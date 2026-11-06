# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class LogisticaRutaParada(models.Model):
    _name = 'logistica.ruta.parada'
    _description = 'Parada de Entrega en Ruta'
    _order = 'sequence asc, id asc'

    route_id = fields.Many2one(
        'logistica.ruta',
        string='Ruta de Despacho',
        required=True,
        ondelete='cascade'
    )
    sequence = fields.Integer(string='Orden', default=10)
    order_id = fields.Many2one(
        'sale.order',
        string='Pedido de Venta',
        required=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente Destinatario',
        related='order_id.partner_id',
        readonly=True
    )
    zone = fields.Selection(
        related='order_id.delivery_zone',
        string='Zona',
        readonly=True
    )
    latitude = fields.Float(
        related='order_id.delivery_latitude',
        string='Latitud',
        digits=(10, 7),
        readonly=True
    )
    longitude = fields.Float(
        related='order_id.delivery_longitude',
        string='Longitud',
        digits=(10, 7),
        readonly=True
    )
    delivery_notes = fields.Text(
        related='order_id.delivery_notes',
        string='Instrucciones',
        readonly=True
    )
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('delivered', 'Entregado'),
        ('failed', 'No Entregado'),
    ], string='Resultado', default='pending', readonly=True)

    failed_reason = fields.Selection([
        ('absent', 'Cliente Ausente'),
        ('wrong_address', 'Dirección Incorrecta / No Localizada'),
        ('refused', 'Pedido Rechazado por Cliente'),
        ('damaged', 'Producto Averiado'),
        ('other', 'Otro Motivo'),
    ], string='Motivo de No Entrega')

    delivery_datetime = fields.Datetime(string='Fecha/Hora Entrega', readonly=True)

    def action_mark_delivered(self):
        for stop in self:
            stop.write({
                'state': 'delivered',
                'delivery_datetime': fields.Datetime.now(),
                'failed_reason': False,
            })

    def action_mark_failed(self):
        for stop in self:
            if not stop.failed_reason:
                raise UserError(_('Debe seleccionar un motivo de no entrega antes de marcar la parada como fallida.'))
            stop.write({
                'state': 'failed',
                'delivery_datetime': fields.Datetime.now(),
            })

    def action_open_navigation(self):
        self.ensure_one()
        if not self.latitude or not self.longitude:
            raise UserError(_('Esta parada no tiene coordenadas GPS válidas.'))
        url = f"https://www.google.com/maps/dir/?api=1&destination={self.latitude},{self.longitude}"
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

