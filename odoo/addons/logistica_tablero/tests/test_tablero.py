# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from odoo.addons.logistica_tablero import tablero
from odoo.addons.logistica_tablero.controllers import tablero as api


class DwhFalso:
    """Responde por nombre de consulta; registra los parametros que recibe."""

    def __init__(self, respuestas=None, error=None):
        self.respuestas, self.error, self.llamadas = respuestas or {}, error, []

    def consultar(self, nombre, sql, params=None):
        if self.error:
            raise self.error
        self.llamadas.append((nombre, params))
        return self.respuestas.get(nombre, [])


@tagged('post_install', '-at_install')
class TestTablero(TransactionCase):

    def setUp(self):
        super().setUp()
        api._cache.limpiar()
        self.addCleanup(setattr, api, '_dwh', None)

    def test_opciones_desde_el_dwh(self):
        api._dwh = DwhFalso({
            'opciones_zonas': [{'codigo': 'centro', 'nombre': 'Centro'}],
            'opciones_categorias': [{'categoria': 'Granos'}],
            'opciones_conductores': [{'conductor': 'Carlos'}]})
        self.assertEqual(api.consultar('opciones', {}), {
            'zonas': [{'codigo': 'centro', 'nombre': 'Centro'}], 'categorias': ['Granos'], 'conductores': ['Carlos']})

    def test_filtros_llegan_a_las_consultas(self):
        falso = DwhFalso({
            'ultimo_dia': [{'ultimo': '2026-11-17'}],
            'resumen_variacion': [{'importe_7d': 70, 'importe_7d_previo': 50, 'pedidos_7d': 7, 'pedidos_7d_previo': 5}],
            'resumen_total': [{'importe': 120, 'pedidos': 12, 'unidades': 30}],
            'resumen_simulado': [{'simulados': 0, 'total': 12}]})
        api._dwh = falso
        datos = api.consultar('resumen', {'zona': 'centro', 'categoria': 'Granos', 'procedencia': 'real',
                                          'conductor': 'no aplica en resumen'})
        self.assertEqual(datos['rango']['hasta'], '2026-11-17')
        self.assertEqual(datos['rango']['desde'], '2026-10-19')        # 30 dias que terminan en la ultima venta
        self.assertEqual((datos['kpi']['ticket'], datos['kpi']['variacion_importe_7d']), (10.0, 40.0))
        params = dict(falso.llamadas)['resumen_total']
        self.assertEqual((params['zona'], params['categoria'], params['proc'], params['conductor']),
                         ('centro', 'Granos', 'REAL', None))

    def test_filtro_invalido_es_un_mensaje(self):
        api._dwh = DwhFalso()
        self.assertIn('error', api.consultar('resumen', {'desde': '2026-11-10', 'hasta': '2026-11-01'}))
        self.assertIn('error', api.consultar('no_existe', {}))

    def test_sin_dwh_mensaje_simple(self):
        api._dwh = DwhFalso(error=tablero.SinDwh('Faltan las vistas del DWH (detalle tecnico)'))
        self.assertEqual(api.consultar('opciones', {}), {'error': tablero.MENSAJE_USUARIO})

    def test_sin_clave_no_intenta_conectar(self):
        with self.assertRaises(tablero.SinDwh):
            tablero.Dwh('db', '5432', 'logistica_dwh', 'dwh_ro', '').consultar('x', 'SELECT 1')

    def test_solo_gerentes(self):
        basico = self.env['res.users'].create({'name': 'Básico', 'login': 'basico_tablero',
                                               'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.assertFalse(api.puede_ver(basico))
        self.assertTrue(api.puede_ver(self.env.ref('base.user_admin')))

    def test_menus_y_accion(self):
        accion = self.env.ref('logistica_tablero.action_tablero_indicadores')
        self.assertEqual(accion.tag, 'logistica_tablero.tablero')
        menu = self.env.ref('logistica_tablero.menu_tablero_indicadores_dashboards')
        self.assertEqual(menu.parent_id, self.env.ref('spreadsheet_dashboard.spreadsheet_dashboard_menu_root'))
