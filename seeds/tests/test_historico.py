# -*- coding: utf-8 -*-
import copy
import unittest
from datetime import date, datetime

from seeds import historico, schema

HOY = date(2026, 11, 16)


class HistoricoTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.datos = schema.cargar_historico()
        odoo, _t, _s = schema.cargar()
        cls.vehiculos = [{'license_plate': v['license_plate'], 'uniqueId': v['uniqueId']} for v in odoo['vehiculos']]
        cls.bodega = (odoo['bodega_logistica']['latitude'], odoo['bodega_logistica']['longitude'])
        cls.clientes, cls.plan = historico.planificar(cls.datos, cls.vehiculos, cls.bodega, HOY, dias=60)

    def test_json_valido(self):
        schema.validar_historico(self.datos)

    def test_coordenada_fuera_de_ambato_falla(self):
        datos = copy.deepcopy(self.datos)
        datos['parroquias'][0]['lat'] = -0.18     # Quito
        with self.assertRaisesRegex(schema.ErrorEsquema, 'fuera del canton Ambato'):
            schema.validar_historico(datos)

    def test_categoria_inexistente_falla(self):
        datos = copy.deepcopy(self.datos)
        datos['productos'][0]['categoria'] = 'No existe'
        with self.assertRaisesRegex(schema.ErrorEsquema, 'categoria'):
            schema.validar_historico(datos)

    def test_plan_determinista(self):
        _c, otro = historico.planificar(self.datos, self.vehiculos, self.bodega, HOY, dias=60)
        self.assertEqual(self.plan, otro)

    def test_un_dia_sale_igual_con_otra_ventana(self):
        _c, largo = historico.planificar(self.datos, self.vehiculos, self.bodega, HOY, dias=90)
        por_fecha = {d['fecha']: d['pedidos'] for d in largo}
        for dia in self.plan:
            self.assertEqual(dia['pedidos'], por_fecha[dia['fecha']])

    def test_clientes_unicos_y_en_ambato(self):
        nombres = [c['name'] for c in self.clientes]
        self.assertEqual(len(nombres), len(set(nombres)))
        total = sum(p['clientes'] for p in self.datos['parroquias'])
        self.assertEqual(len(self.clientes), total)
        (la0, la1), (lo0, lo1) = schema.CAJA_AMBATO['lat'], schema.CAJA_AMBATO['lon']
        for c in self.clientes:
            self.assertTrue(la0 <= c['lat'] <= la1 and lo0 <= c['lon'] <= lo1, c)

    def test_referencias_unicas_y_rutas_con_pedidos_previos(self):
        refs = [p['ref'] for d in self.plan for p in d['pedidos']]
        self.assertEqual(len(refs), len(set(refs)))
        vistos = set()
        for dia in self.plan:
            for ruta in dia['rutas']:
                for parada in ruta['paradas']:
                    self.assertIn(parada['ref'], vistos, 'una ruta entrega un pedido de un dia anterior')
            vistos.update(p['ref'] for p in dia['pedidos'])

    def test_tiempos_ordenados(self):
        for dia in self.plan:
            for r in dia['rutas']:
                self.assertLess(r['carga'], r['inicio'])
                anterior = r['inicio']
                for p in r['paradas']:
                    self.assertLessEqual(anterior, p['llegada'])
                    self.assertLess(p['llegada'], p['cierre'])
                    anterior = p['cierre']
                self.assertLessEqual(anterior, r['fin'])

    def test_fallidas_se_reintentan(self):
        fallidas = {p['ref'] for d in self.plan[:-1] for r in d['rutas'] for p in r['paradas']
                    if p['resultado'] == 'no_entregado'}
        self.assertTrue(fallidas)
        entregas = [p['ref'] for d in self.plan for r in d['rutas'] for p in r['paradas']]
        for ref in fallidas:
            self.assertGreaterEqual(entregas.count(ref), 2, ref)

    def test_demanda_con_patron_semanal_y_de_ubicacion(self):
        # Sabados (peso 1,35) con mas pedidos que martes (0,85), en promedio.
        por_dia = {}
        for d in self.plan:
            por_dia.setdefault(datetime.strptime(d['fecha'], '%Y-%m-%d').weekday(), []).append(len(d['pedidos']))
        media = {k: sum(v) / len(v) for k, v in por_dia.items()}
        self.assertGreater(media[5], media[1])
        # El mismo producto pesa distinto segun la parroquia (factor local estable).
        cats = {c['nombre']: c for c in self.datos['categorias']}
        prod = self.datos['productos'][0]
        pesos = {historico.afinidad(prod, c, cats, 1) for c in self.clientes if c['tipo'] == 'urbana'}
        self.assertGreater(len(pesos), 3)

    def test_gps_cronologico(self):
        ruta = self.plan[-1]['rutas'][0]
        puntos = historico.puntos_gps(ruta, self.bodega, self.datos['operacion'], 1)
        marcas = [p['timestamp'] for p in puntos]
        self.assertEqual(marcas, sorted(marcas))
        self.assertGreater(len(puntos), 20)
        self.assertTrue(any(p['speed'] == 0 for p in puntos))
        self.assertTrue(any(p['speed'] > 0 for p in puntos))


if __name__ == '__main__':
    unittest.main()
