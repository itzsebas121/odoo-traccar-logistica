# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    delivery_latitude = fields.Float(
        string='Latitud Entrega',
        digits=(10, 7),
        copy=False,
        help='Latitud del punto de entrega seleccionado para este pedido.'
    )
    delivery_longitude = fields.Float(
        string='Longitud Entrega',
        digits=(10, 7),
        copy=False,
        help='Longitud del punto de entrega seleccionado para este pedido.'
    )
    delivery_zone = fields.Selection([
        ('centro', 'Centro'),
        ('ficoa', 'Ficoa'),
        ('huachi', 'Huachi'),
        ('izamba', 'Izamba'),
        ('atocha', 'Atocha'),
        ('ingahurco', 'Ingahurco'),
        ('otra', 'Otra / Periférica'),
    ], string='Zona Logística', default='centro', copy=False)

    delivery_notes = fields.Text(
        string='Instrucciones de Entrega',
        copy=False,
        help='Indicaciones específicas de este pedido para el transportista.'
    )

    @api.onchange('partner_shipping_id', 'partner_id')
    def _onchange_partner_delivery_coords(self):
        partner = self.partner_shipping_id or self.partner_id
        if partner:
            self.delivery_latitude = partner.delivery_latitude
            self.delivery_longitude = partner.delivery_longitude
            self.delivery_zone = partner.delivery_zone
            self.delivery_notes = partner.delivery_notes

    def action_open_delivery_map(self):
        self.ensure_one()
        if not self.delivery_latitude or not self.delivery_longitude:
            return False
        url = f"https://www.google.com/maps/search/?api=1&query={self.delivery_latitude},{self.delivery_longitude}"
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

