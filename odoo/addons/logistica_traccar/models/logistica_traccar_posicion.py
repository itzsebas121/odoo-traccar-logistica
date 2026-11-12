# -*- coding: utf-8 -*-
from odoo import models, fields


class LogisticaTraccarPosicion(models.Model):
    _name = 'logistica.traccar.posicion'
    _description = 'Posición GPS recibida de Traccar'

    device_id = fields.Many2one(
        'traccar.device',
        string='Dispositivo GPS',
        ondelete='cascade',
        index=True,
    )
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehículo')
    route_id = fields.Many2one('logistica.ruta', string='Ruta activa', index=True,
                               ondelete='set null', help='Ruta en recorrido al recibir el fix.')
    traccar_position_id = fields.Integer(string='ID Posición Traccar', required=True)
    fix_time = fields.Datetime(string='Fecha/Hora del Fix (UTC)', required=True, index=True)
    latitude = fields.Float(string='Latitud', digits=(10, 7))
    longitude = fields.Float(string='Longitud', digits=(10, 7))
    speed_kmh = fields.Float(string='Velocidad (km/h)')
    odometer_km = fields.Float(string='Odómetro (km)')
    valid = fields.Boolean(string='Fix válido')

    _sql_constraints = [
        ('traccar_position_uniq', 'unique(traccar_position_id)',
         'El ID de posición de Traccar debe ser único.'),
        # Odoo convierte None a 0 en los campos Integer, así que el CHECK rechaza ese 0.
        ('traccar_position_positivo', 'CHECK(traccar_position_id > 0)',
         'El ID de posición de Traccar debe ser un entero positivo.'),
    ]
