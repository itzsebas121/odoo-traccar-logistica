# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TraccarDevice(models.Model):
    _name = 'traccar.device'
    _description = 'Dispositivo GPS Traccar'
    _order = 'name asc'

    name = fields.Char(string='Nombre del Dispositivo', required=True)
    unique_id = fields.Char(string='Identificador Único (IMEI / Client ID)', required=True, index=True)
    traccar_id = fields.Integer(string='ID Interno Traccar', required=True, index=True)
    server_id = fields.Many2one('traccar.server', string='Servidor Traccar', required=True, ondelete='cascade')

    status = fields.Selection([
        ('online', 'En Línea'),
        ('offline', 'Fuera de Línea'),
        ('unknown', 'Desconocido'),
    ], string='Estado', default='unknown')

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehículo Asociado', ondelete='set null')

    last_latitude = fields.Float(string='Última Latitud', digits=(10, 7), readonly=True)
    last_longitude = fields.Float(string='Última Longitud', digits=(10, 7), readonly=True)
    last_speed = fields.Float(string='Última Velocidad (km/h)', readonly=True)
    last_position_time = fields.Datetime(string='Fecha/Hora Última Posición', readonly=True)

    is_stale = fields.Boolean(
        string='GPS desactualizado', compute='_compute_is_stale',
        help='Verdadero si la última posición es más antigua que el umbral configurado en logística.')
    position_watermark = fields.Datetime(
        string='Marca de Última Posición Procesada',
        copy=False,
        help='Fecha/hora de la última posición de Traccar incorporada a Odoo para este dispositivo.',
    )
    is_active = fields.Boolean(
        string='Activo para Sincronización',
        default=True,
        help='Los dispositivos inactivos no se sincronizan con Traccar.',
    )

    _sql_constraints = [
        ('server_traccar_id_uniq', 'unique(server_id, traccar_id)', 'El ID interno de Traccar debe ser único por servidor.'),
        ('unique_id_uniq', 'unique(unique_id)', 'El identificador único (IMEI / Client ID) debe ser único.')
    ]

    def _registrar_posicion(self, fix_time, latitud, longitud, velocidad_kmh):
        """Guarda la última posición conocida solo si es más reciente que la registrada.
        Escritura con sudo: los usuarios internos no escriben en traccar.device (F1-R16).
        Con una posición nueva revisa si el vehículo llegó a alguna parada (solo registra
        «posible llegada»; nunca marca la entrega como entregada)."""
        self.ensure_one()
        if self.last_position_time and fix_time <= self.last_position_time:
            return
        self.sudo().write({
            'last_latitude': latitud,
            'last_longitude': longitud,
            'last_speed': velocidad_kmh,
            'last_position_time': fix_time,
        })
        self._verificar_llegadas(latitud, longitud, fix_time)

    def _verificar_llegadas(self, latitud, longitud, fix_time):
        """Llegada por proximidad. Un fallo aquí nunca debe romper la sincronización del GPS."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                vehiculo = self.env['fleet.vehicle'].sudo().search(
                    [('traccar_device_id', '=', self.id)], limit=1)
                if not vehiculo:
                    return
                Parada = self.env['logistica.ruta.parada'].sudo()
                Parada._paradas_en_recorrido(vehiculo)._check_proximidad(latitud, longitud, fix_time)
        except Exception as exc:  # aislamiento: la posición ya quedó guardada
            _logger.warning('traccar_llegada_error dispositivo=%s error=%s', self.traccar_id, exc)

    @api.model
    def _umbral_desactualizado_s(self):
        return self.env['logistica.configuracion'].sudo().get_config().gps_stale_after_seconds or 300

    @api.depends('last_position_time')
    def _compute_is_stale(self):
        umbral = self._umbral_desactualizado_s()
        ahora = fields.Datetime.now()
        for rec in self:
            rec.is_stale = bool(
                rec.last_position_time
                and (ahora - rec.last_position_time).total_seconds() > umbral)

    def _estado_gps(self):
        """Estado para el monitoreo. Nunca simula movimiento: si la señal es vieja devuelve la
        última ubicación conocida con su antigüedad."""
        self.ensure_one()
        base = {'dispositivo': self.name, 'tiene_posicion': False, 'desactualizado': False,
                'antiguedad_s': None, 'ultima_ubicacion_conocida': None}
        if not self.last_position_time:
            return base
        antiguedad = max(int((fields.Datetime.now() - self.last_position_time).total_seconds()), 0)
        base.update(
            tiene_posicion=True,
            desactualizado=antiguedad > self._umbral_desactualizado_s(),
            antiguedad_s=antiguedad,
            ultima_ubicacion_conocida={
                'latitud': self.last_latitude, 'longitud': self.last_longitude,
                'velocidad_kmh': self.last_speed,
                'hora_gps': fields.Datetime.to_string(self.last_position_time)})
        return base

    def action_fetch_latest_position(self):
        self.ensure_one()
        if not self.server_id:
            raise UserError(_('El dispositivo no está asociado a un servidor Traccar.'))

        url = f"{self.server_id.base_url.rstrip('/')}/api/positions?deviceId={self.traccar_id}"
        headers = self.server_id._get_auth_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                positions = response.json()
                if positions:
                    latest = positions[0]
                    # Conversión de nudos a km/h si Traccar reporta en knots (1 knot = 1.852 km/h)
                    speed_knots = latest.get('speed', 0.0)
                    speed_kmh = round(speed_knots * 1.852, 2)
                    # F1-R17: la lectura queda en el contexto del usuario; la escritura va con sudo.
                    self.sudo().write({
                        'last_latitude': latest.get('latitude', 0.0),
                        'last_longitude': latest.get('longitude', 0.0),
                        'last_speed': speed_kmh,
                        'last_position_time': fields.Datetime.now(),
                    })
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Posición Actualizada'),
                            'message': _('Lat: %s, Lon: %s, Velocidad: %s km/h') % (
                                latest.get('latitude'), latest.get('longitude'), speed_kmh
                            ),
                            'sticky': False,
                            'type': 'success',
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Sin Posiciones'),
                            'message': _('No se han registrado posiciones GPS para este dispositivo.'),
                            'sticky': False,
                            'type': 'warning',
                        }
                    }
            else:
                raise UserError(_('Error al consultar posición en Traccar: HTTP %s') % response.status_code)
        except requests.RequestException as e:
            raise UserError(_('Error de comunicación con Traccar: %s') % str(e))

