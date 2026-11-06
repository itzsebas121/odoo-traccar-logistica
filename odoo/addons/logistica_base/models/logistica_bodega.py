# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class LogisticaBodega(models.Model):
    _name = 'logistica.bodega'
    _description = 'Bodega de Despacho'
    _order = 'id'

    name = fields.Char(string='Nombre', required=True)
    address = fields.Char(string='Dirección')
    latitude = fields.Float(string='Latitud', digits=(10, 7), required=True)
    longitude = fields.Float(string='Longitud', digits=(10, 7), required=True)
    active = fields.Boolean(string='Activa', default=True)

    @api.constrains('active')
    def _check_bodega_unica(self):
        activas = self.with_context(active_test=False).search_count([('active', '=', True)])
        if activas > 1:
            raise ValidationError(_('Solo puede existir una bodega activa.'))

    @api.constrains('latitude', 'longitude')
    def _check_coordenadas(self):
        for rec in self:
            if not (-90 <= rec.latitude <= 90 and -180 <= rec.longitude <= 180):
                raise ValidationError(_('Coordenadas de bodega fuera de rango.'))

    @api.model
    def get_bodega_activa(self):
        return self.search([('active', '=', True)], limit=1)
