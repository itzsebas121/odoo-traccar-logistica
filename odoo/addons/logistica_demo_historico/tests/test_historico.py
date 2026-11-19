# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

LAT, LON = -1.2417, -78.6197


@tagged('post_install', '-at_install', 'logistica_demo_historico')
class TestHistorico(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cliente = cls.env['res.partner'].create({'name': 'Cliente Historico'})
        cls.producto = cls.env['product.product'].create({'name': 'Producto Historico', 'type': 'consu',
                                                          'list_price': 2})
        marca = cls.env['fleet.vehicle.model.brand'].create({'name': 'MarcaHistorico'})
        modelo = cls.env['fleet.vehicle.model'].create({'name': 'ModeloHistorico', 'brand_id': marca.id})
        cls.conductor = cls.env['res.partner'].create({'name': 'Conductor Historico', 'is_driver': True})
        cls.vehiculo = cls.env['fleet.vehicle'].create({'model_id': modelo.id, 'license_plate': 'HIS-0001',
                                                        'driver_id': cls.conductor.id})
        cls.H = cls.env['logistica.demo.historico']

    def _dia(self, ref='T-001', resultado='entregado'):
        return {
            'pedidos': [{'ref': ref, 'partner_id': self.cliente.id, 'lat': LAT, 'lon': LON,
                         'fecha': '2026-06-01 15:10:00', 'lineas': [[self.producto.id, 3]]}],
            'rutas': [{'clave': 'r-' + ref, 'vehicle_id': self.vehiculo.id, 'driver_id': self.conductor.id,
                       'fecha': '2026-06-02', 'carga': '2026-06-02 13:30:00', 'inicio': '2026-06-02 14:00:00',
                       'fin': '2026-06-02 15:30:00', 'km': 12.5, 'min': 80,
                       'paradas': [{'ref': ref, 'llegada': '2026-06-02 14:20:00', 'cierre': '2026-06-02 14:27:00',
                                    'resultado': resultado, 'motivo': 'absent'}]}],
        }

    def test_dia_completo_con_fechas_historicas(self):
        conteo = self.H.registrar_dia(self._dia())
        self.assertEqual(conteo['pedidos_creados'], 1)
        self.assertEqual(conteo['rutas_creadas'], 1)
        pedido = self.env['sale.order'].search([('client_order_ref', '=', 'T-001')])
        self.assertEqual(pedido.state, 'sale')
        self.assertEqual(pedido.date_order, datetime(2026, 6, 1, 15, 10))
        entrega = pedido.logistica_entrega_ids
        self.assertEqual(entrega.state, 'entregado')
        ruta = self.env['logistica.ruta'].browse(entrega.route_id)
        self.assertEqual(ruta.state, 'cerrada')
        self.assertEqual(ruta.started_at, datetime(2026, 6, 2, 14, 0))
        self.assertEqual(ruta.finished_at, datetime(2026, 6, 2, 15, 30))
        self.assertEqual(ruta.stop_ids.completed_at, datetime(2026, 6, 2, 14, 27))
        evento = entrega.event_ids.filtered(lambda e: e.event_type == 'entregado')
        self.assertEqual(evento.event_time, datetime(2026, 6, 2, 14, 27))
        creado = entrega.event_ids.filtered(lambda e: e.event_type == 'creado')
        self.assertEqual(creado.event_time, datetime(2026, 6, 1, 15, 10))

    def test_idempotente(self):
        self.H.registrar_dia(self._dia('T-002'))
        conteo = self.H.registrar_dia(self._dia('T-002'))
        self.assertEqual(conteo['pedidos_creados'], 0)
        self.assertEqual(conteo['rutas_creadas'], 0)
        self.assertEqual(self.env['sale.order'].search_count([('client_order_ref', '=', 'T-002')]), 1)

    def test_no_entregado_queda_para_reprogramar(self):
        self.H.registrar_dia(self._dia('T-003', resultado='no_entregado'))
        entrega = self.env['sale.order'].search([('client_order_ref', '=', 'T-003')]).logistica_entrega_ids
        self.assertEqual(entrega.state, 'pendiente_reprogramacion')
        dia2 = self._dia('T-003')
        dia2['pedidos'] = []
        dia2['rutas'][0]['clave'] = 'r2-T-003'
        self.H.registrar_dia(dia2)
        self.assertEqual(entrega.state, 'entregado')

    def test_solo_administrador(self):
        usuario = self.env['res.users'].create({'name': 'Sin permiso', 'login': 'sin_permiso_historico',
                                                'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            self.H.with_user(usuario).registrar_dia(self._dia('T-004'))
