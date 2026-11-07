# -*- coding: utf-8 -*-
import copy
import unittest

from seeds import schema


class EsquemaSeedsTest(unittest.TestCase):

    def setUp(self):
        self.odoo, self.traccar, self.simulacion = schema.cargar()

    def test_json_validos_pasan_con_los_datos_de_la_seccion_11(self):
        schema.validar_todo(self.odoo, self.traccar, self.simulacion)
        self.assertEqual(['ABC-1234', 'DEF-5678', 'GHI-9012'],
                         [v['license_plate'] for v in self.odoo['vehiculos']])
        self.assertEqual(['Carlos', 'Luis', 'Pedro'],
                         [c['name'] for c in self.odoo['conductores']])
        self.assertEqual(3, len(self.traccar['dispositivos']))
        self.assertEqual(5, len(self.simulacion['pedidos']))
        self.assertEqual(5, len(self.odoo['productos']))
        self.assertEqual(3, len(self.odoo['usuarios_conductor']))
        self.assertEqual(3, len(self.simulacion['rutas']))

    def test_dispositivo_sin_uniqueId_falla_nombrando_el_campo(self):
        traccar = copy.deepcopy(self.traccar)
        del traccar['dispositivos'][0]['uniqueId']
        with self.assertRaisesRegex(schema.ErrorEsquema, "'uniqueId'"):
            schema.validar_traccar(traccar)

    def test_vehiculo_sin_uniqueId_falla_nombrando_el_campo(self):
        odoo = copy.deepcopy(self.odoo)
        del odoo['vehiculos'][0]['uniqueId']
        with self.assertRaisesRegex(schema.ErrorEsquema, "'uniqueId'"):
            schema.validar_odoo(odoo)

    def test_vehiculo_con_uniqueId_inexistente_falla(self):
        odoo = copy.deepcopy(self.odoo)
        odoo['vehiculos'][1]['uniqueId'] = 'GPS-NO-EXISTE'
        with self.assertRaisesRegex(schema.ErrorEsquema, 'GPS-NO-EXISTE'):
            schema.validar_todo(odoo, self.traccar, self.simulacion)

    def test_speedLimit_no_numerico_falla_nombrando_el_campo(self):
        traccar = copy.deepcopy(self.traccar)
        traccar['dispositivos'][0]['attributes']['speedLimit'] = 'treinta'
        with self.assertRaisesRegex(schema.ErrorEsquema, 'speedLimit'):
            schema.validar_traccar(traccar)

    def test_latitud_fuera_de_rango_falla(self):
        simulacion = copy.deepcopy(self.simulacion)
        simulacion['pedidos'][0]['latitud'] = 95
        with self.assertRaisesRegex(schema.ErrorEsquema, 'latitud'):
            schema.validar_simulacion(simulacion)

    def test_usuario_integracion_con_administrador_falla(self):
        traccar = copy.deepcopy(self.traccar)
        traccar['usuarios'][0]['administrator'] = True
        with self.assertRaisesRegex(schema.ErrorEsquema, "'administrator'"):
            schema.validar_traccar(traccar)

    def test_usuario_integracion_sin_solo_lectura_falla(self):
        traccar = copy.deepcopy(self.traccar)
        traccar['usuarios'][0]['readonly'] = False
        with self.assertRaisesRegex(schema.ErrorEsquema, "'readonly'"):
            schema.validar_traccar(traccar)


    def test_producto_sin_precio_falla_nombrando_el_campo(self):
        odoo = copy.deepcopy(self.odoo)
        del odoo['productos'][0]['list_price']
        with self.assertRaisesRegex(schema.ErrorEsquema, "'list_price'"):
            schema.validar_odoo(odoo)

    def test_usuario_conductor_de_un_conductor_inexistente_falla(self):
        odoo = copy.deepcopy(self.odoo)
        odoo['usuarios_conductor'][0]['conductor'] = 'Nadie'
        with self.assertRaisesRegex(schema.ErrorEsquema, 'Nadie'):
            schema.validar_todo(odoo, self.traccar, self.simulacion)

    def test_login_repetido_falla(self):
        odoo = copy.deepcopy(self.odoo)
        odoo['usuarios_conductor'][1]['login'] = odoo['usuarios_conductor'][0]['login']
        with self.assertRaisesRegex(schema.ErrorEsquema, 'login'):
            schema.validar_odoo(odoo)

    def test_bodega_fuera_de_la_geocerca_falla(self):
        odoo = copy.deepcopy(self.odoo)
        odoo['bodega_logistica']['latitude'] = odoo['bodega_logistica']['latitude'] + 1.0
        with self.assertRaisesRegex(schema.ErrorEsquema, 'geocerca'):
            schema.validar_todo(odoo, self.traccar, self.simulacion)

    def test_cada_vehiculo_tiene_una_ruta_de_simulacion(self):
        con_ruta = {r['uniqueId'] for r in self.simulacion['rutas']}
        self.assertEqual(con_ruta, {v['uniqueId'] for v in self.odoo['vehiculos']})


if __name__ == '__main__':
    unittest.main()
