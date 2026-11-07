# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

OPTIMIZE = 'odoo.addons.logistica_despacho.services.routing_client.optimize'
LAT, LON = -1.2417, -78.6197


@tagged('post_install', '-at_install', 'logistica_despacho')
class TestDespacho(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cliente = cls.env['res.partner'].create({'name': 'Cliente Despacho', 'phone': '0999999999'})
        cls.producto = cls.env['product.product'].create({
            'name': 'Producto Despacho', 'type': 'consu', 'list_price': 10})
        cls.marca = cls.env['fleet.vehicle.model.brand'].create({'name': 'MarcaDespacho'})
        cls.modelo = cls.env['fleet.vehicle.model'].create({
            'name': 'ModeloDespacho', 'brand_id': cls.marca.id})
        cls.bodega = cls.env['logistica.bodega'].get_bodega_activa()
        cls._n = 0

    # ---------------------------------------------------------------- ayudas
    def _vehiculo(self, capacidad=10):
        type(self)._n += 1
        n = type(self)._n
        conductor = self.env['res.partner'].create({'name': 'Conductor D%s' % n, 'is_driver': True})
        return self.env['fleet.vehicle'].create({
            'model_id': self.modelo.id, 'license_plate': 'DSP-%04d' % n,
            'driver_id': conductor.id, 'logistica_capacidad': capacidad})

    def _entrega(self, estado='preparado'):
        pedido = self.env['sale.order'].create({
            'partner_id': self.cliente.id,
            'delivery_latitude': LAT, 'delivery_longitude': LON,
            'order_line': [(0, 0, {'product_id': self.producto.id, 'product_uom_qty': 1})],
        })
        pedido.action_confirm()
        entrega = pedido.logistica_entrega_id
        if estado == 'preparado':
            entrega.action_marcar_preparado()
        return entrega

    def _ruta(self, entregas, vehiculo=None):
        vehiculo = vehiculo or self._vehiculo()
        return self.env['logistica.ruta'].create({
            'vehicle_id': vehiculo.id, 'driver_id': vehiculo.driver_id.id,
            'bodega_id': self.bodega.id,
            'stop_ids': [(0, 0, {'entrega_id': e.id, 'sequence': i + 1})
                         for i, e in enumerate(entregas)],
        })

    def _ruta_en_recorrido(self, n=2):
        entregas = [self._entrega() for _i in range(n)]
        ruta = self._ruta(entregas)
        ruta.action_aprobar_plan()
        ruta.action_confirmar_carga()
        ruta.action_iniciar_recorrido()
        return ruta, entregas

    def _respuesta(self, vehiculo, entregas, **extra):
        resp = {
            'routes': [{
                'vehicle_id': vehiculo.id,
                'stops': [{'id': e.id, 'sequence': i + 1} for i, e in enumerate(entregas)],
                'distance_km': 5.5, 'duration_min': 12.0, 'load': len(entregas)}],
            'unassigned': [], 'source': 'estimado_haversine', 'optimization_version': 'v-test',
        }
        resp.update(extra)
        return resp

    def _planificar(self, vehiculos, respuesta):
        plan = self.env['logistica.planificador'].create({
            'vehicle_ids': [(6, 0, [v.id for v in vehiculos])]})
        with patch(OPTIMIZE, return_value=respuesta) as mock:
            accion = plan.action_proponer()
        return accion, mock

    # ----------------------------------------------------------- planificador
    def test_planificador_rutas_desde_bodega(self):
        e1, e2 = self._entrega(), self._entrega()
        veh = self._vehiculo()
        accion, mock = self._planificar([veh], self._respuesta(veh, [e2, e1]))
        payload = mock.call_args.args[1]
        self.assertEqual(payload['depot'], {'lat': self.bodega.latitude, 'lon': self.bodega.longitude})
        rutas = self.env['logistica.ruta'].search(accion['domain'])
        self.assertEqual(len(rutas), 1)
        self.assertEqual(rutas.state, 'borrador')
        self.assertEqual(rutas.vehicle_id, veh)
        self.assertEqual(rutas.driver_id, veh.driver_id)
        self.assertEqual(rutas.bodega_id, self.bodega)
        self.assertEqual(rutas.optimization_version, 'v-test')
        self.assertEqual(rutas.stop_ids.sorted('sequence').mapped('entrega_id'), e2 | e1)

    def test_planificador_solo_preparados(self):
        preparada = self._entrega('preparado')
        en_preparacion = self._entrega('en_preparacion')
        veh = self._vehiculo()
        _accion, mock = self._planificar([veh], self._respuesta(veh, [preparada]))
        ids = {s['id'] for s in mock.call_args.args[1]['stops']}
        self.assertIn(preparada.id, ids)
        self.assertNotIn(en_preparacion.id, ids)

    def test_no_asignados_quedan_preparados(self):
        entrega = self._entrega()
        veh = self._vehiculo()
        resp = {'routes': [], 'unassigned': [{'id': entrega.id, 'reason': 'sin_capacidad'}],
                'source': 'estimado_haversine', 'optimization_version': 'v-test'}
        self._planificar([veh], resp)
        self.assertEqual(entrega.state, 'preparado')
        evento = entrega.event_ids.filtered(lambda ev: ev.event_type == 'no_asignado')
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento.notes, 'sin_capacidad')

    def test_capacidad_del_vehiculo(self):
        entrega = self._entrega()
        veh = self._vehiculo(capacidad=7)
        _accion, mock = self._planificar([veh], self._respuesta(veh, [entrega]))
        vehiculos = mock.call_args.args[1]['vehicles']
        self.assertEqual(vehiculos, [{'id': veh.id, 'capacity': 7}])

    def test_nuevo_pedido_no_entra_a_ruta_iniciada(self):
        ruta, _entregas = self._ruta_en_recorrido(1)
        nueva = self._entrega()
        otro = self._vehiculo()
        _accion, mock = self._planificar([ruta.vehicle_id, otro], self._respuesta(otro, [nueva]))
        # El vehículo con ruta iniciada no se ofrece al optimizador y su ruta no cambia.
        ids_vehiculo = {v['id'] for v in mock.call_args.args[1]['vehicles']}
        self.assertNotIn(ruta.vehicle_id.id, ids_vehiculo)
        self.assertNotIn(nueva, ruta.stop_ids.mapped('entrega_id'))
        with self.assertRaises(UserError):
            ruta.write({'stop_ids': [(0, 0, {'entrega_id': nueva.id})]})
        with self.assertRaises(UserError):
            self.env['logistica.ruta.parada'].create({'route_id': ruta.id, 'entrega_id': nueva.id})

    # ------------------------------------------------------- máquina de estados
    def test_aprobar_plan(self):
        e1, e2 = self._entrega(), self._entrega()
        ruta = self._ruta([e1, e2])
        ruta.action_aprobar_plan()
        self.assertEqual(ruta.state, 'planificada')
        for entrega in (e1, e2):
            self.assertEqual(entrega.state, 'asignado')
            self.assertEqual(entrega.route_id, ruta.id)
            self.assertEqual(entrega.ruta_id, ruta)

    def test_confirmar_carga_requiere_paradas(self):
        vacia = self.env['logistica.ruta'].create({
            'vehicle_id': self._vehiculo().id, 'bodega_id': self.bodega.id,
            'driver_id': self._vehiculo().driver_id.id})
        vacia.write({'state': 'planificada'})
        with self.assertRaises(UserError):
            vacia.action_confirmar_carga()
        entrega = self._entrega()
        ruta = self._ruta([entrega])
        ruta.action_aprobar_plan()
        ruta.action_confirmar_carga()
        self.assertEqual(ruta.state, 'carga_confirmada')
        self.assertTrue(ruta.confirmed_load_at)
        self.assertTrue(entrega.event_ids.filtered(lambda ev: ev.event_type == 'carga_confirmada'))

    def test_iniciar_solo_desde_carga_confirmada(self):
        ruta = self._ruta([self._entrega()])
        ruta.action_aprobar_plan()
        with self.assertRaises(UserError):
            ruta.action_iniciar_recorrido()
        self.assertEqual(ruta.state, 'planificada')

    def test_doble_inicio_rechazado(self):
        entrega = self._entrega()
        ruta = self._ruta([entrega])
        ruta.action_aprobar_plan()
        ruta.action_confirmar_carga()
        ruta.action_iniciar_recorrido()
        with self.assertRaises(UserError):
            ruta.action_iniciar_recorrido()
        self.assertEqual(ruta.state, 'en_recorrido')
        self.assertEqual(entrega.state, 'en_recorrido')
        self.assertEqual(len(entrega.event_ids.filtered(
            lambda ev: ev.event_type == 'inicio_recorrido')), 1)

    def test_cerrar_diferencia_fallidos(self):
        ruta, (e1, e2) = self._ruta_en_recorrido(2)
        p1, p2 = ruta.stop_ids.sorted('sequence')
        with self.assertRaises(UserError):
            ruta.action_cerrar()
        p1.action_marcar_entregado()
        with self.assertRaises(UserError):
            ruta.action_cerrar()
        p2.action_marcar_no_entregado('absent')
        ruta.action_cerrar()
        self.assertEqual(ruta.state, 'cerrada')
        self.assertTrue(ruta.finished_at)
        self.assertEqual((ruta.delivered_stops, ruta.failed_stops, ruta.pending_stops), (1, 1, 0))
        self.assertEqual(e1.state, 'entregado')
        self.assertEqual(e2.state, 'pendiente_reprogramacion')
        self.assertEqual(p2.failed_reason, 'absent')

    def test_cancelar_antes_de_iniciar(self):
        e1, e2 = self._entrega(), self._entrega()
        planificada = self._ruta([e1, e2])
        planificada.action_aprobar_plan()
        planificada.action_cancelar('Cambio de plan')
        self.assertEqual(planificada.state, 'cancelada')
        for entrega in (e1, e2):
            self.assertEqual(entrega.state, 'preparado')
            self.assertEqual(entrega.route_id, 0)
            self.assertTrue(entrega.event_ids.filtered(lambda ev: ev.event_type == 'desasignado'))
        e3 = self._entrega()
        borrador = self._ruta([e3])
        borrador.action_cancelar()
        self.assertEqual(borrador.state, 'cancelada')
        self.assertEqual(e3.state, 'preparado')

    def test_interrumpir_durante_ejecucion(self):
        ruta, (e1, e2) = self._ruta_en_recorrido(2)
        p1, _p2 = ruta.stop_ids.sorted('sequence')
        p1.action_marcar_entregado()
        with self.assertRaises(UserError):
            ruta.action_interrumpir('')
        ruta.action_interrumpir('Avería del vehículo')
        self.assertEqual(ruta.state, 'interrumpida')
        self.assertEqual(ruta.interrupt_reason, 'Avería del vehículo')
        self.assertEqual(e1.state, 'entregado')
        self.assertEqual(e2.state, 'pendiente_reprogramacion')

    # ------------------------------------------------------------ paradas
    def test_parada_entregado_idempotente(self):
        ruta, (e1, _e2) = self._ruta_en_recorrido(2)
        parada = ruta.stop_ids.filtered(lambda p: p.entrega_id == e1)
        parada.action_marcar_entregado()
        with self.assertRaises(UserError):
            parada.action_marcar_entregado()
        self.assertEqual(len(e1.event_ids.filtered(lambda ev: ev.event_type == 'entregado')), 1)

    def test_llegada_manual_no_cambia_estado_de_la_entrega(self):
        ruta, (e1, _e2) = self._ruta_en_recorrido(2)
        parada = ruta.stop_ids.filtered(lambda p: p.entrega_id == e1)
        parada.action_marcar_llegada()
        self.assertEqual(e1.state, 'en_recorrido')
        self.assertTrue(parada.actual_arrival_at)
        with self.assertRaises(UserError):
            parada.action_marcar_llegada()

    def test_no_entregado_requiere_motivo_valido(self):
        ruta, (e1, _e2) = self._ruta_en_recorrido(2)
        parada = ruta.stop_ids.filtered(lambda p: p.entrega_id == e1)
        with self.assertRaises(Exception):
            parada.action_marcar_no_entregado('')
        with self.assertRaises(Exception):
            parada.action_marcar_no_entregado('inventado')
        self.assertEqual(parada.state, 'pendiente')

    def test_assert_driver(self):
        ruta = self._ruta([self._entrega()])
        usuario_conductor = self.env['res.users'].create({
            'name': 'Usuario Conductor', 'login': 'cond_despacho_test',
            'partner_id': ruta.driver_id.id})
        ruta.assert_driver(usuario_conductor)
        otro = self.env['res.users'].create({'name': 'Otro', 'login': 'otro_despacho_test'})
        with self.assertRaises(AccessError):
            ruta.assert_driver(otro)
