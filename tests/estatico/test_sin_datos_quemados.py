# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from tests.estatico.escaneo import Hallazgo, escanear

# El borrado de este archivo sigue pendiente de aprobación: tiene marca, modelo
# y una contraseña fija. El escaneo lo señala, y el resto del repo debe estar limpio.
EXCEPCION_CONOCIDA = 'scripts/verify_integration.py'


class EscaneoEstaticoTest(unittest.TestCase):

    def test_repo_sin_datos_quemados_fuera_de_la_excepcion(self):
        hallazgos = [h for h in escanear() if h.ruta != EXCEPCION_CONOCIDA]
        self.assertEqual(
            hallazgos, [],
            'Hay datos de negocio o un literal de password fuera de seeds/data y .env')

    def test_la_excepcion_conocida_sigue_teniendo_datos_quemados(self):
        hallazgos = [h for h in escanear() if h.ruta == EXCEPCION_CONOCIDA]
        self.assertTrue(
            hallazgos,
            'scripts/verify_integration.py ya no tiene datos quemados; quite EXCEPCION_CONOCIDA')

    def test_detecta_token_y_password_sin_revelar_el_secreto(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            datos = raiz / 'seeds' / 'data'
            datos.mkdir(parents=True)
            (datos / 'odoo.json').write_text(json.dumps({
                'marca': 'MarcaUnicaFase1',
                'vehiculos': [{'uniqueId': 'GPS-UNICO-0001'}],
            }), encoding='utf-8')
            (raiz / '.env.example').write_text('ODOO_PASSWORD=secreto-de-prueba-x\n', encoding='utf-8')
            codigo = raiz / 'app.py'
            campo = 'pass' + 'word'
            codigo.write_text(
                "uid = 'GPS-UNICO-0001'\n"
                "clave = {'%s': 'otra-clave-larga'}\n"
                "copia = 'secreto-de-prueba-x'\n" % campo,
                encoding='utf-8')
            (datos / 'copia.py').write_text('GPS-UNICO-0001', encoding='utf-8')
            hallazgos = escanear(raiz)
        rutas = {h.ruta for h in hallazgos}
        self.assertIn('app.py', rutas)
        self.assertNotIn('seeds/data/copia.py', rutas)
        self.assertNotIn('secreto-de-prueba-x', repr(hallazgos))
        self.assertNotIn('otra-clave-larga', repr(hallazgos))
        self.assertIn(Hallazgo('app.py', 'GPS-UNICO-0001'), hallazgos)
        self.assertIn(Hallazgo('app.py', 'literal de password'), hallazgos)
        self.assertIn(Hallazgo('app.py', 'valor secreto de .env'), hallazgos)


if __name__ == '__main__':
    unittest.main()
