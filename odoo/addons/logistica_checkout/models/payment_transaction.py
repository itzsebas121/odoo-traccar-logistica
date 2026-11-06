# -*- coding: utf-8 -*-
import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _set_pending(self, state_message=None):
        """D5: el pago de prueba (payment_custom) deja la transacción en
        «pendiente»; en ese momento se confirma el pedido web sin aprobación
        manual, solo si su destino y datos son válidos. Si no lo son, el pedido
        no se confirma y el motivo queda en el chatter y en la página de
        confirmación del cliente."""
        txs = super()._set_pending(state_message=state_message)
        config = self.env['logistica.configuracion'].sudo().get_config()
        if not config.checkout_auto_confirm:
            return txs
        # R25: solo el proveedor de prueba (estado 'test'); una transferencia
        # bancaria habilitada de verdad nunca confirma un pedido sin cobro.
        for tx in txs.filtered(
                lambda t: t.provider_code == 'custom' and t.provider_id.state == 'test'):
            if len(tx.sale_order_ids) != 1:
                continue
            order = tx.sale_order_ids.sudo()
            if order.state not in ('draft', 'sent') or not order._logistica_es_web():
                continue
            if order.currency_id.compare_amounts(tx.amount, order.amount_total) != 0:
                _logger.warning('Pago de prueba %s: importe distinto del pedido %s; no se confirma.',
                                tx.reference, order.name)
                continue
            errores = order._logistica_checkout_errores()
            if not errores:
                try:
                    with self.env.cr.savepoint():
                        order.action_confirm()
                except UserError as exc:
                    errores = [exc.args[0]]
            if errores:
                order.message_post(body=_('Pedido no confirmado automáticamente: %s') % (
                    ' '.join(errores)))
        return txs
