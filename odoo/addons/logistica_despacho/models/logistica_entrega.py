# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LogisticaEntrega(models.Model):
    _inherit = 'logistica.entrega'

    route_stop_ids = fields.One2many('logistica.ruta.parada', 'entrega_id', string='Paradas de ruta')
    ruta_id = fields.Many2one('logistica.ruta', string='Ruta', compute='_compute_ruta_id')

    @api.depends('route_id')
    def _compute_ruta_id(self):
        Ruta = self.env['logistica.ruta']
        for rec in self:
            rec.ruta_id = Ruta.browse(rec.route_id).exists() if rec.route_id else Ruta


class LogisticaEntregaEvento(models.Model):
    _inherit = 'logistica.entrega.evento'

    event_type = fields.Selection(
        selection_add=[
            ('no_asignado', 'No asignado en la planificación'),
            ('desasignado', 'Desasignado de ruta'),
            ('ruta_interrumpida', 'Ruta interrumpida'),
        ],
        ondelete={
            'no_asignado': 'cascade',
            'desasignado': 'cascade',
            'ruta_interrumpida': 'cascade',
        })
