# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        """Venta directa: al confirmar una factura de cliente, registra y concilia su pago automático."""
        res = super().action_post()
        if self.env.context.get('skip_auto_pago_directo'):
            return res
        facturas = self.filtered(
            lambda m: m.move_type == 'out_invoice'
            and m.state == 'posted'
            and m.payment_state == 'not_paid'
            and m.amount_residual > 0
        )
        for factura in facturas:
            diario = self.env['account.journal'].sudo().search([
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', factura.company_id.id),
            ], order='type asc, id asc', limit=1)
            if not diario:
                continue
            fecha = factura.invoice_date or fields.Date.context_today(factura)
            self.env['account.payment.register'].sudo().with_context(
                active_model='account.move',
                active_ids=factura.ids,
                skip_auto_pago_directo=True,
            ).create({
                'payment_date': fecha,
                'journal_id': diario.id,
            })._create_payments()
        return res
