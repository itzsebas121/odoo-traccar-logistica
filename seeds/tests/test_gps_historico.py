# -*- coding: utf-8 -*-
import unittest

from seeds import gps_historico as g

BODEGA = (-1.2705, -78.6249)
RUTA = {
    'clave': 'RUT-1', 'inicio': '2026-08-03 13:00:00', 'fin': '2026-08-03 15:00:00',
    'paradas': [
        {'lat': -1.2417, 'lon': -78.6197, 'llegada': '2026-08-03 13:20:00', 'cierre': '2026-08-03 13:28:00'},
        {'lat': -1.2500, 'lon': -78.6300, 'llegada': '2026-08-03 13:50:00', 'cierre': '2026-08-03 13:58:00'},
    ],
}


class GpsHistoricoTest(unittest.TestCase):

    def test_cronologico_y_con_paradas(self):
        puntos = g.puntos_gps(RUTA, BODEGA, 30, 8)
        marcas = [p['timestamp'] for p in puntos]
        self.assertEqual(marcas, sorted(marcas))
        self.assertGreater(len(puntos), 100)
        self.assertTrue(any(p['speed'] == 0 for p in puntos))
        self.assertTrue(any(p['speed'] > 0 for p in puntos))
        self.assertEqual(marcas[0], int(g._ts(RUTA['inicio'])))
        self.assertEqual(marcas[-1], int(g._ts(RUTA['fin'])))

    def test_determinista_por_ruta(self):
        self.assertEqual(g.puntos_gps(RUTA, BODEGA, 30, 8), g.puntos_gps(RUTA, BODEGA, 30, 8))

    def test_sin_ruido_pasa_por_la_parada(self):
        puntos = g.puntos_gps(RUTA, BODEGA, 30, 0)
        parada = RUTA['paradas'][0]
        t = int(g._ts(parada['llegada']))
        cerca = [p for p in puntos if abs(p['timestamp'] - t) <= 30]
        self.assertTrue(any(abs(p['lat'] - parada['lat']) < 0.001 for p in cerca))

    def test_armar_ruta_omite_paradas_sin_hora_y_ordena(self):
        ruta = {'name': 'RUT-9', 'started_at': '2026-08-03 13:00:00', 'finished_at': '2026-08-03 15:00:00'}
        paradas = [
            {'sequence': 2, 'entrega_id': [2, 'E2'], 'actual_arrival_at': '2026-08-03 14:00:00',
             'completed_at': '2026-08-03 14:05:00'},
            {'sequence': 1, 'entrega_id': [1, 'E1'], 'actual_arrival_at': '2026-08-03 13:30:00',
             'completed_at': '2026-08-03 13:35:00'},
            {'sequence': 3, 'entrega_id': [3, 'E3'], 'actual_arrival_at': False, 'completed_at': False},
        ]
        entregas = {1: {'latitude': -1.24, 'longitude': -78.61}, 2: {'latitude': -1.25, 'longitude': -78.62},
                    3: {'latitude': -1.26, 'longitude': -78.63}}
        armada = g.armar_ruta(ruta, paradas, entregas)
        self.assertEqual([p['lat'] for p in armada['paradas']], [-1.24, -1.25])
        self.assertEqual(armada['clave'], 'RUT-9')

    def test_armar_ruta_sin_horario_es_none(self):
        self.assertIsNone(g.armar_ruta({'name': 'X', 'started_at': False, 'finished_at': False}, [], {}))
        ruta = {'name': 'X', 'started_at': '2026-08-03 13:00:00', 'finished_at': '2026-08-03 15:00:00'}
        self.assertIsNone(g.armar_ruta(ruta, [], {}))


if __name__ == '__main__':
    unittest.main()
