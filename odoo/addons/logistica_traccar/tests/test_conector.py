# -*- coding: utf-8 -*-
import base64
from datetime import datetime
from unittest import mock
from urllib.parse import parse_qs, urlparse

import requests

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from ..models import traccar_server as modulo

DESDE = datetime(2026, 11, 6, 11, 0, 0)
HASTA = datetime(2026, 11, 6, 13, 0, 0)
CABECERAS = {'Accept': 'application/json'}


def _respuesta(datos, status=200):
    respuesta = mock.Mock(status_code=status, text=repr(datos))
    respuesta.json.return_value = datos
    return respuesta


def _posicion(id_, fix='2026-11-06T12:00:00.000+00:00', lat=45.0, lon=-120.0,
              velocidad=10, metros=5000, valido=True):
    return {
        'id': id_, 'deviceId': 4, 'fixTime': fix, 'latitude': lat, 'longitude': lon,
        'speed': velocidad, 'valid': valido, 'attributes': {'totalDistance': metros},
    }


def _fake_traccar(posiciones=None, eventos=None, dispositivos=None, caidos=()):
    """Sustituto de requests.get: responde por ruta y deviceId (en params o en la URL); caidos lanza ConnectionError."""
    posiciones = posiciones or {}
    eventos = eventos or {}

    def get(url, headers=None, params=None, timeout=None):
        partes = urlparse(url)
        consulta = parse_qs(partes.query)
        if 'deviceId' in consulta:
            id_dispositivo = int(consulta['deviceId'][0])
        else:
            id_dispositivo = (params or {}).get('deviceId')
        if id_dispositivo in caidos:
            raise requests.ConnectionError('Traccar no responde')
        if partes.path.endswith('/api/devices'):
            return _respuesta(dispositivos or [])
        if partes.path.endswith('/api/positions'):
            return _respuesta(posiciones.get(id_dispositivo, []))
        if partes.path.endswith('/api/reports/events'):
            return _respuesta(eventos.get(id_dispositivo, []))
        raise AssertionError('ruta inesperada: %s' % url)
    return get


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestConectorTraccar(TransactionCase):
    """Sincronización desde Traccar con requests parcheado (sin red)."""

    def setUp(self):
        super().setUp()
        self._parche_cabeceras = mock.patch.object(
            modulo.TraccarServer, '_get_auth_headers', return_value=CABECERAS)
        self._parche_cabeceras.start()
        self.addCleanup(self._parche_cabeceras.stop)
        self.servidor = self.env['traccar.server'].create({'name': 'Servidor de sincronización'})
        marca = self.env['fleet.vehicle.model.brand'].create({'name': 'MarcaSync'})
        self.modelo = self.env['fleet.vehicle.model'].create({
            'name': 'ModeloSync', 'brand_id': marca.id})
        self.vehiculo = self._vehiculo('SYN-0001')
        self.dispositivo = self._dispositivo(4, 'SYNC-1', self.vehiculo)

    def _vehiculo(self, placa):
        return self.env['fleet.vehicle'].create({
            'model_id': self.modelo.id, 'license_plate': placa})

    def _dispositivo(self, traccar_id, unique_id, vehiculo=None, activo=True):
        """Dispositivo; el vehículo se vincula desde la ficha de flota (fleet.vehicle.traccar_device_id, F1-R20)."""
        dispositivo = self.env['traccar.device'].create({
            'name': unique_id,
            'unique_id': unique_id,
            'traccar_id': traccar_id,
            'server_id': self.servidor.id,
            'is_active': activo,
        })
        if vehiculo:
            vehiculo.traccar_device_id = dispositivo.id
        return dispositivo

    def _usuario(self, login, *grupos_xmlid):
        ids = [self.env.ref(x).id for x in ('base.group_user',) + grupos_xmlid]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'groups_id': [(6, 0, ids)]})

    def _traccar(self, **kwargs):
        parche = mock.patch.object(modulo.requests, 'get', side_effect=_fake_traccar(**kwargs))
        get = parche.start()
        self.addCleanup(parche.stop)
        return get

    def _sin_esperas(self):
        parche = mock.patch.object(modulo, 'time')
        reloj = parche.start()
        self.addCleanup(parche.stop)
        return reloj.sleep

    def _cuenta_posiciones(self, dispositivo):
        return self.env['logistica.traccar.posicion'].search_count(
            [('device_id', '=', dispositivo.id)])

    def _llamadas(self, get, sufijo, traccar_id):
        return [llamada for llamada in get.call_args_list
                if llamada.args[0].endswith(sufijo)
                and (llamada.kwargs.get('params') or {}).get('deviceId') == traccar_id]

    def test_mapeo_nudos_y_odometro(self):
        self._traccar(posiciones={4: [_posicion(101, velocidad=10, metros=5000)]})
        nuevas = self.servidor._sincronizar_posiciones(DESDE, HASTA)
        posicion = self.env['logistica.traccar.posicion'].search(
            [('traccar_position_id', '=', 101)])
        self.assertEqual(nuevas, 1)
        self.assertEqual(posicion.speed_kmh, 18.52)
        self.assertEqual(posicion.odometer_km, 5.0)
        self.assertEqual(posicion.device_id, self.dispositivo)
        self.assertEqual(posicion.vehicle_id, self.vehiculo)
        self.assertTrue(posicion.valid)

    def test_idempotencia(self):
        self._traccar(posiciones={4: [_posicion(101)]})
        self.servidor._sincronizar_todo()
        self.servidor._sincronizar_todo()
        self.assertEqual(self.env['logistica.traccar.posicion'].search_count(
            [('traccar_position_id', '=', 101)]), 1)

    def test_reprocesar_ventana_no_duplica(self):
        self._traccar(posiciones={4: [
            _posicion(101), _posicion(102, fix='2026-11-06T12:30:00.000+00:00')]})
        primera = self.servidor._sincronizar_posiciones(DESDE, HASTA)
        segunda = self.servidor._sincronizar_posiciones(DESDE, HASTA)
        self.assertEqual(primera, 2)
        self.assertEqual(segunda, 0)
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 2)

    def test_fallo_red_no_avanza_watermark(self):
        self._sin_esperas()
        self._traccar(posiciones={4: [_posicion(101)]}, caidos=(4,))
        marca = datetime(2026, 11, 6, 12, 0, 0)
        self.dispositivo.position_watermark = marca
        with self.assertLogs(modulo._logger.name, 'WARNING'):
            with self.assertRaises(UserError):
                self.servidor._sincronizar_posiciones(DESDE, HASTA)
            resumen = self.servidor._sincronizar_todo()
        self.assertEqual(resumen['errores'], 1)
        self.assertEqual(self.dispositivo.position_watermark, marca)
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 0)
        self.assertTrue(self.servidor.last_error_message)

    def test_reintentos_backoff(self):
        espera = self._sin_esperas()
        get = self._traccar(caidos=(4,))
        with self.assertLogs(modulo._logger.name, 'WARNING'), self.assertRaises(UserError):
            self.servidor._request('/api/positions', {'deviceId': 4})
        self.assertEqual(get.call_count, 3)
        self.assertEqual(espera.call_args_list, [mock.call(1), mock.call(2)])
        self.assertEqual(get.call_args.kwargs['headers']['Accept'], 'application/json')

    def test_aislamiento_por_dispositivo(self):
        self._sin_esperas()
        otro_vehiculo = self._vehiculo('SYN-0002')
        otro = self._dispositivo(5, 'SYNC-2', otro_vehiculo)
        self._traccar(posiciones={5: [_posicion(201)]}, caidos=(4,))
        with self.assertLogs(modulo._logger.name, 'WARNING'):
            resumen = self.servidor._sincronizar_todo()
        self.assertEqual(resumen['errores'], 1)
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 0)
        self.assertFalse(self.dispositivo.position_watermark)
        self.assertEqual(self._cuenta_posiciones(otro), 1)
        self.assertTrue(otro.position_watermark)

    def test_dispositivo_sin_vehiculo_ignorado(self):
        self._dispositivo(6, 'SYNC-3')
        get = self._traccar(posiciones={6: [_posicion(301)]})
        nuevas = self.servidor._sincronizar_posiciones(DESDE, HASTA)
        self.assertEqual(nuevas, 0)
        self.assertFalse(self._llamadas(get, '/api/positions', 6))
        self.assertFalse(self.env['logistica.traccar.posicion'].search(
            [('traccar_position_id', '=', 301)]))

    def test_posicion_invalida_se_descarta(self):
        self._traccar(posiciones={4: [
            _posicion(401, lat=95.0),
            _posicion(402, lat=0.0, lon=0.0),
            _posicion(403, lat=None),
            _posicion(0),
            _posicion(404),
        ]})
        estadisticas = self.servidor._posiciones_dispositivo(self.dispositivo, self.vehiculo, DESDE, HASTA)
        self.assertEqual(estadisticas['nuevas'], 1)
        self.assertEqual(estadisticas['descartadas'], 4)
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 1)

    def test_ventana_con_solape_de_60_s(self):
        self.dispositivo.position_watermark = datetime(2026, 11, 6, 12, 0, 0)
        get = self._traccar(posiciones={4: [_posicion(101)]})
        self.servidor._sincronizar_todo()
        llamada = self._llamadas(get, '/api/positions', 4)[0]
        self.assertEqual(llamada.kwargs['params']['from'], '2026-11-06T11:59:00Z')

    def test_dispositivo_inactivo_ignorado(self):
        self.dispositivo.is_active = False
        get = self._traccar(posiciones={4: [_posicion(101)]})
        resumen = self.servidor._sincronizar_todo()
        self.assertEqual(resumen['posiciones'], 0)
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 0)
        self.assertFalse(self._llamadas(get, '/api/positions', 4))

    def test_boton_legacy_usuario_plano_escribe_dispositivo(self):
        usuario = self._usuario('usuario-gps-plano')
        self._traccar(posiciones={4: [_posicion(501, lat=40.0, lon=-70.0, velocidad=10)]})
        self.dispositivo.with_user(usuario).action_fetch_latest_position()
        self.assertEqual(self.dispositivo.last_latitude, 40.0)
        self.assertAlmostEqual(self.dispositivo.last_speed, 18.52)

    def test_sincronizar_dispositivos_solo_gestor(self):
        usuario = self._usuario('usuario-sync-plano')
        gestor = self._usuario('usuario-sync-gestor', 'fleet.fleet_group_manager')
        get = self._traccar(dispositivos=[
            {'id': 7, 'uniqueId': 'SYNC-7', 'name': 'Equipo nuevo', 'status': 'online'}])
        with self.assertRaises(AccessError):
            self.servidor.with_user(usuario).action_sync_devices()
        self.assertFalse(get.called)  # el usuario sin permiso se rechaza antes de llamar a Traccar
        self.servidor.with_user(gestor).action_sync_devices()
        nuevo = self.env['traccar.device'].search(
            [('server_id', '=', self.servidor.id), ('traccar_id', '=', 7)])
        self.assertEqual(nuevo.unique_id, 'SYNC-7')

    def test_sincronizacion_manual_solo_gestor(self):
        usuario = self._usuario('usuario-manual-plano')
        gestor = self._usuario('usuario-manual-gestor', 'fleet.fleet_group_manager')
        self._traccar(posiciones={4: [_posicion(601)]})
        with self.assertRaises(AccessError):
            self.servidor.with_user(usuario).action_sincronizar_ahora()
        self.servidor.with_user(gestor).action_sincronizar_ahora()
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 1)

    def test_ultima_posicion_del_vehiculo(self):
        self._traccar(posiciones={4: [
            _posicion(701, fix='2026-11-06T12:30:00.000+00:00', lat=45.1, lon=-120.2),
            _posicion(702, fix='2026-11-06T12:10:00.000+00:00', lat=10.0, lon=-10.0),
        ]})
        self.servidor._sincronizar_todo()
        self.assertAlmostEqual(self.vehiculo.traccar_latitude, 45.1, places=5)
        self.assertEqual(self.dispositivo.last_position_time, datetime(2026, 11, 6, 12, 30, 0))
        self.assertAlmostEqual(self.vehiculo.traccar_speed, 18.52)

    def test_vehiculo_sale_de_la_ficha_de_flota(self):
        """F1-R20: el vehículo sale solo de fleet.vehicle.traccar_device_id, no de traccar.device.vehicle_id."""
        otro_vehiculo = self._vehiculo('SYN-0003')
        self.dispositivo.vehicle_id = otro_vehiculo.id
        self._traccar(posiciones={4: [_posicion(901)]})
        self.servidor._sincronizar_posiciones(DESDE, HASTA)
        posicion = self.env['logistica.traccar.posicion'].search(
            [('traccar_position_id', '=', 901)])
        self.assertEqual(posicion.vehicle_id, self.vehiculo)
        self.assertNotEqual(posicion.vehicle_id, otro_vehiculo)

    def test_sincronizacion_sin_metodos_publicos(self):
        """F1-R16: las operaciones que escriben con sudo son privadas; el único punto público es action_sincronizar_ahora."""
        for nombre in ('sincronizar_posiciones', 'sincronizar_eventos', 'sincronizar_todo'):
            self.assertFalse(hasattr(modulo.TraccarServer, nombre), nombre)
        self.assertTrue(hasattr(modulo.TraccarServer, 'action_sincronizar_ahora'))

    def _valores_visibles(self, registro, campo):
        """Valores del campo que devuelven read y search_read (RPC). Vacío si Odoo rechaza la lectura."""
        valores = []
        lecturas = (
            lambda: registro.read([campo]),
            lambda: registro.search_read([('id', '=', registro.id)], [campo]),
        )
        for lectura in lecturas:
            try:
                valores += [fila.get(campo) for fila in lectura()]
            except AccessError:
                pass
        return valores

    def test_usuario_interno_no_cambia_base_url(self):
        """Seguridad: el usuario interno no puede redirigir el servidor (las credenciales irían al nuevo host)."""
        usuario = self._usuario('usuario-url-plano')
        with self.assertRaises(AccessError):
            self.servidor.with_user(usuario).write({'base_url': 'host-distinto'})
        self.assertNotEqual(self.servidor.base_url, 'host-distinto')

    def test_usuario_interno_no_lee_contrasena(self):
        """Seguridad: la contraseña del servidor Traccar solo la ve un gestor de flota."""
        secreto = 'clave-de-prueba-no-visible'
        self.servidor.password = secreto
        usuario = self._usuario('usuario-clave-plano')
        self.assertNotIn(secreto, self._valores_visibles(self.servidor.with_user(usuario), 'password'))

    def test_credencial_la_lee_el_servidor_no_el_llamador(self):
        """Seguridad: el usuario interno no ve la contraseña, pero el conector la usa con sudo para llamar a Traccar."""
        self._parche_cabeceras.stop()  # usar la implementación real de _get_auth_headers
        secreto = 'clave-de-prueba-no-visible'
        self.servidor.sudo().password = secreto
        usuario = self._usuario('usuario-cabecera-plano')
        cabeceras = self.servidor.with_user(usuario)._get_auth_headers()
        esperada = base64.b64encode(f'{self.servidor.username}:{secreto}'.encode('utf-8')).decode('utf-8')
        self.assertEqual(cabeceras['Authorization'], f'Basic {esperada}')

    def test_gestor_de_flota_cambia_base_url(self):
        """Seguridad: el gestor de flota sí puede cambiar la URL del servidor."""
        gestor = self._usuario('usuario-url-gestor', 'fleet.fleet_group_manager')
        self.servidor.with_user(gestor).write({'base_url': 'host-nuevo'})
        self.assertEqual(self.servidor.base_url, 'host-nuevo')

    def _sincronizacion_simulada(self):
        """Sustituye la sincronización por un espejo para comprobar solo la puerta de acceso."""
        parche = mock.patch.object(modulo.TraccarServer, '_sincronizar_todo', autospec=True)
        self.addCleanup(parche.stop)
        return parche.start()

    def test_cron_rechaza_usuario_interno(self):
        """F1-R22: cron_sincronizar es público por ir.cron; un usuario interno no lo puede ejecutar."""
        usuario = self._usuario('usuario-cron-plano')
        sincronizar = self._sincronizacion_simulada()
        with self.assertRaises(AccessError):
            self.env['traccar.server'].with_user(usuario).cron_sincronizar()
        sincronizar.assert_not_called()

    def test_cron_permite_gestor_de_flota(self):
        """F1-R22: un gestor de flota sí puede ejecutar cron_sincronizar."""
        gestor = self._usuario('usuario-cron-gestor', 'fleet.fleet_group_manager')
        sincronizar = self._sincronizacion_simulada()
        self.env['traccar.server'].with_user(gestor).cron_sincronizar()
        sincronizar.assert_called()

    def test_cron_ejecuta_como_sistema(self):
        """F1-R22: la llamada del sistema (superusuario, como el ir.cron) ejecuta la sincronización."""
        sincronizar = self._sincronizacion_simulada()
        self.env['traccar.server'].sudo().cron_sincronizar()
        sincronizar.assert_called()

    def test_cron_sincroniza_servidores_activos(self):
        # La base de desarrollo puede tener otros servidores activos; solo este se sincroniza en la prueba.
        self.env['traccar.server'].search([('id', '!=', self.servidor.id)]).write({'active': False})
        self._traccar(posiciones={4: [_posicion(801)]})
        self.env['traccar.server'].cron_sincronizar()
        self.assertEqual(self._cuenta_posiciones(self.dispositivo), 1)
