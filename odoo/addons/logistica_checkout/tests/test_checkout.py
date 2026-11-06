# -*- coding: utf-8 -*-
import re
from datetime import timedelta

import odoo
import odoo.fields
from odoo import Command
from odoo.tests.common import HttpCase, tagged

LAT, LON = -1.2417, -78.6197
TOKEN_INVENTADO = 'x' * 43
CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


@tagged('post_install', '-at_install', 'logistica_checkout')
class TestCheckout(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref('website.default_website')
        cls.website.account_on_checkout = 'optional'
        cls.country = cls.env.ref('base.ec')
        cls.product = cls.env['product.product'].create({
            'name': 'Producto Web', 'type': 'consu', 'list_price': 10,
            'sale_ok': True, 'website_published': True})
        cls.provider = cls.env.ref('payment.payment_provider_transfer')
        cls.provider.write({'state': 'test'})
        cls.config = cls.env['logistica.configuracion'].get_config()
        cls.config.write({
            'coverage_lat_min': -1.35, 'coverage_lat_max': -1.15,
            'coverage_lon_min': -78.70, 'coverage_lon_max': -78.52,
            'checkout_auto_confirm': True,
        })
        cls.cliente = cls.env['res.partner'].create({
            'name': 'Cliente Seguimiento', 'phone': '0999999999',
            'street': 'Calle 1', 'city': 'Ambato', 'zip': '180101',
            'country_id': cls.country.id, 'email': 'seg@example.com'})
        cls.pedido_confirmado = cls._pedido_web(cls.cliente, LAT, LON)
        cls.pedido_confirmado.action_confirm()
        cls.entrega = cls.pedido_confirmado.logistica_entrega_id
        cls.token = cls.entrega.tracking_token

    @classmethod
    def _pedido_web(cls, partner, lat=0.0, lon=0.0):
        return cls.env['sale.order'].create({
            'partner_id': partner.id,
            'website_id': cls.website.id,
            'delivery_latitude': lat,
            'delivery_longitude': lon,
            'order_line': [Command.create({
                'product_id': cls.product.id, 'product_uom_qty': 1})],
        })

    def setUp(self):
        super().setUp()
        try:
            from odoo.addons.logistica_checkout.controllers.main import LIMITADOR
            LIMITADOR.reset()
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _sesion(self, **vals):
        self.authenticate(None, None)
        self.session.update(vals)
        odoo.http.root.session_store.save(self.session)

    def _carrito(self):
        order = self._pedido_web(self.website.user_id.partner_id)
        self._sesion(sale_order_id=order.id)
        return order

    def _post_direccion(self, **over):
        pagina = self.url_open('/shop/address')
        self.assertEqual(pagina.status_code, 200)
        # El formulario incluye el mapa y los campos ocultos del pin.
        self.assertIn('id="logistica_map_picker"', pagina.text)
        self.assertIn('name="delivery_latitude"', pagina.text)
        self.assertIn('name="delivery_longitude"', pagina.text)
        self.assertIn('map_picker.js', pagina.text)
        csrf = CSRF_RE.search(pagina.text).group(1)
        data = {
            'name': 'Cliente Web', 'email': 'cliente@example.com',
            'phone': '0991234567', 'street': 'Av. Cevallos 123',
            'city': 'Ambato', 'zip': '180101', 'country_id': str(self.country.id),
            'submitted': '1', 'partner_id': '0', 'use_same': '1',
            'field_required': 'phone,name',
            'delivery_latitude': str(LAT), 'delivery_longitude': str(LON),
            'delivery_notes': 'Casa azul, segundo piso',
            'csrf_token': csrf,
        }
        data.update(over)
        return self.url_open('/shop/address', data={k: v for k, v in data.items() if v is not None})

    def _pagar(self, order):
        """Completa el pago de prueba por la ruta real de payment_custom."""
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'reference': 'LOGTEST-%s' % order.id,
            'amount': order.amount_total,
            'currency_id': order.currency_id.id,
            'partner_id': order.partner_id.id,
            'operation': 'online_redirect',
            'sale_order_ids': [Command.set(order.ids)],
        })
        self.url_open('/payment/custom/process', data={'reference': tx.reference})
        self.env.invalidate_all()
        return tx

    def _seguimiento(self, token):
        return self.url_open('/logistica/seguimiento/%s' % token)

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------
    def test_checkout_guarda_pin_en_pedido(self):
        order = self._carrito()
        resp = self._post_direccion()
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/shop/payment', resp.url)
        self.env.invalidate_all()
        self.assertAlmostEqual(order.delivery_latitude, LAT, places=6)
        self.assertAlmostEqual(order.delivery_longitude, LON, places=6)
        self.assertEqual(order.delivery_zone, 'centro')
        self.assertEqual(order.delivery_notes, 'Casa azul, segundo piso')
        partner = order.partner_id
        self.assertNotEqual(partner, self.website.user_id.partner_id)
        self.assertEqual(partner.phone, '0991234567')
        # El destino vive en el pedido, no en el contacto (§3.1).
        self.assertEqual(partner.delivery_latitude, 0.0)
        self.assertEqual(partner.delivery_longitude, 0.0)

    def test_checkout_rechaza_coords_invalidas(self):
        casos = [
            ('', ''),
            ('abc', str(LON)),
            ('0', '0'),
            ('95', str(LON)),
            (str(LAT), '-200'),
            ('-0.1807', '-78.4678'),  # Quito: fuera del rectángulo de cobertura
        ]
        publico = self.website.user_id.partner_id
        for lat, lon in casos:
            with self.subTest(lat=lat, lon=lon):
                order = self._carrito()
                resp = self._post_direccion(delivery_latitude=lat, delivery_longitude=lon)
                self.assertEqual(resp.status_code, 200)
                self.assertIn('/shop/address', resp.url)
                self.assertIn('ubicación de entrega', resp.text)
                self.env.invalidate_all()
                self.assertEqual(order.partner_id, publico)
                self.assertEqual(order.delivery_latitude, 0.0)
                self._pagar(order)
                self.assertNotEqual(order.state, 'sale')
                self.assertFalse(order.logistica_entrega_ids)

    def test_checkout_sin_datos_no_confirma(self):
        order = self._carrito()
        resp = self._post_direccion(phone='')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/shop/address', resp.url)
        self.env.invalidate_all()
        self.assertEqual(order.partner_id, self.website.user_id.partner_id)
        self.assertEqual(order.state, 'draft')
        # Pedido con destino válido pero sin teléfono: el pago de prueba no lo
        # confirma en silencio y el cliente ve el motivo.
        sin_tel = self.env['res.partner'].create({
            'name': 'Sin Teléfono', 'street': 'Calle 2', 'city': 'Ambato',
            'zip': '180101', 'country_id': self.country.id, 'email': 'st@example.com'})
        order2 = self._pedido_web(sin_tel, LAT, LON)
        self._pagar(order2)
        self.assertNotEqual(order2.state, 'sale')
        self.assertFalse(order2.logistica_entrega_ids)
        self._sesion(sale_last_order_id=order2.id)
        conf = self.url_open('/shop/confirmation')
        self.assertEqual(conf.status_code, 200)
        self.assertIn('teléfono', conf.text)
        self.assertNotIn('/logistica/seguimiento/', conf.text)

    def test_pago_prueba_confirma_pedido(self):
        order = self._carrito()
        resp = self._post_direccion()
        self.assertIn('/shop/payment', resp.url)
        self._pagar(order)
        self.assertEqual(order.state, 'sale')
        self.assertEqual(len(order.logistica_entrega_ids), 1)
        self.assertEqual(order.logistica_entrega_ids.state, 'en_preparacion')
        self.assertAlmostEqual(order.logistica_entrega_ids.latitude, LAT, places=6)

    def _pedido_listo_para_pagar(self):
        order = self._carrito()
        resp = self._post_direccion()
        self.assertIn('/shop/payment', resp.url)
        self.env.invalidate_all()
        self.assertFalse(order._logistica_checkout_errores())
        return order

    def test_sin_auto_confirmacion_no_confirma(self):
        self.config.checkout_auto_confirm = False
        order = self._pedido_listo_para_pagar()
        self._pagar(order)
        # payment_custom deja la cotización en 'sent' (estándar de sale); no se confirma.
        self.assertIn(order.state, ('draft', 'sent'))
        self.assertFalse(order.logistica_entrega_ids)

    def test_proveedor_no_prueba_no_confirma(self):
        """R25: solo un proveedor en estado 'test' confirma automáticamente."""
        self.provider.state = 'enabled'
        self.assertTrue(self.config.checkout_auto_confirm)
        order = self._pedido_listo_para_pagar()
        self._pagar(order)
        self.assertIn(order.state, ('draft', 'sent'))
        self.assertFalse(order.logistica_entrega_ids)

    def test_seguimiento_token_revocado_o_vencido_404(self):
        Entrega = self.env['logistica.entrega']
        self.assertEqual(self._seguimiento(self.token).status_code, 200)
        nombre = self.pedido_confirmado.name
        self.entrega.sudo().write({'tracking_token_revoked': True})
        self.assertFalse(Entrega.get_by_tracking_token(self.token))
        resp = self._seguimiento(self.token)
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(nombre, resp.text)
        self.assertNotIn('En preparación', resp.text)
        self.entrega.sudo().write({
            'tracking_token_revoked': False,
            'tracking_token_expires': odoo.fields.Datetime.now() - timedelta(seconds=1)})
        self.assertFalse(Entrega.get_by_tracking_token(self.token))
        resp = self._seguimiento(self.token)
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(nombre, resp.text)
        self.assertNotIn('En preparación', resp.text)

    def test_confirmacion_muestra_enlace(self):
        self._sesion(sale_last_order_id=self.pedido_confirmado.id)
        resp = self.url_open('/shop/confirmation')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/logistica/seguimiento/%s' % self.token, resp.text)

    # ------------------------------------------------------------------
    # Seguimiento público
    # ------------------------------------------------------------------
    def test_seguimiento_token_invalido_404(self):
        resp = self._seguimiento(TOKEN_INVENTADO)
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(self.pedido_confirmado.name, resp.text)
        self.assertNotIn('En preparación', resp.text)

    def test_seguimiento_no_expone_coordenadas(self):
        resp = self._seguimiento(self.token)
        self.assertEqual(resp.status_code, 200)
        texto = resp.text
        self.assertIn(self.pedido_confirmado.name, texto)
        self.assertIn('En preparación', texto)
        bajo = texto.lower()
        self.assertNotIn('latitude', bajo)
        self.assertNotIn('longitude', bajo)
        self.assertIsNone(re.search(r'\blat\b', bajo))
        self.assertIsNone(re.search(r'\blon\b', bajo))
        self.assertNotIn('1.2417', texto)
        self.assertNotIn('78.6197', texto)
        self.assertNotIn(self.cliente.phone, texto)
        self.assertNotIn(self.cliente.street, texto)

    def test_seguimiento_estados_simplificados(self):
        esperado = {
            'pendiente_preparacion': 'En preparación',
            'en_preparacion': 'En preparación',
            'preparado': 'Preparado',
            'en_recorrido': 'En ruta',
            'entregado': 'Entregado',
            'no_entregado': 'No entregado',
            'pendiente_reprogramacion': 'No entregado',
            'devuelto_bodega': 'En retorno a bodega',
        }
        for estado, etiqueta in esperado.items():
            with self.subTest(estado=estado):
                self.entrega.sudo().write({'state': estado})
                resp = self._seguimiento(self.token)
                self.assertEqual(resp.status_code, 200)
                self.assertIn(etiqueta, resp.text)

    def test_rate_limit(self):
        for _i in range(30):
            self.assertNotEqual(self._seguimiento(TOKEN_INVENTADO).status_code, 429)
        self.assertEqual(self._seguimiento(TOKEN_INVENTADO).status_code, 429)
        # el límite es por IP: también bloquea un token válido
        self.assertEqual(self._seguimiento(self.token).status_code, 429)
