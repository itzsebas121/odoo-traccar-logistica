# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

LAT, LON = -1.2417, -78.6197


@tagged('post_install', '-at_install', 'logistica_entregas')
class TestEntregas(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Prueba', 'phone': '0999999999'})
        cls.product = cls.env['product.product'].create({
            'name': 'Producto Prueba', 'type': 'consu', 'list_price': 10})

    def _pedido(self, lat=LAT, lon=LON):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'delivery_latitude': lat,
            'delivery_longitude': lon,
            'order_line': [(0, 0, {
                'product_id': self.product.id, 'product_uom_qty': 1})],
        })

    def _entrega(self, hasta='en_recorrido'):
        """Crea una entrega confirmada y la lleva al estado indicado."""
        pedido = self._pedido()
        pedido.action_confirm()
        ent = pedido.logistica_entrega_id
        if hasta == 'en_preparacion':
            return ent
        ent.action_marcar_preparado()
        if hasta == 'preparado':
            return ent
        ent.action_marcar_asignado()
        if hasta == 'asignado':
            return ent
        ent.action_marcar_en_recorrido()
        return ent

    def test_entrega_al_confirmar_con_destino(self):
        pedido = self._pedido()
        pedido.action_confirm()
        entregas = self.env['logistica.entrega'].search(
            [('sale_order_id', '=', pedido.id)])
        self.assertEqual(len(entregas), 1)
        self.assertEqual(entregas.state, 'en_preparacion')
        self.assertEqual(entregas.latitude, LAT)
        self.assertTrue(entregas.event_ids.filtered(
            lambda e: e.event_type == 'creado'))

    def test_pedido_web_sin_destino_no_confirma(self):
        pedido = self._pedido(lat=0.0, lon=0.0)
        Order = self.env.registry['sale.order']
        with patch.object(Order, '_logistica_es_web', return_value=True):
            with self.assertRaises(UserError):
                pedido.action_confirm()
        self.assertEqual(pedido.state, 'draft')
        self.assertFalse(self.env['logistica.entrega'].search(
            [('sale_order_id', '=', pedido.id)]))

    def test_transicion_invalida(self):
        pedido = self._pedido()
        pedido.action_confirm()
        ent = pedido.logistica_entrega_id
        ent.sudo().write({'state': 'pendiente_preparacion'})
        with self.assertRaises(UserError):
            ent.action_marcar_entregado()
        self.assertEqual(ent.state, 'pendiente_preparacion')

    def test_state_no_se_escribe_directo(self):
        ent = self._entrega('en_recorrido')
        manager = self.env['res.users'].create({
            'name': 'Gestor', 'login': 'gestor_state',
            'groups_id': [(6, 0, [self.env.ref('fleet.fleet_group_manager').id])]})
        como_gestor = self.env['logistica.entrega'].with_user(manager).browse(ent.id)
        with self.assertRaises(UserError):
            como_gestor.write({'state': 'entregado'})
        with self.assertRaises(UserError):
            como_gestor.with_context(logistica_transicion=True).write(
                {'state': 'entregado'})
        self.assertEqual(ent.state, 'en_recorrido')
        # la ruta autorizada sigue funcionando
        como_gestor.action_marcar_entregado()
        self.assertEqual(ent.state, 'entregado')

    def _gestor(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [self.env.ref('fleet.fleet_group_manager').id])]})

    def test_create_no_fija_estado(self):
        pedido = self._pedido()
        # El gestor de flota no crea entregas: solo el hook de sale.order (sudo).
        manager = self._gestor('gestor_create')
        with self.assertRaises(AccessError):
            self.env['logistica.entrega'].with_user(manager).create(
                {'sale_order_id': pedido.id})
        # La guarda de estado de create() se prueba con un usuario no-su que
        # tiene derecho de creación mediante un grupo exclusivo de la prueba.
        grupo = self.env['res.groups'].create({'name': 'Prueba: crear entregas'})
        self.env['ir.model.access'].create({
            'name': 'prueba.crear.entrega',
            'model_id': self.env.ref('logistica_entregas.model_logistica_entrega').id,
            'group_id': grupo.id,
            'perm_read': True, 'perm_write': False,
            'perm_create': True, 'perm_unlink': False})
        creador = self.env['res.users'].create({
            'name': 'Creador', 'login': 'creador_prueba',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, grupo.id])]})
        Entrega = self.env['logistica.entrega'].with_user(creador)
        self.assertFalse(Entrega.env.su)
        with self.assertRaises(UserError):
            Entrega.create({'sale_order_id': pedido.id, 'state': 'entregado'})
        ent = Entrega.create({'sale_order_id': pedido.id})
        self.assertEqual(ent.state, 'pendiente_preparacion')
        pedido2 = self._pedido()
        ent2 = Entrega.create({'sale_order_id': pedido2.id,
                               'state': 'pendiente_preparacion'})
        self.assertEqual(ent2.state, 'pendiente_preparacion')

    def test_destino_corregido_auditado(self):
        ent = self._entrega('en_preparacion')
        manager = self._gestor('gestor_destino')
        como_gestor = ent.with_user(manager)
        como_gestor.write({'latitude': LAT + 0.001})
        eventos = ent.event_ids.filtered(
            lambda e: e.event_type == 'destino_corregido')
        self.assertEqual(len(eventos), 1)
        self.assertIn('latitude', eventos.notes)
        self.assertIn('-1.2417', eventos.notes)
        self.assertIn('-1.2407', eventos.notes)
        self.assertEqual(eventos.user_id, manager)
        # sin cambio real de valor no hay evento nuevo
        como_gestor.write({'latitude': LAT + 0.001})
        self.assertEqual(len(ent.event_ids.filtered(
            lambda e: e.event_type == 'destino_corregido')), 1)
        # campos ajenos al destino no generan evento
        como_gestor.write({'phone': '0988888888'})
        self.assertEqual(len(ent.event_ids.filtered(
            lambda e: e.event_type == 'destino_corregido')), 1)

    def test_campos_protegidos_no_se_escriben(self):
        ent = self._entrega('preparado')
        token = ent.tracking_token
        manager = self._gestor('gestor_protegido')
        como_gestor = ent.with_user(manager)
        otro = self._pedido()
        for vals in ({'tracking_token': 'x' * 43},
                     {'tracking_token_expires': fields.Datetime.now()},
                     {'tracking_token_revoked': True},
                     {'sale_order_id': otro.id},
                     {'route_id': 99}):
            with self.assertRaises(UserError):
                como_gestor.write(vals)
        self.assertEqual(ent.tracking_token, token)
        self.assertFalse(ent.tracking_token_revoked)
        self.assertEqual(ent.route_id, 0)
        # la acción autorizada sí fija la ruta (escritura interna con sudo)
        como_gestor.action_marcar_asignado(route_id=7)
        self.assertEqual(ent.route_id, 7)
        self.assertEqual(ent.state, 'asignado')

    def test_token_solo_para_gestores(self):
        ent = self._entrega('en_preparacion')
        user = self.env['res.users'].create({
            'name': 'Interno', 'login': 'interno_tok',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        ent.flush_recordset()
        ent.invalidate_recordset()
        with self.assertRaises(AccessError):
            ent.with_user(user).read(['tracking_token'])
        with self.assertRaises(AccessError):
            ent.with_user(user).read(['tracking_token_expires'])

    def test_revocar_token_solo_gestor(self):
        ent = self._entrega('en_preparacion')
        token = ent.tracking_token
        Entrega = self.env['logistica.entrega']
        self.assertEqual(Entrega.get_by_tracking_token(token), ent)
        interno = self.env['res.users'].create({
            'name': 'Interno Rev', 'login': 'interno_rev',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(UserError):
            ent.with_user(interno).action_revocar_token()
        self.assertFalse(ent.tracking_token_revoked)
        self.assertEqual(Entrega.get_by_tracking_token(token), ent)
        manager = self._gestor('gestor_revoca')
        ent.with_user(manager).action_revocar_token()
        self.assertTrue(ent.tracking_token_revoked)
        self.assertFalse(Entrega.get_by_tracking_token(token))

    def test_pedido_web_real_sin_destino_no_confirma(self):
        if 'website_id' not in self.env['sale.order']._fields:
            self.skipTest('website no instalado')
        website = self.env['website'].search([], limit=1)
        pedido = self._pedido(lat=0.0, lon=0.0)
        pedido.website_id = website
        with self.assertRaises(UserError):
            pedido.action_confirm()

    def test_evento_no_se_borra_con_entrega(self):
        ent = self._entrega('en_preparacion')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                ent.unlink()

    def test_evento_append_only(self):
        ent = self._entrega('en_preparacion')
        ev = ent.event_ids[:1]
        with self.assertRaises(UserError):
            ev.write({'notes': 'x'})
        with self.assertRaises(UserError):
            ev.unlink()

    def test_doble_entregado_un_evento(self):
        ent = self._entrega('en_recorrido')
        ent.action_marcar_entregado()
        with self.assertRaises(UserError) as cm:
            ent.action_marcar_entregado()
        self.assertIn('ya registrado', str(cm.exception.args[0]))
        eventos = ent.event_ids.filtered(lambda e: e.event_type == 'entregado')
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos.user_id, self.env.user)
        self.assertTrue(eventos.event_time)

    def test_no_entregado_requiere_motivo(self):
        ent = self._entrega('en_recorrido')
        with self.assertRaises(ValidationError):
            ent.action_marcar_no_entregado(False)
        with self.assertRaises(ValidationError):
            ent.action_marcar_no_entregado('inventado')
        self.assertEqual(ent.state, 'en_recorrido')
        ent.action_marcar_no_entregado('absent', 'Nadie abrió')
        self.assertEqual(ent.state, 'no_entregado')
        ev = ent.event_ids.filtered(lambda e: e.event_type == 'no_entregado')
        self.assertEqual(ev.failure_reason, 'absent')

    def test_llegada_gps_no_entrega(self):
        ent = self._entrega('en_recorrido')
        gps = {'latitude': LAT + 0.0002, 'longitude': LON,
               'time': fields.Datetime.now(), 'age_seconds': 5}
        ent.action_marcar_llegada(gps=gps)
        self.assertEqual(ent.state, 'en_recorrido')
        tipos = ent.event_ids.mapped('event_type')
        self.assertIn('posible_llegada', tipos)
        self.assertNotIn('entregado', tipos)
        ev = ent.event_ids.filtered(lambda e: e.event_type == 'posible_llegada')
        self.assertTrue(ev.gps_available)
        self.assertEqual(ev.gps_latitude, LAT + 0.0002)

    def test_token_seguro_y_expira(self):
        ent = self._entrega('en_preparacion')
        self.assertGreaterEqual(len(ent.tracking_token), 43)
        Entrega = self.env['logistica.entrega']
        self.assertEqual(Entrega.get_by_tracking_token(ent.tracking_token), ent)
        self.assertFalse(Entrega.get_by_tracking_token('inexistente'))
        self.assertFalse(Entrega.get_by_tracking_token(False))
        ent.tracking_token_expires = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(Entrega.get_by_tracking_token(ent.tracking_token))
        ent.tracking_token_expires = fields.Datetime.now() + timedelta(days=1)
        ent.tracking_token_revoked = True
        self.assertFalse(Entrega.get_by_tracking_token(ent.tracking_token))

    def test_reprogramar_o_devolver(self):
        ent = self._entrega('en_recorrido')
        ent.action_marcar_no_entregado('refused')
        ent.action_reprogramar()
        self.assertEqual(ent.state, 'preparado')
        ent2 = self._entrega('en_recorrido')
        ent2.action_marcar_no_entregado('access')
        ent2.action_devolver_bodega()
        self.assertEqual(ent2.state, 'devuelto_bodega')
