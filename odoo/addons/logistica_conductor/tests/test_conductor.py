# -*- coding: utf-8 -*-
import re

from odoo.tests.common import HttpCase, tagged

LAT, LON = -1.2417, -78.6197


@tagged('post_install', '-at_install', 'logistica_conductor')
class TestConductor(HttpCase):

    def setUp(self):
        super().setUp()
        self.cliente = self.env['res.partner'].create({'name': 'Cliente Conductor', 'phone': '0988888888'})
        self.producto = self.env['product.product'].create({
            'name': 'Producto Conductor', 'type': 'consu', 'list_price': 10})
        marca = self.env['fleet.vehicle.model.brand'].create({'name': 'MarcaCond'})
        self.modelo = self.env['fleet.vehicle.model'].create({'name': 'ModeloCond', 'brand_id': marca.id})
        self.bodega = self.env['logistica.bodega'].get_bodega_activa()
        self.user_a = self._conductor('cond-a')
        self.user_b = self._conductor('cond-b')
        self.ruta_a = self._ruta(self.user_a, 'CND-0001', n=2)
        self.ruta_b = self._ruta(self.user_b, 'CND-0002', n=1)

    # ---------------------------------------------------------------- ayudas
    def _conductor(self, login):
        grupos = [self.env.ref(x).id for x in ('base.group_user', 'logistica_conductor.group_conductor')]
        usuario = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Conductor %s' % login, 'login': login, 'password': '%s-clave' % login,
            'groups_id': [(6, 0, grupos)]})
        usuario.partner_id.write({'is_driver': True})
        return usuario

    def _entrega(self):
        pedido = self.env['sale.order'].create({
            'partner_id': self.cliente.id, 'delivery_latitude': LAT, 'delivery_longitude': LON,
            'order_line': [(0, 0, {'product_id': self.producto.id, 'product_uom_qty': 1})]})
        pedido.action_confirm()
        entrega = pedido.logistica_entrega_id
        entrega.action_marcar_preparado()
        return entrega

    def _ruta(self, usuario, placa, n=1, estado='planificada'):
        vehiculo = self.env['fleet.vehicle'].create({
            'model_id': self.modelo.id, 'license_plate': placa, 'driver_id': usuario.partner_id.id})
        ruta = self.env['logistica.ruta'].create({
            'vehicle_id': vehiculo.id, 'driver_id': usuario.partner_id.id, 'bodega_id': self.bodega.id,
            'stop_ids': [(0, 0, {'entrega_id': self._entrega().id, 'sequence': i + 1}) for i in range(n)]})
        if estado in ('planificada', 'carga_confirmada', 'en_recorrido'):
            ruta.action_aprobar_plan()
        if estado in ('carga_confirmada', 'en_recorrido'):
            ruta.action_confirmar_carga()
        if estado == 'en_recorrido':
            ruta.action_iniciar_recorrido()
        return ruta

    def _entrar(self, usuario):
        self.authenticate(usuario.login, '%s-clave' % usuario.login)

    def _csrf(self):
        html = self.url_open('/logistica/conductor').text
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def _post(self, url, **datos):
        datos['csrf_token'] = self._csrf()
        return self.url_open(url, data=datos, allow_redirects=False)

    def _refrescar(self):
        self.env.invalidate_all()

    def _eventos(self, entrega, tipo):
        return entrega.event_ids.filtered(lambda e: e.event_type == tipo)

    # ----------------------------------------------------------------- pruebas
    def test_conductor_solo_ve_sus_rutas(self):
        self._entrar(self.user_a)
        lista = self.url_open('/logistica/conductor').text
        self.assertIn(self.ruta_a.name, lista)
        self.assertNotIn(self.ruta_b.name, lista)
        propia = self.url_open('/logistica/conductor/ruta/%s' % self.ruta_a.id)
        self.assertEqual(propia.status_code, 200)
        ajena = self.url_open('/logistica/conductor/ruta/%s' % self.ruta_b.id)
        self.assertIn(ajena.status_code, (403, 404))
        self.assertNotIn(self.ruta_b.vehicle_plate, ajena.text)
        inexistente = self.url_open('/logistica/conductor/ruta/999999')
        self.assertEqual(inexistente.status_code, ajena.status_code)

    def test_regla_registro_por_conductor(self):
        rutas = self.env['logistica.ruta'].with_user(self.user_a).search([])
        self.assertIn(self.ruta_a, rutas)
        self.assertNotIn(self.ruta_b, rutas)
        self.assertTrue(all(r.driver_id == self.user_a.partner_id for r in rutas))
        paradas = self.env['logistica.ruta.parada'].with_user(self.user_a).search([])
        self.assertTrue(paradas)
        self.assertTrue(all(p.route_id.driver_id == self.user_a.partner_id for p in paradas))
        entregas = self.env['logistica.entrega'].with_user(self.user_a).search([])
        self.assertEqual(entregas, self.ruta_a.stop_ids.mapped('entrega_id'))

    def test_usuario_sin_grupo_403(self):
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Interno', 'login': 'interno-sin-grupo', 'password': 'interno-sin-grupo-clave',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.authenticate('interno-sin-grupo', 'interno-sin-grupo-clave')
        self.assertEqual(self.url_open('/logistica/conductor').status_code, 403)
        self.assertEqual(self.url_open('/logistica/conductor/ruta/%s' % self.ruta_a.id).status_code, 403)

    def test_confirmar_e_iniciar(self):
        self._entrar(self.user_a)
        url = '/logistica/conductor/ruta/%s' % self.ruta_a.id
        self.assertEqual(self._post(url + '/confirmar-carga').status_code, 303)
        self._refrescar()
        self.assertEqual(self.ruta_a.state, 'carga_confirmada')
        self.assertEqual(self._post(url + '/iniciar').status_code, 303)
        self._refrescar()
        self.assertEqual(self.ruta_a.state, 'en_recorrido')
        self.assertTrue(all(e.state == 'en_recorrido' for e in self.ruta_a.stop_ids.mapped('entrega_id')))
        # Un segundo «iniciar» no repite el evento y se informa como ya registrado.
        repetido = self._post(url + '/iniciar')
        self.assertEqual(repetido.status_code, 409)
        self._refrescar()
        for entrega in self.ruta_a.stop_ids.mapped('entrega_id'):
            self.assertEqual(len(self._eventos(entrega, 'inicio_recorrido')), 1)

    def test_entregado_idempotente(self):
        ruta = self._ruta(self.user_a, 'CND-0003', n=1, estado='en_recorrido')
        parada = ruta.stop_ids
        self._entrar(self.user_a)
        url = '/logistica/conductor/parada/%s/entregado' % parada.id
        self.assertEqual(self._post(url).status_code, 303)
        segunda = self._post(url)
        self.assertEqual(segunda.status_code, 409)
        self.assertIn('ya registrado', segunda.text)
        self._refrescar()
        self.assertEqual(parada.state, 'entregado')
        self.assertEqual(len(self._eventos(parada.entrega_id, 'entregado')), 1)

    def test_no_entregado_requiere_motivo(self):
        ruta = self._ruta(self.user_a, 'CND-0004', n=1, estado='en_recorrido')
        parada = ruta.stop_ids
        self._entrar(self.user_a)
        url = '/logistica/conductor/parada/%s/no-entregado' % parada.id
        self.assertEqual(self._post(url).status_code, 400)
        self.assertEqual(self._post(url, motivo='inventado').status_code, 400)
        self._refrescar()
        self.assertEqual(parada.state, 'pendiente')
        self.assertEqual(self._post(url, motivo='absent', notas='Nadie en casa').status_code, 303)
        self._refrescar()
        self.assertEqual(parada.state, 'no_entregado')
        self.assertEqual(parada.failed_reason, 'absent')
        evento = self._eventos(parada.entrega_id, 'no_entregado')
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento.failure_reason, 'absent')

    def test_orden_de_paradas(self):
        ruta = self._ruta(self.user_a, 'CND-0005', n=3, estado='en_recorrido')
        paradas = ruta.stop_ids.sorted('sequence')
        self._entrar(self.user_a)
        html = self.url_open('/logistica/conductor/ruta/%s' % ruta.id).text
        posiciones = [html.index(p.entrega_id.name) for p in paradas]
        self.assertEqual(posiciones, sorted(posiciones))
        self.assertEqual(html.count('Siguiente parada'), 1)
        self.assertLess(html.index('Siguiente parada'), posiciones[0])
        # Tras entregar la primera, la siguiente es la segunda.
        self._post('/logistica/conductor/parada/%s/entregado' % paradas[0].id)
        html = self.url_open('/logistica/conductor/ruta/%s' % ruta.id).text
        self.assertEqual(html.count('Siguiente parada'), 1)
        self.assertGreater(html.index('Siguiente parada'), html.index(paradas[0].entrega_id.name))
        self.assertLess(html.index('Siguiente parada'), html.index(paradas[1].entrega_id.name))

    def test_conductor_no_entrega_ajena(self):
        ruta_b = self._ruta(self.user_b, 'CND-0006', n=1, estado='en_recorrido')
        parada_b = ruta_b.stop_ids
        self._entrar(self.user_a)
        for accion in ('llegada', 'entregado'):
            respuesta = self._post('/logistica/conductor/parada/%s/%s' % (parada_b.id, accion))
            self.assertEqual(respuesta.status_code, 403, accion)
        self.assertEqual(self._post('/logistica/conductor/parada/%s/no-entregado' % parada_b.id,
                                    motivo='absent').status_code, 403)
        self.assertEqual(self._post('/logistica/conductor/ruta/%s/cerrar' % ruta_b.id).status_code, 403)
        self._refrescar()
        self.assertEqual(parada_b.state, 'pendiente')
        self.assertEqual(ruta_b.state, 'en_recorrido')

    def test_cerrar_ruta_con_todo_registrado(self):
        ruta = self._ruta(self.user_a, 'CND-0007', n=2, estado='en_recorrido')
        p1, p2 = ruta.stop_ids.sorted('sequence')
        self._entrar(self.user_a)
        cerrar = '/logistica/conductor/ruta/%s/cerrar' % ruta.id
        self.assertEqual(self._post(cerrar).status_code, 400)  # aún hay pendientes
        self._post('/logistica/conductor/parada/%s/entregado' % p1.id)
        self._post('/logistica/conductor/parada/%s/no-entregado' % p2.id, motivo='refused')
        self.assertEqual(self._post(cerrar).status_code, 303)
        self._refrescar()
        self.assertEqual(ruta.state, 'cerrada')
        self.assertEqual((ruta.delivered_stops, ruta.failed_stops), (1, 1))

    def test_interrumpir_exige_motivo(self):
        ruta = self._ruta(self.user_a, 'CND-0008', n=1, estado='en_recorrido')
        self._entrar(self.user_a)
        url = '/logistica/conductor/ruta/%s/interrumpir' % ruta.id
        self.assertEqual(self._post(url).status_code, 400)
        self.assertEqual(self._post(url, motivo='Avería').status_code, 303)
        self._refrescar()
        self.assertEqual(ruta.state, 'interrumpida')

    def test_post_sin_csrf_se_rechaza(self):
        ruta = self._ruta(self.user_a, 'CND-0009', n=1, estado='en_recorrido')
        self._entrar(self.user_a)
        respuesta = self.url_open(
            '/logistica/conductor/parada/%s/entregado' % ruta.stop_ids.id, data={}, allow_redirects=False)
        self.assertEqual(respuesta.status_code, 400)
        self._refrescar()
        self.assertEqual(ruta.stop_ids.state, 'pendiente')
