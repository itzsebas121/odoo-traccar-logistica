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

    _sql_constraints = [
        ('server_traccar_id_uniq', 'unique(server_id, traccar_id)', 'El ID interno de Traccar debe ser único por servidor.'),
        ('unique_id_uniq', 'unique(unique_id)', 'El identificador único (IMEI / Client ID) debe ser único.')
    ]

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
                    self.write({
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

