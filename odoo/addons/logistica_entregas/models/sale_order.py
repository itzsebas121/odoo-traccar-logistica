# -*- coding: utf-8 -*-
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    logistica_entrega_ids = fields.One2many(
        'logistica.entrega', 'sale_order_id', string='Entregas logísticas')
    logistica_entrega_id = fields.Many2one(
        'logistica.entrega', string='Entrega logística',
        compute='_compute_logistica_entrega_id')

    @api.depends('logistica_entrega_ids')
    def _compute_logistica_entrega_id(self):
        for order in self:
            order.logistica_entrega_id = order.logistica_entrega_ids[:1]

    def _logistica_es_web(self):
        """Pedido originado en el eCommerce. No depende del módulo website:
        el campo se lee solo si existe."""
        self.ensure_one()
        return 'website_id' in self._fields and bool(self['website_id'])

    def _logistica_destino_valido(self):
        self.ensure_one()
        lat, lon = self.delivery_latitude, self.delivery_longitude
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return False
        if math.isnan(lat) or math.isnan(lon):
            return False
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False
        return not (lat == 0 and lon == 0)

    def action_confirm(self):
        for order in self:
            if order._logistica_es_web() and not order._logistica_destino_valido():
                raise UserError(_(
                    'El pedido %s no tiene un destino de entrega válido. '
                    'Indique la ubicación en el mapa antes de confirmar.') % order.name)
        res = super().action_confirm()
        for order in self:
            if order.state == 'sale' and not order.sudo().logistica_entrega_ids:
                order._logistica_crear_entrega()
        return res

    def _logistica_crear_entrega(self):
        self.ensure_one()
        partner = self.partner_shipping_id or self.partner_id
        direccion = (partner._display_address(without_company=True) or '').replace('\n', ', ')
        entrega = self.env['logistica.entrega'].sudo().create({
            'sale_order_id': self.id,
            'partner_id': partner.id,
            'latitude': self.delivery_latitude,
            'longitude': self.delivery_longitude,
            'destination_address': direccion.strip(', '),
            'delivery_reference': self.delivery_notes,
            'recipient_name': partner.name,
            'phone': partner.phone or partner.mobile,
        })
        entrega._transicionar('pendiente_preparacion', 'en_preparacion')
        return entrega
