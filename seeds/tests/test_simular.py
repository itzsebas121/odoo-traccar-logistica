# -*- coding: utf-8 -*-
import math
import re
import unittest
import urllib.parse
from unittest import mock

from seeds import schema
from seeds import simular

_CIRCULO = re.compile(r'^CIRCLE \((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?), (\d+(?:\.\d+)?)\)$')


def _metros(lat1, lon1, lat2, lon2):
    medio = math.radians((lat1 + lat2) / 2.0)
    dy = math.radians(lat2 - lat1) * 6371000
    dx = math.radians(lon2 - lon1) * 6371000 * math.cos(medio)
    return math.hypot(dx, dy)


class SimuladorTest(unittest.TestCase):

    def test_url_lleva_id_lat_lon_speed_y_timestamp_en_segundos(self):
        url = simular.construir_url('http://127.0.0.1:5055/', 'GPS-ABC-1234', {
            'lat': 4.6197, 'lon': -74.0817, 'speed': 40, 'timestamp': 1762473600,
        })
        partes = urllib.parse.urlparse(url)
        consulta = urllib.parse.parse_qs(partes.query)
        self.assertEqual(partes.scheme, 'http')
        self.assertEqual(partes.netloc, '127.0.0.1:5055')
        self.assertEqual(partes.path, '/')
        self.assertEqual(consulta['id'], ['GPS-ABC-1234'])
        self.assertEqual(consulta['lat'], ['4.6197'])
        self.assertEqual(consulta['lon'], ['-74.0817'])
        self.assertEqual(consulta['speed'], ['40'])
        self.assertEqual(consulta['timestamp'], ['1762473600'])
        self.assertLess(int(consulta['timestamp'][0]), 10 ** 11)

    def test_json_sin_uniqueId_falla(self):
        _odoo, _traccar, simulacion = schema.cargar()
        del simulacion['rutas'][0]['uniqueId']
        with self.assertRaisesRegex(schema.ErrorEsquema, "'uniqueId'"):
            schema.validar_simulacion(simulacion)

    def test_la_ruta_entra_a_la_geocerca_por_encima_del_limite(self):
        _odoo, traccar, simulacion = schema.cargar()
        geocerca = next(g for g in traccar['geocercas'] if g['name'] == 'Bodega central')
        coincidencia = _CIRCULO.match(geocerca['area'])
        self.assertIsNotNone(coincidencia)
        centro_lat = float(coincidencia.group(1))
        centro_lon = float(coincidencia.group(2))
        radio_m = float(coincidencia.group(3))
        ruta = next(r for r in simulacion['rutas'] if r['uniqueId'] == 'GPS-ABC-1234')
        limite = next(
            d['attributes']['speedLimit'] for d in traccar['dispositivos']
            if d['uniqueId'] == ruta['uniqueId'])
        dentro = []
        for punto in ruta['puntos']:
            dentro.append(_metros(centro_lat, centro_lon, punto['lat'], punto['lon']) <= radio_m)
        self.assertIn(False, dentro)
        self.assertIn(True, dentro)
        self.assertLess(dentro.index(False), dentro.index(True))
        self.assertTrue(any(p['speed'] > limite for p in ruta['puntos']))
        self.assertTrue(any(p['speed'] <= limite for p in ruta['puntos']))

    def test_respuesta_distinta_de_200_falla_sin_red(self):
        error = urllib_error_http(500)
        with mock.patch('seeds.simular.urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(simular.ErrorSimulacion, 'HTTP 500'):
                simular._enviar('http://127.0.0.1:5055', 'GPS-ABC-1234', {
                    'lat': 4.61, 'lon': -74.08, 'speed': 10, 'timestamp': 1762473600,
                })

    def test_sin_url_osmand_falla(self):
        with mock.patch.dict('os.environ', {'TRACCAR_OSMAND_URL': ''}, clear=False):
            with self.assertRaisesRegex(simular.ErrorSimulacion, 'TRACCAR_OSMAND_URL'):
                simular.url_osmand()


def urllib_error_http(codigo):
    import urllib.error
    return urllib.error.HTTPError('http://127.0.0.1:5055/', codigo, 'error', hdrs=None, fp=None)


if __name__ == '__main__':
    unittest.main()
