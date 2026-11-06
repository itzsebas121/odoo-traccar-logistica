# -*- coding: utf-8 -*-
from odoo import models, fields


class LogisticaTraccarEvento(models.Model):
    _name = 'logistica.traccar.evento'
    _description = 'Evento reportado por Traccar'

    device_id = fields.Many2one(
        'traccar.device',
        string='Dispositivo GPS',
        ondelete='cascade',
        index=True,
    )
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehículo')
    traccar_event_id = fields.Integer(string='ID Evento Traccar', required=True)
    event_type = fields.Char(string='Tipo de Evento')
    event_time = fields.Datetime(string='Fecha/Hora del Evento (UTC)', index=True)
    geofence_traccar_id = fields.Integer(string='ID Geocerca Traccar')
    position_traccar_id = fields.Integer(string='ID Posición Traccar')
    attributes = fields.Text(string='Atributos (JSON)')

    _sql_constraints = [
        ('traccar_event_uniq', 'unique(traccar_event_id)',
         'El ID de evento de Traccar debe ser único.'),
        # Odoo convierte None a 0 en los campos Integer, así que el CHECK rechaza ese 0.
        ('traccar_event_positivo', 'CHECK(traccar_event_id > 0)',
         'El ID de evento de Traccar debe ser un entero positivo.'),
    ]
