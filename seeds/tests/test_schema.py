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


if __name__ == '__main__':
    unittest.main()
