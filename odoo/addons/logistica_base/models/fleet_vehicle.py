# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    logistica_capacidad = fields.Integer(
        string='Capacidad (bultos)', default=10,
        help='1 entrega = 1 bulto.')

    @api.constrains('logistica_capacidad')
    def _check_capacidad(self):
        for rec in self:
            if rec.logistica_capacidad < 0:
                raise ValidationError(_('La capacidad del vehículo no puede ser negativa.'))
