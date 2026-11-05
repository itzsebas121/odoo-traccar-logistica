# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    traccar_device_id = fields.Many2one(
        'traccar.device',
        string='Dispositivo GPS Traccar',
        help='Dispositivo GPS vinculado en Traccar Server para el seguimiento en tiempo real de este vehículo.'
    )
    traccar_unique_id = fields.Char(
        related='traccar_device_id.unique_id',
        string='ID Rastreo GPS (IMEI / Traccar Client ID)',
        readonly=True
    )
    traccar_status = fields.Selection(
        related='traccar_device_id.status',
        string='Estado de Conexión GPS',
        readonly=True
    )
    traccar_latitude = fields.Float(
        related='traccar_device_id.last_latitude',
        string='Última Latitud',
        readonly=True
    )
    traccar_longitude = fields.Float(
        related='traccar_device_id.last_longitude',
        string='Última Longitud',
        readonly=True
    )
    traccar_speed = fields.Float(
        related='traccar_device_id.last_speed',
        string='Velocidad Actual (km/h)',
        readonly=True
    )
    traccar_position_time = fields.Datetime(
        related='traccar_device_id.last_position_time',
        string='Fecha/Hora Última Posición',
        readonly=True
    )

    def action_fetch_traccar_position(self):
        self.ensure_one()
        if not self.traccar_device_id:
            raise UserError(_('El vehículo no tiene un dispositivo Traccar vinculado.'))
        return self.traccar_device_id.action_fetch_latest_position()

