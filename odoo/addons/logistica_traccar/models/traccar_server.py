# -*- coding: utf-8 -*-
import base64
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError

from .logistica_traccar_util import knots_to_kmh, meters_to_km, valid_latlon

_logger = logging.getLogger(__name__)

_INTENTOS = 3
# Esperas tras el 1.er y el 2.º fallo; el 3.er intento agota sin esperar.
_ESPERAS = (1, 2)
_TIMEOUT = 10
# Cada dispositivo se consulta desde su watermark menos este solape, para no perder posiciones tardías.
_SOLAPE = timedelta(seconds=60)
_TIPOS_EVENTO = ['deviceOverspeed', 'geofenceEnter', 'geofenceExit', 'deviceOnline', 'deviceOffline']


def _iso_utc(fecha):
    """Fecha UTC (sin zona) en ISO 8601 con sufijo Z, el formato de los parámetros from y to."""
    return fecha.strftime('%Y-%m-%dT%H:%M:%SZ')


def _fecha_utc(texto):
    """Fecha ISO de Traccar a datetime UTC sin zona (formato de Odoo). None si no es válida."""
    if not texto:
        return None
    try:
        fecha = datetime.fromisoformat(str(texto).replace('Z', '+00:00'))
    except ValueError:
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


_AUTORIZACION = re.compile(r'(?i)\b(Basic|Bearer)\s+[A-Za-z0-9+/=._~-]+')


def _sin_secretos(texto, secreto=None):
    """Quita de un mensaje de error cualquier cabecera de autorización y el secreto del servidor."""
    texto = _AUTORIZACION.sub(r'\1 ***', str(texto))
    return texto.replace(secreto, '***') if secreto else texto


def _a_utc(fecha):
    """Datetime a UTC sin zona; una fecha sin zona ya se entiende UTC (formato de Odoo)."""
    if fecha.tzinfo is not None:
        return fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


def _parametros(dispositivo, desde, hasta):
    return {'deviceId': dispositivo.traccar_id, 'from': _iso_utc(desde), 'to': _iso_utc(hasta)}


def _odometro_km(posicion):
    metros = (posicion.get('attributes') or {}).get('totalDistance')
    return meters_to_km(metros) if metros is not None else None


