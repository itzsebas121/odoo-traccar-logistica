# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    """Vínculo pedido ↔ vehículo y conductor.

    El pedido no se asigna a un camión al venderse: se asigna al planificar la ruta (pedido → entrega → parada →
    ruta). Estos campos muestran esa asignación en el pedido, guardados para poder buscar y agrupar. Salen de la
    entrega del pedido (la misma que ``logistica_entrega_id``)."""
    _inherit = 'sale.order'

    logistica_ruta_id = fields.Many2one('logistica.ruta', string='Ruta de despacho',
                                        compute='_compute_logistica_asignacion', store=True, index=True)
    logistica_vehicle_id = fields.Many2one('fleet.vehicle', string='Vehículo de reparto',
                                           compute='_compute_logistica_asignacion', store=True, index=True)
    logistica_driver_id = fields.Many2one('res.partner', string='Conductor de reparto',
                                          compute='_compute_logistica_asignacion', store=True, index=True)

    @api.depends('logistica_entrega_ids.ruta_id', 'logistica_entrega_ids.vehicle_id',
                 'logistica_entrega_ids.driver_id')
    def _compute_logistica_asignacion(self):
        for order in self:
            entrega = order.sudo().logistica_entrega_ids[:1]
            order.logistica_ruta_id = entrega.ruta_id
            order.logistica_vehicle_id = entrega.vehicle_id
            order.logistica_driver_id = entrega.driver_id
