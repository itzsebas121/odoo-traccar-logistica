# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta
from unittest import mock

import requests

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from ..models import traccar_server as modulo
from ..models.logistica_traccar_util import haversine_m, knots_to_kmh
from .test_conector import CABECERAS, _fake_traccar, _posicion, _respuesta

DESDE = datetime(2026, 11, 6, 11, 0, 0)
HASTA = datetime(2026, 11, 6, 13, 0, 0)
LAT, LON = -1.2417, -78.6197
# 0,00027 grados de latitud son unos 30 m; 0,0045 son unos 500 m.
CERCA = 0.00027
LEJOS = 0.0045


class _BaseMonitoreo:
    """Datos comunes: vehículo con dispositivo y una ruta en recorrido con una parada."""

    def _preparar(self):
        self._parche = mock.patch.object(
            modulo.TraccarServer, '_get_auth_headers', return_value=CABECERAS)
        self._parche.start()
        self.addCleanup(self._parche.stop)
        self.servidor = self.env['traccar.server'].create({'name': 'Servidor monitoreo'})
        marca = self.env['fleet.vehicle.model.brand'].create({'name': 'MarcaMon'})
        modelo = self.env['fleet.vehicle.model'].create({'name': 'ModeloMon', 'brand_id': marca.id})
        conductor = self.env['res.partner'].create({'name': 'Conductor Mon', 'is_driver': True})
        self.vehiculo = self.env['fleet.vehicle'].create({
            'model_id': modelo.id, 'license_plate': 'MON-0001', 'driver_id': conductor.id})
        self.dispositivo = self.env['traccar.device'].create({
            'name': 'MON-1', 'unique_id': 'MON-1', 'traccar_id': 41, 'server_id': self.servidor.id})
        self.vehiculo.traccar_device_id = self.dispositivo.id

    def _entrega_preparada(self):
        cliente = self.env['res.partner'].create({'name': 'Cliente Mon'})
        producto = self.env['product.product'].create({
            'name': 'Producto Mon', 'type': 'consu', 'list_price': 5})
        pedido = self.env['sale.order'].create({
            'partner_id': cliente.id, 'delivery_latitude': LAT, 'delivery_longitude': LON,
            'order_line': [(0, 0, {'product_id': producto.id, 'product_uom_qty': 1})]})
        pedido.action_confirm()
        entrega = pedido.logistica_entrega_id
        entrega.action_marcar_preparado()
        return entrega

    def _ruta_en_recorrido(self):
        entrega = self._entrega_preparada()
        ruta = self.env['logistica.ruta'].create({
            'vehicle_id': self.vehiculo.id, 'driver_id': self.vehiculo.driver_id.id,
            'bodega_id': self.env['logistica.bodega'].get_bodega_activa().id,
            'stop_ids': [(0, 0, {'entrega_id': entrega.id, 'sequence': 1})]})
        ruta.action_aprobar_plan()
        ruta.action_confirmar_carga()
        ruta.action_iniciar_recorrido()
        return ruta, entrega


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestMonitoreoTraccar(_BaseMonitoreo, TransactionCase):

    def setUp(self):
        super().setUp()
        self._preparar()

    # ----------------------------------------------------------- posiciones
    def test_sincronizacion_crea_posicion_por_vehiculo(self):
        with mock.patch.object(modulo.requests, 'get', side_effect=_fake_traccar(
                posiciones={41: [_posicion(2001, lat=LAT, lon=LON)]})):
            self.servidor._sincronizar_todo()
        posicion = self.env['logistica.traccar.posicion'].search([('traccar_position_id', '=', 2001)])
        self.assertEqual(posicion.vehicle_id, self.vehiculo)
        self.assertEqual(posicion.device_id, self.dispositivo)

    def test_nudos_a_kmh(self):
        self.assertEqual(knots_to_kmh(10), 18.52)

    def test_haversine_30_m(self):
        self.assertAlmostEqual(haversine_m(LAT, LON, LAT + CERCA, LON), 30.0, delta=1.0)

    # ------------------------------------------------------- GPS desactualizado
    def test_posicion_desactualizada_marca_stale(self):
        umbral = self.dispositivo._umbral_desactualizado_s()
        ahora = fields.Datetime.now()
        self.dispositivo.sudo().write({
            'last_latitude': LAT, 'last_longitude': LON, 'last_speed': 12.0,
            'last_position_time': ahora - timedelta(seconds=umbral + 1)})
        self.assertTrue(self.dispositivo.is_stale)
        estado = self.dispositivo._estado_gps()
        self.assertTrue(estado['desactualizado'])
        self.assertGreaterEqual(estado['antiguedad_s'], umbral + 1)
        ultima = estado['ultima_ubicacion_conocida']
        self.assertEqual((ultima['latitud'], ultima['longitud']), (LAT, LON))
        self.dispositivo.sudo().write({'last_position_time': ahora - timedelta(seconds=10)})
        self.assertFalse(self.dispositivo.is_stale)
        self.assertFalse(self.dispositivo._estado_gps()['desactualizado'])

    def test_sin_posicion_no_inventa_ubicacion(self):
        estado = self.dispositivo._estado_gps()
        self.assertFalse(estado['tiene_posicion'])
        self.assertIsNone(estado['ultima_ubicacion_conocida'])
        self.assertIsNone(estado['antiguedad_s'])

    def test_traccar_caido_no_rompe(self):
        entrega = self._entrega_preparada()
        reloj = mock.patch.object(modulo, 'time')
        reloj.start()
        self.addCleanup(reloj.stop)
        with mock.patch.object(modulo.requests, 'get', side_effect=requests.ConnectionError('caído')):
            self.servidor.cron_sincronizar()  # no debe lanzar excepción
        self.assertEqual(self.servidor.state, 'error')
        self.assertTrue(self.servidor.last_error_message)
        self.assertEqual(entrega.state, 'preparado')

    # ----------------------------------------------------- llegada por proximidad
    def test_llegada_por_proximidad_no_entrega(self):
        ruta, entrega = self._ruta_en_recorrido()
        parada = ruta.stop_ids
        ahora = fields.Datetime.now()
        self.dispositivo._registrar_posicion(ahora, LAT + CERCA, LON, 10.0)
        self.assertTrue(parada.arrival_candidate_at)
        self.assertEqual(entrega.state, 'en_recorrido')  # la llegada nunca entrega
        self.assertEqual(parada.state, 'pendiente')
        eventos = entrega.event_ids.filtered(lambda e: e.event_type == 'posible_llegada')
        self.assertEqual(len(eventos), 1)
        self.assertTrue(eventos.gps_available)
        # Otra posición cercana no duplica el evento.
        self.dispositivo._registrar_posicion(ahora + timedelta(seconds=30), LAT + CERCA, LON, 5.0)
        self.assertEqual(len(entrega.event_ids.filtered(lambda e: e.event_type == 'posible_llegada')), 1)

    def test_posicion_lejana_no_marca_llegada(self):
        ruta, entrega = self._ruta_en_recorrido()
        self.dispositivo._registrar_posicion(fields.Datetime.now(), LAT + LEJOS, LON, 30.0)
        self.assertFalse(ruta.stop_ids.arrival_candidate_at)
        self.assertFalse(entrega.event_ids.filtered(lambda e: e.event_type == 'posible_llegada'))

    def test_gps_se_adjunta_a_la_entrega_del_vehiculo(self):
        """El snapshot GPS sale del vínculo de la ficha de flota (antes devolvía siempre «sin GPS»)."""
        ruta, entrega = self._ruta_en_recorrido()
        self.dispositivo._registrar_posicion(fields.Datetime.now(), LAT + LEJOS, LON, 20.0)
        snapshot = entrega._gps_snapshot()
        self.assertTrue(snapshot['available'])
        self.assertAlmostEqual(snapshot['latitude'], LAT + LEJOS, places=5)

    # ------------------------------------------------------------- informes
    def test_informes_parametros(self):
        casos = (('get_route_report', 'route'), ('get_trips', 'trips'), ('get_stops', 'stops'))
        for metodo, ruta in casos:
            with mock.patch.object(modulo.requests, 'get', return_value=_respuesta([])) as get:
                getattr(self.servidor, metodo)(self.dispositivo, DESDE, HASTA)
            self.assertTrue(get.call_args.args[0].endswith('/api/reports/' + ruta), metodo)
            self.assertEqual(get.call_args.kwargs['params'], {
                'deviceId': 41, 'from': '2026-11-06T11:00:00Z', 'to': '2026-11-06T13:00:00Z'})
            self.assertEqual(get.call_args.kwargs['headers']['Accept'], 'application/json')

    def test_informes_solo_personal_de_flota(self):
        usuario = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Sin flota', 'login': 'sin-flota-informes',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        with mock.patch.object(modulo.requests, 'get', return_value=_respuesta([])) as get:
            with self.assertRaises(AccessError):
                self.servidor.with_user(usuario).get_route_report(self.dispositivo, DESDE, HASTA)
        self.assertFalse(get.called)


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestMonitoreoHttp(_BaseMonitoreo, HttpCase):

    def setUp(self):
        super().setUp()
        self._preparar()
        grupos = [self.env.ref(x).id for x in ('base.group_user', 'fleet.fleet_group_user')]
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Monitor', 'login': 'monitor-flota', 'password': 'monitor-flota-clave',
            'groups_id': [(6, 0, grupos)]})
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Sin flota', 'login': 'sin-flota-http', 'password': 'sin-flota-clave',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})

    def test_monitoreo_sin_credenciales(self):
        ruta, _entrega = self._ruta_en_recorrido()
        self.dispositivo._registrar_posicion(fields.Datetime.now(), LAT + LEJOS, LON, 20.0)
        self.servidor.sudo().write({'username': 'usuario-secreto@logistica.local'})
        self.servidor.password = 'clave-secreta-mon'
        cabeceras = dict(CABECERAS, Authorization='Basic Y3JlZGVuY2lhbGVz')
        recorrido = [{'latitude': LAT + LEJOS, 'longitude': LON}]
        with mock.patch.object(modulo.TraccarServer, '_get_auth_headers', return_value=cabeceras), \
                mock.patch.object(modulo.requests, 'get', return_value=_respuesta(recorrido)):
            self.authenticate('monitor-flota', 'monitor-flota-clave')
            respuesta = self.url_open('/logistica/monitoreo/data')
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.text
        for prohibido in ('password', 'Authorization', 'Basic', 'clave-secreta-mon',
                          'usuario-secreto', 'base_url', self.servidor.base_url):
            self.assertNotIn(prohibido, cuerpo)
        datos = json.loads(cuerpo)
        vehiculo = next(v for v in datos['vehiculos'] if v['placa'] == 'MON-0001')
        self.assertEqual(vehiculo['ruta']['recorrido'], [[LAT + LEJOS, LON]])
        self.assertTrue(vehiculo['gps']['tiene_posicion'])
        self.assertFalse(vehiculo['gps']['desactualizado'])

    def test_monitoreo_muestra_ultima_ubicacion_conocida(self):
        umbral = self.dispositivo._umbral_desactualizado_s()
        self.dispositivo.sudo().write({
            'last_latitude': LAT, 'last_longitude': LON, 'last_speed': 0.0,
            'last_position_time': fields.Datetime.now() - timedelta(seconds=umbral + 60)})
        self.authenticate('monitor-flota', 'monitor-flota-clave')
        datos = json.loads(self.url_open('/logistica/monitoreo/data').text)
        vehiculo = next(v for v in datos['vehiculos'] if v['placa'] == 'MON-0001')
        self.assertTrue(vehiculo['gps']['desactualizado'])
        self.assertGreaterEqual(vehiculo['gps']['antiguedad_s'], umbral + 60)
        self.assertEqual(vehiculo['gps']['ultima_ubicacion_conocida']['latitud'], LAT)

    def test_monitoreo_exige_personal_de_flota(self):
        self.authenticate('sin-flota-http', 'sin-flota-clave')
        self.assertEqual(self.url_open('/logistica/monitoreo/data').status_code, 403)
        self.assertEqual(self.url_open('/logistica/monitoreo').status_code, 403)

    def test_pagina_de_monitoreo_carga(self):
        self.authenticate('monitor-flota', 'monitor-flota-clave')
        respuesta = self.url_open('/logistica/monitoreo')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('monitoreo-mapa', respuesta.text)
        self.assertNotIn('password', respuesta.text)
