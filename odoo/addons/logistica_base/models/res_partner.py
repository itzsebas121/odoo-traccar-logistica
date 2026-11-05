# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    delivery_latitude = fields.Float(
        string='Latitud Entrega',
        digits=(10, 7),
        help='Latitud geográfica del punto habitual de entrega.'
    )
    delivery_longitude = fields.Float(
        string='Longitud Entrega',
        digits=(10, 7),
        help='Longitud geográfica del punto habitual de entrega.'
    )
    delivery_zone = fields.Selection([
        ('centro', 'Centro'),
        ('ficoa', 'Ficoa'),
        ('huachi', 'Huachi'),
        ('izamba', 'Izamba'),
        ('atocha', 'Atocha'),
        ('ingahurco', 'Ingahurco'),
        ('otra', 'Otra / Periférica'),
    ], string='Zona Logística', default='centro', help='Zona urbana para agrupación de despachos.')

    delivery_notes = fields.Text(
        string='Referencias de Entrega',
        help='Color de fachada, piso, indicaciones para el repartidor.'
    )
    is_driver = fields.Boolean(
        string='Es Conductor / Repartidor',
        default=False,
        help='Marcar si este contacto puede ser asignado como conductor de flota.'
    )

    def action_open_in_google_maps(self):
        self.ensure_one()
        if not self.delivery_latitude or not self.delivery_longitude:
            return False
        url = f"https://www.google.com/maps/search/?api=1&query={self.delivery_latitude},{self.delivery_longitude}"
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

