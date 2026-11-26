# -*- coding: utf-8 -*-
"""El atributo integrity de Leaflet en las plantillas debe coincidir con el archivo servido.

Si no coincide, el navegador bloquea el archivo: sin leaflet.css las teselas salen sueltas y desordenadas, sin
controles de zoom ni pin (pasó en los cuatro mapas). Esta prueba recalcula el hash de cada archivo de
logistica_base/static/lib/leaflet y lo compara con cada plantilla que lo carga.
"""
import base64
import hashlib
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ADDONS = RAIZ / 'odoo' / 'addons'
LEAFLET = ADDONS / 'logistica_base' / 'static' / 'lib' / 'leaflet'
# <link ... href=".../leaflet/leaflet.css" ... integrity="sha256-..."> (o <script src=...>), en cualquier orden.
ETIQUETA = re.compile(r'<(?:link|script)\b[^>]*?(?:href|src)="/logistica_base/static/lib/leaflet/([^"?]+)"[^>]*>',
                      re.S)
INTEGRIDAD = re.compile(r'integrity="(sha\d+)-([^"]+)"')


def _hash(ruta, algoritmo):
    return base64.b64encode(hashlib.new(algoritmo, ruta.read_bytes()).digest()).decode('ascii')


class LeafletSriTest(unittest.TestCase):

    def test_integrity_coincide_con_el_archivo(self):
        revisadas = 0
        for plantilla in ADDONS.rglob('*.xml'):
            texto = plantilla.read_text(encoding='utf-8')
            for etiqueta in ETIQUETA.finditer(texto):
                integridad = INTEGRIDAD.search(etiqueta.group(0))
                if not integridad:
                    continue
                archivo = LEAFLET / etiqueta.group(1)
                algoritmo, esperado = integridad.groups()
                with self.subTest(plantilla=plantilla.relative_to(RAIZ).as_posix(), archivo=archivo.name):
                    self.assertTrue(archivo.is_file(), 'no existe %s' % archivo)
                    self.assertEqual(_hash(archivo, algoritmo), esperado,
                                     'el hash de %s no coincide: el navegador bloqueara el archivo' % archivo.name)
                revisadas += 1
        self.assertGreater(revisadas, 0, 'no se encontro ninguna plantilla que cargue Leaflet con integrity')


if __name__ == '__main__':
    unittest.main()
