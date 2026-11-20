# -*- coding: utf-8 -*-
from odoo import models

from ..controllers.tablero import puede_ver


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """session.logistica_tablero: el usuario puede ver los indicadores logisticos (la app Tableros los muestra
        sin esperar una consulta de grupos)."""
        info = super().session_info()
        info['logistica_tablero'] = bool(self.env.user and puede_ver(self.env.user))
        return info
