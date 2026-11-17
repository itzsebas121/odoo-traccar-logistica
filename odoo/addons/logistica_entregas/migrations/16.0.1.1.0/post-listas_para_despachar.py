# -*- coding: utf-8 -*-
"""Fase A: sin preparación en bodega (opción por defecto), lo que esperaba en «En preparación» queda listo."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    if env['logistica.configuracion'].get_config().require_preparation:
        return
    env['logistica.entrega'].search([('state', '=', 'en_preparacion')]).action_marcar_preparado()