class TraccarServer(models.Model):
    _name = 'traccar.server'
    _description = 'Configuración de Servidor Traccar GPS'

    name = fields.Char(string='Nombre de Servidor', required=True, default='Traccar Principal')
    base_url = fields.Char(
        string='URL del Servidor Traccar',
        required=True,
        default='http://traccar:8082',
        help='URL base interna o externa de Traccar (ejemplo: http://traccar:8082)'
    )
    auth_type = fields.Selection([
        ('basic', 'Autenticación Básica (Usuario y Contraseña)'),
        ('token', 'Token de Sesión / API Bearer'),
    ], string='Tipo de Autenticación', default='basic', required=True)

    username = fields.Char(string='Usuario / Correo Traccar', default='admin@logistica.local')
    # No almacenado: el valor vive en traccar.server.clave. Así no se puede agrupar ni almacenar en esta tabla (F1-R24).
    password = fields.Char(
        string='Contraseña / Token Traccar',
        compute='_compute_password',
        inverse='_inverse_password',
        search='_buscar_password',
        store=False,
    )

    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Sin Verificar'),
        ('connected', 'Conectado'),
        ('error', 'Error de Conexión'),
    ], string='Estado de Conexión', default='draft', readonly=True)

    last_sync_date = fields.Datetime(string='Última Sincronización', readonly=True)
    last_error_message = fields.Text(string='Detalle del Último Error', readonly=True)

    device_ids = fields.One2many('traccar.device', 'server_id', string='Dispositivos Vinculados')
    device_count = fields.Integer(string='Total Dispositivos', compute='_compute_device_count')

    @api.depends('device_ids')
    def _compute_device_count(self):
        for rec in self:
            rec.device_count = len(rec.device_ids)

    @api.depends_context('uid')
    def _compute_password(self):
        """Devuelve el secreto solo a un gestor de flota; a los demás, False (F1-R24)."""
        gestor = self.env.user.has_group('fleet.fleet_group_manager')
        ids = [i for i in self.ids if isinstance(i, int)]
        por_servidor = {}
        if gestor and ids:
            claves = self.env['traccar.server.clave'].sudo().search([('server_id', 'in', ids)])
            por_servidor = {clave.server_id.id: clave.password for clave in claves}
        for servidor in self:
            servidor.password = por_servidor.get(servidor.id, False)

    def _inverse_password(self):
        """Escribe la contraseña en traccar.server.clave (una fila por servidor)."""
        Clave = self.env['traccar.server.clave'].sudo()
        for servidor in self:
            clave = Clave.search([('server_id', '=', servidor.id)], limit=1)
            if clave:
                clave.password = servidor.password
            else:
                Clave.create({'server_id': servidor.id, 'password': servidor.password})

    def _buscar_password(self, operador, valor):
        raise UserError(_('La contraseña de Traccar no se puede usar en búsquedas.'))

    def _secreto(self):
        """Contraseña o token del servidor, leídos de traccar.server.clave con sudo. Solo uso interno del conector."""
        self.ensure_one()
        clave = self.env['traccar.server.clave'].sudo().search([('server_id', '=', self.id)], limit=1)
        return clave.password or False

    def _get_auth_headers(self):
        self.ensure_one()
        # El secreto sale de traccar.server.clave con sudo: el llamador no necesita ser gestor de flota (F1-R24).
        secreto = self._secreto()
        servidor = self.sudo()
        headers = {'Accept': 'application/json'}
        if servidor.auth_type == 'basic':
            if not servidor.username or not secreto:
                raise UserError(_('Debe configurar usuario y contraseña para la autenticación básica.'))
            raw_credentials = f"{servidor.username}:{secreto}"
            encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
            headers['Authorization'] = f"Basic {encoded}"
        elif servidor.auth_type == 'token':
            if not secreto:
                raise UserError(_('Debe configurar el token de autorización.'))
            headers['Authorization'] = f"Bearer {secreto}"
        return headers

    def _limpiar_error(self, texto):
        self.ensure_one()
        return _sin_secretos(texto, self._secreto())

    def action_test_connection(self):
        self.ensure_one()
        # Envía la credencial a la base_url configurada: solo un gestor de flota puede dispararlo.
        self._exigir_gestor_flota()
        url = self.base_url.rstrip('/') + '/api/server'
        headers = self._get_auth_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                version = data.get('version', 'Desconocida')
                self.write({
                    'state': 'connected',
                    'last_error_message': False,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Conexión Exitosa'),
                        'message': _('Conectado con éxito a Traccar Server v%s') % version,
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                error_msg = self._limpiar_error(f"HTTP {response.status_code}: {response.text[:200]}")
                self.write({
                    'state': 'error',
                    'last_error_message': error_msg,
                })
                raise UserError(_('Fallo de conexión a Traccar: %s') % error_msg)
        except requests.RequestException as e:
            error_msg = self._limpiar_error(e)
            self.write({
                'state': 'error',
                'last_error_message': error_msg,
            })
            raise UserError(_('No se pudo establecer conexión con Traccar: %s') % error_msg)

    # ------------------------------------------------------------------
    # Acceso a Traccar
    # ------------------------------------------------------------------

    def _request(self, path, params=None):
        """GET a la API de Traccar con hasta _INTENTOS intentos. Al agotarlos registra el error y lanza UserError."""
        self.ensure_one()
        url = self.base_url.rstrip('/') + path
        headers = self._get_auth_headers()
        headers['Accept'] = 'application/json'  # los reportes sin este encabezado devuelven XLSX
        error = ''
        for intento in range(_INTENTOS):
            try:
                respuesta = requests.get(url, headers=headers, params=params, timeout=_TIMEOUT)
                if respuesta.status_code == 200:
                    return respuesta.json()
                error = self._limpiar_error(f"HTTP {respuesta.status_code}: {respuesta.text[:200]}")
            except (requests.RequestException, ValueError) as exc:
                error = self._limpiar_error(exc)
            _logger.warning('traccar_request_error ruta=%s intento=%s error=%s', path, intento + 1, error)
            if intento < len(_ESPERAS):
                time.sleep(_ESPERAS[intento])
        self.sudo().write({'state': 'error', 'last_error_message': error})
        raise UserError(_('No se pudo consultar Traccar (%s): %s') % (path, error))

    def _exigir_gestor_flota(self):
        """Los botones manuales solo los puede usar un gestor de flota. El cron no pasa por aquí."""
        if not self.env.user.has_group('fleet.fleet_group_manager'):
            raise AccessError(_('Solo un gestor de flota puede ejecutar esta sincronización.'))

    def _registrar_error(self, mensaje):
        self.sudo().write({'state': 'error', 'last_error_message': mensaje})

    def _notificar(self, titulo, mensaje, tipo):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': titulo, 'message': mensaje, 'sticky': False, 'type': tipo},
        }

    # ------------------------------------------------------------------
    # Dispositivos
    # ------------------------------------------------------------------

    def _sincronizar_dispositivos(self):
        """Crea o actualiza traccar.device desde /api/devices (escritura con sudo, F1-R18)."""
        self.ensure_one()
        datos = self._request('/api/devices')
        Dispositivo = self.env['traccar.device'].sudo()
        contador = 0
        for item in datos or []:
            traccar_id = item.get('id')
            if not traccar_id or traccar_id <= 0:
                continue
            unique_id = str(item.get('uniqueId', ''))
            vals = {
                'name': item.get('name') or unique_id,
                'unique_id': unique_id,
                'status': item.get('status') or 'unknown',
                'server_id': self.id,
            }
            existente = Dispositivo.search(
                [('server_id', '=', self.id), ('traccar_id', '=', traccar_id)], limit=1)
            if existente:
                existente.write(vals)
            else:
                Dispositivo.create(dict(vals, traccar_id=traccar_id))
            contador += 1
        return contador

    def action_sync_devices(self):
        self.ensure_one()
        self._exigir_gestor_flota()
        contador = self._sincronizar_dispositivos()
        self.sudo().write({
            'last_sync_date': fields.Datetime.now(),
            'state': 'connected',
            'last_error_message': False,
        })
        return self._notificar(
            _('Sincronización Completada'),
            _('Se sincronizaron %d dispositivo(s) desde Traccar.') % contador,
            'success')

    def _vehiculo_del_dispositivo(self, dispositivo):
        """Vehículo del dispositivo según la ficha de flota (fleet.vehicle.traccar_device_id), F1-R20."""
        return self.env['fleet.vehicle'].sudo().search(
            [('traccar_device_id', '=', dispositivo.id)], limit=1)

    def _dispositivos_sincronizables(self):
        """Pares (dispositivo, vehículo) de los dispositivos activos que tienen vehículo."""
        pares = []
        dispositivos = self.env['traccar.device'].sudo().search(
            [('server_id', '=', self.id), ('is_active', '=', True)])
        for dispositivo in dispositivos:
            vehiculo = self._vehiculo_del_dispositivo(dispositivo)
            if vehiculo:
                pares.append((dispositivo, vehiculo))
        return pares

    # ------------------------------------------------------------------
    # Posiciones y eventos
    # ------------------------------------------------------------------

    def _guardar_posiciones(self, dispositivo, vehiculo, datos):
        """Inserta las posiciones nuevas. Descarta ids no positivos, fechas inválidas y coordenadas no válidas."""
        Posicion = self.env['logistica.traccar.posicion'].sudo()
        validas = {}
        descartadas = 0
        maxima_fix = None
        for item in datos or []:
            fix = _fecha_utc(item.get('fixTime'))
            if fix and (maxima_fix is None or fix > maxima_fix):
                maxima_fix = fix
            id_traccar = item.get('id')
            lat, lon = item.get('latitude'), item.get('longitude')
            if (not id_traccar or id_traccar <= 0 or fix is None
                    or lat is None or lon is None or not valid_latlon(lat, lon)):
                descartadas += 1
                continue
            validas[id_traccar] = {
                'device_id': dispositivo.id,
                'vehicle_id': vehiculo.id,
                'traccar_position_id': id_traccar,
                'fix_time': fix,
                'latitude': lat,
                'longitude': lon,
                'speed_kmh': knots_to_kmh(item.get('speed') or 0),
                'odometer_km': _odometro_km(item),
                'valid': bool(item.get('valid')),
            }
        existentes = set(Posicion.search(
            [('traccar_position_id', 'in', list(validas))]).mapped('traccar_position_id'))
        nuevas = [vals for id_traccar, vals in validas.items() if id_traccar not in existentes]
        if nuevas:
            Posicion.create(nuevas)
        if validas:
            ultima = max(validas.values(), key=lambda vals: vals['fix_time'])
            dispositivo.sudo()._registrar_posicion(
                ultima['fix_time'], ultima['latitude'], ultima['longitude'], ultima['speed_kmh'])
        return {'nuevas': len(nuevas), 'descartadas': descartadas, 'maxima_fix': maxima_fix}

    def _guardar_eventos(self, dispositivo, vehiculo, datos):
        """Inserta los eventos nuevos, únicos por id de evento de Traccar. Devuelve cuántos son nuevos."""
        Evento = self.env['logistica.traccar.evento'].sudo()
        validos = {}
        for item in datos or []:
            id_evento = item.get('id')
            if not id_evento or id_evento <= 0:
                continue
            validos[id_evento] = {
                'device_id': dispositivo.id,
                'vehicle_id': vehiculo.id,
                'traccar_event_id': id_evento,
                'event_type': item.get('type'),
                'event_time': _fecha_utc(item.get('eventTime')),
                'geofence_traccar_id': item.get('geofenceId') or False,
                'position_traccar_id': item.get('positionId') or False,
                'attributes': json.dumps(item.get('attributes') or {}, ensure_ascii=False, sort_keys=True),
            }
        existentes = set(Evento.search(
            [('traccar_event_id', 'in', list(validos))]).mapped('traccar_event_id'))
        nuevos = [vals for id_evento, vals in validos.items() if id_evento not in existentes]
        if nuevos:
            Evento.create(nuevos)
        return len(nuevos)

    def _posiciones_dispositivo(self, dispositivo, vehiculo, desde, hasta):
        datos = self._request('/api/positions', _parametros(dispositivo, desde, hasta))
        return self._guardar_posiciones(dispositivo, vehiculo, datos)

    def _eventos_dispositivo(self, dispositivo, vehiculo, desde, hasta):
        datos = self._request(
            '/api/reports/events', dict(_parametros(dispositivo, desde, hasta), type=_TIPOS_EVENTO))
        return self._guardar_eventos(dispositivo, vehiculo, datos)

    def _ventana_desde(self, dispositivo):
        """Inicio de la ventana: el watermark menos el solape; sin watermark, desde que el dispositivo existe en Odoo."""
        if dispositivo.position_watermark:
            return dispositivo.position_watermark - _SOLAPE
        return dispositivo.create_date

    def _sincronizar_dispositivo(self, dispositivo, vehiculo, hasta):
        """Posiciones y eventos de un dispositivo desde su ventana. El watermark avanza solo si ambas consultas van bien."""
        desde = self._ventana_desde(dispositivo)
        posiciones = self._posiciones_dispositivo(dispositivo, vehiculo, desde, hasta)
        eventos = self._eventos_dispositivo(dispositivo, vehiculo, desde, hasta)
        maxima = posiciones['maxima_fix']
        if maxima and (not dispositivo.position_watermark or maxima > dispositivo.position_watermark):
            dispositivo.sudo().write({'position_watermark': maxima})
        return {
            'desde': desde,
            'nuevas': posiciones['nuevas'],
            'descartadas': posiciones['descartadas'],
            'eventos': eventos,
        }

    def _sincronizar_posiciones(self, desde, hasta):
        """Pasada con ventana explícita sobre los dispositivos vinculados. No mueve el watermark.
        Devuelve las posiciones nuevas. Si algún dispositivo falla, lo registra y lanza UserError al final."""
        self.ensure_one()
        total, fallos = 0, []
        for dispositivo, vehiculo in self._dispositivos_sincronizables():
            try:
                with self.env.cr.savepoint():
                    total += self._posiciones_dispositivo(dispositivo, vehiculo, desde, hasta)['nuevas']
            except Exception as exc:  # aislamiento: un dispositivo no detiene a los demás
                fallos.append(f'{dispositivo.unique_id}: {exc}')
        if fallos:
            mensaje = '; '.join(fallos)
            self._registrar_error(mensaje)
            raise UserError(_('Fallo al sincronizar posiciones: %s') % mensaje)
        return total

    def _sincronizar_eventos(self, desde, hasta):
        """Pasada con ventana explícita sobre los dispositivos vinculados. No mueve el watermark.
        Devuelve los eventos nuevos. Si algún dispositivo falla, lo registra y lanza UserError al final."""
        self.ensure_one()
        total, fallos = 0, []
        for dispositivo, vehiculo in self._dispositivos_sincronizables():
            try:
                with self.env.cr.savepoint():
                    total += self._eventos_dispositivo(dispositivo, vehiculo, desde, hasta)
            except Exception as exc:  # aislamiento: un dispositivo no detiene a los demás
                fallos.append(f'{dispositivo.unique_id}: {exc}')
        if fallos:
            mensaje = '; '.join(fallos)
            self._registrar_error(mensaje)
            raise UserError(_('Fallo al sincronizar eventos: %s') % mensaje)
        return total

    def _sincronizar_todo(self):
        """Dispositivos, luego posiciones y eventos de cada dispositivo con su propia ventana.
        Lo usan el cron y el botón manual. Un dispositivo que falla no detiene a los demás."""
        self.ensure_one()
        resumen = {'dispositivos': 0, 'posiciones': 0, 'eventos': 0, 'errores': 0}
        fallos = []
        try:
            with self.env.cr.savepoint():
                resumen['dispositivos'] = self._sincronizar_dispositivos()
        except Exception as exc:
            fallos.append(f'dispositivos: {exc}')
        hasta = fields.Datetime.now()
        for dispositivo, vehiculo in self._dispositivos_sincronizables():
            try:
                with self.env.cr.savepoint():
                    stats = self._sincronizar_dispositivo(dispositivo, vehiculo, hasta)
            except Exception as exc:  # aislamiento: un dispositivo no detiene a los demás
                fallos.append(f'{dispositivo.unique_id}: {exc}')
                _logger.warning('traccar_sync_error servidor=%s dispositivo=%s error=%s',
                                self.id, dispositivo.traccar_id, exc)
                continue
            resumen['posiciones'] += stats['nuevas']
            resumen['eventos'] += stats['eventos']
            _logger.info(
                'traccar_sync servidor=%s dispositivo=%s desde=%s hasta=%s posiciones=%s '
                'descartadas=%s eventos=%s watermark=%s',
                self.id, dispositivo.traccar_id, stats['desde'], hasta, stats['nuevas'],
                stats['descartadas'], stats['eventos'], dispositivo.position_watermark)
        resumen['errores'] = len(fallos)
        if fallos:
            self._registrar_error('; '.join(fallos))
        else:
            self.sudo().write({
                'state': 'connected',
                'last_error_message': False,
                'last_sync_date': fields.Datetime.now(),
            })
        _logger.info('traccar_sync_resumen servidor=%s dispositivos=%s posiciones=%s eventos=%s errores=%s',
                     self.id, resumen['dispositivos'], resumen['posiciones'], resumen['eventos'],
                     resumen['errores'])
        return resumen

    # ------------------------------------------------------------------
    # Informes de Traccar (ruta, viajes y paradas): solo lectura
    # ------------------------------------------------------------------
    def _exigir_usuario_flota(self):
        if not (self.env.su or self.env.user.has_group('fleet.fleet_group_user')):
            raise AccessError(_('Solo el personal de flota consulta los informes de Traccar.'))

    def _informe(self, tipo, dispositivo, desde, hasta):
        """GET /api/reports/<tipo> con deviceId, from y to en ISO 8601 UTC. Lista vacía si no hay datos."""
        self.ensure_one()
        self._exigir_usuario_flota()
        traccar_id = dispositivo if isinstance(dispositivo, int) else dispositivo.traccar_id
        parametros = {'deviceId': traccar_id, 'from': _iso_utc(_a_utc(desde)), 'to': _iso_utc(_a_utc(hasta))}
        return self._request('/api/reports/' + tipo, parametros) or []

    def get_route_report(self, dispositivo, desde, hasta):
        """Posiciones del dispositivo en la ventana (informe de ruta)."""
        return self._informe('route', dispositivo, desde, hasta)

    def get_trips(self, dispositivo, desde, hasta):
        return self._informe('trips', dispositivo, desde, hasta)

    def get_stops(self, dispositivo, desde, hasta):
        return self._informe('stops', dispositivo, desde, hasta)

    def action_sincronizar_ahora(self):
        """Botón manual «Sincronizar ahora»: el mismo flujo que el cron, solo para gestores de flota."""
        self.ensure_one()
        self._exigir_gestor_flota()
        resumen = self._sincronizar_todo()
        return self._notificar(
            _('Sincronización'),
            _('Posiciones nuevas: %(posiciones)s, eventos nuevos: %(eventos)s, errores: %(errores)s') % resumen,
            'warning' if resumen['errores'] else 'success')

    @api.model
    def cron_sincronizar(self):
        """Entrada del ir.cron (público solo por ir.cron, F1-R22). Puede llamarla el sistema
        (superusuario, como el ir.cron) o un gestor de flota; cualquier otro usuario recibe AccessError."""
        if not self.env.su and not self.env.user.has_group('fleet.fleet_group_manager'):
            raise AccessError(_('Solo el sistema o un gestor de flota puede ejecutar la sincronización automática.'))
        for servidor in self.sudo().search([('active', '=', True)]):
            try:
                servidor._sincronizar_todo()
            except Exception as exc:  # aislamiento: un servidor no detiene a los demás
                _logger.warning('traccar_sync_error servidor=%s error=%s', servidor.id, exc)
