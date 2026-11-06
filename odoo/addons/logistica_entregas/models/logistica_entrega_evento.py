# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

EVENT_TYPES = [
    ('creado', 'Creado'),
    ('preparado', 'Preparado'),
    ('asignado', 'Asignado a ruta'),
    ('carga_confirmada', 'Carga confirmada'),
    ('inicio_recorrido', 'Inicio de recorrido'),
    ('posible_llegada', 'Posible llegada (GPS)'),
    ('llegada_registrada', 'Llegada registrada'),
    ('entregado', 'Entregado'),
    ('no_entregado', 'No entregado'),
    ('reprogramado', 'Reprogramado'),
    ('devuelto_bodega', 'Devuelto a bodega'),
    ('gps_no_disponible', 'GPS no disponible'),
    ('destino_corregido', 'Destino corregido'),
]

MOTIVOS_NO_ENTREGA = [
    ('absent', 'Cliente ausente'),
    ('wrong_address', 'Dirección incorrecta'),
    ('refused', 'Cliente rechaza'),
    ('access', 'Acceso impedido'),
    ('damaged', 'Problema con el producto'),
    ('other', 'Otro'),
]


class LogisticaEntregaEvento(models.Model):
    _name = 'logistica.entrega.evento'
    _description = 'Evento de Entrega Logística (solo inserción)'
    _order = 'event_time desc, id desc'

    entrega_id = fields.Many2one(
        'logistica.entrega', string='Entrega', required=True,
        ondelete='restrict', index=True)
    event_type = fields.Selection(EVENT_TYPES, string='Evento', required=True, index=True)
    event_time = fields.Datetime(
        string='Fecha y hora', required=True, default=fields.Datetime.now)
    user_id = fields.Many2one(
        'res.users', string='Usuario', default=lambda self: self.env.user)
    # Se reemplaza por Many2one a logistica.ruta en la Tarea 8 (misma columna entera).
    route_id = fields.Integer(string='ID de ruta')
    gps_latitude = fields.Float(string='Latitud GPS', digits=(10, 7))
    gps_longitude = fields.Float(string='Longitud GPS', digits=(10, 7))
    gps_time = fields.Datetime(string='Hora de la posición GPS')
    gps_age_seconds = fields.Integer(string='Antigüedad GPS (s)')
    gps_available = fields.Boolean(string='GPS disponible', default=False)
    failure_reason = fields.Selection(MOTIVOS_NO_ENTREGA, string='Motivo de no entrega')
    notes = fields.Text(string='Notas')

    def write(self, vals):
        raise UserError(_('Los eventos de entrega son un registro de auditoría y no se pueden modificar.'))

    def unlink(self):
        # Se permite únicamente durante la desinstalación del módulo.
        if not self.env.context.get('module_uninstall'):
            raise UserError(_('Los eventos de entrega son un registro de auditoría y no se pueden eliminar.'))
        return super().unlink()
