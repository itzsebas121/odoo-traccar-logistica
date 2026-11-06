# -*- coding: utf-8 -*-
from odoo import models, fields


class TraccarServerClave(models.Model):
    """Contraseña o token del servidor Traccar. Solo la leen gestores de flota (F1-R24)."""
    _name = 'traccar.server.clave'
    _description = 'Clave de Servidor Traccar GPS'

    server_id = fields.Many2one('traccar.server', string='Servidor Traccar', required=True, ondelete='cascade')
    password = fields.Char(string='Contraseña / Token Traccar', copy=False)

    _sql_constraints = [
        ('server_uniq', 'unique(server_id)', 'Solo puede haber una clave por servidor Traccar.'),
    ]
