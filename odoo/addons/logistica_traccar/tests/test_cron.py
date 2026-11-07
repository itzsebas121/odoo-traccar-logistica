# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestCronTraccar(TransactionCase):
    """El cron y el botón existen y apuntan a los métodos que ya cierra el conector."""

    def test_cron_activo_llama_a_cron_sincronizar(self):
        cron = self.env.ref('logistica_traccar.ir_cron_traccar_sincronizar')
        self.assertTrue(cron.active)
        self.assertEqual(cron.state, 'code')
        self.assertIn('cron_sincronizar', cron.code)
        self.assertNotIn('sincronizar_todo', cron.code)
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, 'minutes')
        self.assertEqual(cron.user_id.id, SUPERUSER_ID)
        self.assertEqual(cron.model_id.model, 'traccar.server')

    def test_intervalo_coincide_con_el_parametro(self):
        """logistica.traccar_poll_minutes vive en logistica_base; el cron usa el mismo minuto."""
        cron = self.env.ref('logistica_traccar.ir_cron_traccar_sincronizar')
        valor = self.env['ir.config_parameter'].sudo().get_param('logistica.traccar_poll_minutes')
        self.assertEqual(
            valor, '1',
            'logistica.traccar_poll_minutes debe valer 1; lo define logistica_base')
        self.assertEqual(cron.interval_number, int(valor))

    def test_boton_sincronizar_ahora_en_la_vista(self):
        vista = self.env.ref('logistica_traccar.view_traccar_server_form')
        self.assertIn('action_sincronizar_ahora', vista.arch)
        self.assertNotIn('sincronizar_todo', vista.arch)
