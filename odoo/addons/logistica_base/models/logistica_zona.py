# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

ZONA_CODES = [
    ('centro', 'Centro'),
    ('ficoa', 'Ficoa'),
    ('huachi', 'Huachi'),
    ('izamba', 'Izamba'),
    ('atocha', 'Atocha'),
    ('ingahurco', 'Ingahurco'),
    ('otra', 'Otra / Periférica'),
]


class LogisticaZona(models.Model):
    _name = 'logistica.zona'
    _description = 'Zona Logística'
    _order = 'id'

    code = fields.Selection(ZONA_CODES, string='Código', required=True)
    name = fields.Char(string='Nombre', required=True)
    latitude = fields.Float(string='Latitud (centroide aprox.)', digits=(10, 7), required=True)
    longitude = fields.Float(string='Longitud (centroide aprox.)', digits=(10, 7), required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Ya existe una zona con ese código.'),
    ]

    @api.constrains('latitude', 'longitude')
    def _check_coordenadas(self):
        for rec in self:
            if not (-90 <= rec.latitude <= 90 and -180 <= rec.longitude <= 180):
                raise ValidationError(_('Coordenadas de zona fuera de rango.'))

    @api.model
    def centroide(self, code):
        zona = self.search([('code', '=', code)], limit=1)
        return (zona.latitude, zona.longitude) if zona else (0.0, 0.0)
