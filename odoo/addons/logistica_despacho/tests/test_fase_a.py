# -*- coding: utf-8 -*-
"""Fase A: el administrador solo despacha. Pedidos listos al confirmar, ubicación exigida siempre,
nada excluido en silencio, salida en un paso, cierre automático y reprogramación automática."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LAT, LON = -1.2417, -78.6197          # centro de Ambato
LEJOS = (-0.1807, -78.4678)            # Quito


@tagged('post_install', '-at_install', 'logistica_despacho')
class TestFaseA(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['logistica.configuracion'].get_config()
        cls.config.write({'require_preparation': False, 'coverage_radius_km': 0.0, 'max_delivery_attempts': 2})
        cls.cliente = cls.env['res.partner'].create({'name': 'Cliente Fase A', 'phone': '0999999999'})
        cls.producto = cls.env['product.product'].create({'name': 'Fruta Fase A', 'type': 'consu', 'list_price': 3})
        cls.servicio = cls.env['product.product'].create({'name': 'Asesoría', 'type': 'service', 'list_price': 9})
        marca = cls.env['fleet.vehicle.model.brand'].create({'name': 'MarcaFaseA'})
        cls.modelo = cls.env['fleet.vehicle.model'].create({'name': 'ModeloFaseA', 'brand_id': marca.id})
        cls.bodega = cls.env['logistica.bodega'].get_bodega_activa()
        cls._n = 0

    def _pedido(self, lat=LAT, lon=LON, producto=None):
        valores = {'partner_id': self.cliente.id,
                   'order_line': [(0, 0, {'product_id': (producto or self.producto).id, 'product_uom_qty': 1})]}
        if lat is not None:
            valores.update(delivery_latitude=lat, delivery_longitude=lon)
        return self.env['sale.order'].create(valores)

    def _entrega(self):
        pedido = self._pedido()
        pedido.action_confirm()
        return pedido.logistica_entrega_id

    def _vehiculo(self):
        type(self)._n += 1
        conductor = self.env['res.partner'].create({'name': 'Conductor FA%s' % self._n, 'is_driver': True})
        return self.env['fleet.vehicle'].create({
            'model_id': self.modelo.id, 'license_plate': 'FA-%04d' % self._n, 'driver_id': conductor.id})

    def _ruta(self, entregas):
        vehiculo = self._vehiculo()
        return self.env['logistica.ruta'].create({
            'vehicle_id': vehiculo.id, 'driver_id': vehiculo.driver_id.id, 'bodega_id': self.bodega.id,
            'stop_ids': [(0, 0, {'entrega_id': e.id, 'sequence': i + 1}) for i, e in enumerate(entregas)]})

    # ------------------------------------------------------------ pedidos
    def test_confirmar_deja_la_entrega_por_despachar(self):
        entrega = self._entrega()
        self.assertEqual(entrega.state, 'preparado')
        self.assertEqual(entrega.estado_simple, 'por_despachar')
        self.assertEqual(entrega.event_ids.mapped('event_type'), ['creado', 'preparado'])

    def test_con_preparacion_en_bodega_espera_y_se_prepara_en_lote(self):
        self.config.require_preparation = True
        e1, e2 = self._entrega(), self._entrega()
        self.assertEqual((e1.state, e2.state), ('en_preparacion', 'en_preparacion'))
        self.assertEqual(e1.estado_simple, 'por_despachar')  # visible en «Pedidos por despachar»
        (e1 | e2).action_marcar_preparado_lote()
        self.assertEqual((e1.state, e2.state), ('preparado', 'preparado'))

    def test_pedido_sin_ubicacion_no_se_confirma_aunque_no_sea_web(self):
        pedido = self._pedido(lat=None)
        with self.assertRaisesRegex(UserError, 'ubicación de entrega'):
            pedido.action_confirm()
        self.assertEqual(pedido.state, 'draft')

    def test_pedido_solo_de_servicios_no_pide_ubicacion_ni_crea_entrega(self):
        pedido = self._pedido(lat=None, producto=self.servicio)
        pedido.action_confirm()
        self.assertEqual(pedido.state, 'sale')
        self.assertFalse(pedido.logistica_entrega_ids)

    def test_radio_de_cobertura(self):
        self.config.coverage_radius_km = 25
        dentro = self._pedido()
        dentro.action_confirm()
        self.assertEqual(dentro.state, 'sale')
        fuera = self._pedido(*LEJOS)
        with self.assertRaisesRegex(UserError, 'cobertura'):
            fuera.action_confirm()

    # ------------------------------------------------------------ planificador
    def test_planificador_explica_lo_que_no_sale(self):
        lista = self._entrega()
        sin_punto = self._entrega()
        sin_punto.write({'latitude': 0.0, 'longitude': 0.0})
        tarde = self._entrega()
        hoy = self.config.hoy_local()
        tarde.sale_order_id.date_order = self.config.inicio_corte_utc(hoy) + timedelta(minutes=30)
        wiz = self.env['logistica.planificador'].create({'date': hoy})
        listas, excluidas = wiz._evaluar()
        motivos = {e: m for e, m in excluidas}
        self.assertIn(lista, listas)
        self.assertIn('ubicación', motivos[sin_punto])
        self.assertIn('hora de corte', motivos[tarde])
        self.assertIn('No saldrán en este despacho', wiz.resumen)
        # Mañana la del corte ya sale.
        manana = self.env['logistica.planificador'].create({'date': hoy + timedelta(days=1)})
        self.assertIn(tarde, manana._evaluar()[0])

    # ------------------------------------------------------------ rutas
    def test_aprobar_seleccion_y_salir_en_un_paso(self):
        r1, r2 = self._ruta([self._entrega()]), self._ruta([self._entrega()])
        r2.action_aprobar_plan()
        (r1 | r2).action_aprobar_seleccion()  # r2 ya estaba aprobada: se omite sin error
        self.assertEqual((r1.state, r2.state), ('planificada', 'planificada'))
        r1.action_salir_a_ruta()
        self.assertEqual(r1.state, 'en_recorrido')
        self.assertTrue(r1.confirmed_load_at and r1.started_at)

    def test_ultima_parada_cierra_y_reprograma_hasta_agotar_intentos(self):
        entrega = self._entrega()
        ruta = self._ruta([entrega])
        ruta.action_aprobar_plan()
        ruta.action_salir_a_ruta()
        ruta.stop_ids.action_marcar_no_entregado('absent')
        self.assertEqual(ruta.state, 'cerrada')
        self.assertEqual(entrega.estado_simple, 'por_despachar')  # intento 1 de 2: vuelve sola
        # Segundo intento fallido: requiere atención del administrador.
        ruta2 = self._ruta([entrega])
        ruta2.action_aprobar_plan()
        ruta2.action_salir_a_ruta()
        ruta2.stop_ids.action_marcar_no_entregado('absent')
        self.assertEqual(entrega.intentos, 2)
        self.assertEqual(entrega.state, 'pendiente_reprogramacion')
        self.assertEqual(entrega.estado_simple, 'atencion')

    def test_direccion_incorrecta_pide_atencion_al_primer_fallo(self):
        entrega = self._entrega()
        ruta = self._ruta([entrega])
        ruta.action_aprobar_plan()
        ruta.action_salir_a_ruta()
        ruta.stop_ids.action_marcar_no_entregado('wrong_address')
        self.assertEqual(entrega.estado_simple, 'atencion')

    def test_entregado_cierra_la_ruta(self):
        e1, e2 = self._entrega(), self._entrega()
        ruta = self._ruta([e1, e2])
        ruta.action_aprobar_plan()
        ruta.action_salir_a_ruta()
        p1, p2 = ruta.stop_ids.sorted('sequence')
        p1.action_marcar_entregado()
        self.assertEqual(ruta.state, 'en_recorrido')
        p2.action_marcar_entregado()
        self.assertEqual(ruta.state, 'cerrada')
        self.assertLessEqual(ruta.finished_at, fields.Datetime.now())
