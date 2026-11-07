# -*- coding: utf-8 -*-
from odoo import fields, models


class LogisticaRutaMotivo(models.TransientModel):
    """Pide el motivo antes de cancelar o interrumpir una ruta desde la interfaz."""
    _name = 'logistica.ruta.motivo'
    _description = 'Motivo de cancelación o interrupción de ruta'

    ruta_id = fields.Many2one('logistica.ruta', string='Ruta', required=True, ondelete='cascade')
    accion = fields.Selection(
        [('cancelar', 'Cancelar'), ('interrumpir', 'Interrumpir')], string='Acción', required=True)
    motivo = fields.Text(string='Motivo', required=True)

    def action_confirmar(self):
        self.ensure_one()
        if self.accion == 'cancelar':
            self.ruta_id.action_cancelar(self.motivo)
        else:
            self.ruta_id.action_interrumpir(self.motivo)
        return {'type': 'ir.actions.act_window_close'}
