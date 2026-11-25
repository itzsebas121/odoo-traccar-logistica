# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LogisticaEntrega(models.Model):
    _inherit = 'logistica.entrega'

    route_stop_ids = fields.One2many('logistica.ruta.parada', 'entrega_id', string='Paradas de ruta')
    # Guardado (antes solo calculado): se puede filtrar y agrupar por ruta. Se recalcula cada vez que cambia
    # route_id, que es el único punto donde el despacho asigna o libera la entrega (aprobar, cancelar, reprogramar).
    ruta_id = fields.Many2one('logistica.ruta', string='Ruta', compute='_compute_ruta_id', store=True,
                              index=True, ondelete='set null')
    # Vínculo entrega ↔ vehículo y conductor: los de la ruta asignada (el pedido lo toma de aquí).
    vehicle_id = fields.Many2one(related='ruta_id.vehicle_id', string='Vehículo', store=True, index=True)
    driver_id = fields.Many2one(related='ruta_id.driver_id', string='Conductor', store=True, index=True)

    @api.depends('route_id')
    def _compute_ruta_id(self):
        Ruta = self.env['logistica.ruta'].sudo()
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
