# -*- coding: utf-8 -*-
"""Flujo de punta a punta contra el stack vivo.

Se omite solo si faltan variables de entorno: no hay credenciales en este archivo.
La sincronización entra por action_sincronizar_ahora (sincronizar_todo es privado).
Los reinicios de contenedor piden E2E_REINICIO=1 para no tumbar el stack de desarrollo
en cada corrida.
"""
import json
import os
import subprocess
import sys
import time
import unittest
import xmlrpc.client
from pathlib import Path

from seeds import schema

RAIZ = Path(__file__).resolve().parents[2]
VARIABLES = (
    'ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD',
    'TRACCAR_URL', 'TRACCAR_OSMAND_URL',
)


def _faltan():
    return [nombre for nombre in VARIABLES if not os.environ.get(nombre, '').strip()]


class FlujoE2ETest(unittest.TestCase):

    def setUp(self):
        faltan = _faltan()
        if faltan:
            self.skipTest(
                'E2E omitido; faltan variables (no se muestran valores): ' + ', '.join(faltan))

    def test_seed_idempotente(self):
        self._script('seeds/seed.py')
        segundo = json.loads(self._script('seeds/seed.py'))
        self.assertEqual(segundo['creados'], [])

    def test_posicion_en_odoo_vehiculo_correcto(self):
        self._script('seeds/seed.py')
        self._script('seeds/simular.py')
        self._sincronizar()
        db, uid, clave, modelos = self._odoo()
        vehiculos = modelos.execute_kw(
            db, uid, clave, 'fleet.vehicle', 'search_read',
            [[]], {'fields': ['license_plate', 'id'], 'limit': 0})
        self.assertTrue(vehiculos)
        posiciones = modelos.execute_kw(
            db, uid, clave, 'logistica.traccar.posicion', 'search_read',
            [[]], {'fields': ['vehicle_id', 'traccar_position_id'], 'limit': 0})
        self.assertTrue(posiciones, 'no hay posiciones en Odoo tras sincronizar')
        ids_vehiculo = {v['id'] for v in vehiculos}
        self.assertTrue(all(p['vehicle_id'] and p['vehicle_id'][0] in ids_vehiculo for p in posiciones))
        ids_posicion = [p['traccar_position_id'] for p in posiciones]
        self.assertEqual(len(ids_posicion), len(set(ids_posicion)))

    def test_evento_overspeed_y_geocerca_en_odoo(self):
        self._script('seeds/seed.py')
        self._script('seeds/simular.py')
        # Traccar guarda la posicion antes de generar sus eventos: se reintenta la sincronizacion hasta un tope.
        esperados = {'deviceOverspeed', 'geofenceEnter'}
        tipos = set()
        limite = time.time() + 90
        while time.time() < limite:
            self._sincronizar()
            db, uid, clave, modelos = self._odoo()
            eventos = modelos.execute_kw(
                db, uid, clave, 'logistica.traccar.evento', 'search_read',
                [[]], {'fields': ['event_type'], 'limit': 0})
            tipos = {e['event_type'] for e in eventos}
            if esperados <= tipos:
                break
            time.sleep(5)
        self.assertIn('deviceOverspeed', tipos)
        self.assertIn('geofenceEnter', tipos)

    def test_datos_demo_en_odoo_sin_duplicados(self):
        self._script('seeds/seed.py')
        self._script('seeds/seed.py')
        odoo, traccar, simulacion = schema.cargar()
        db, uid, clave, modelos = self._odoo()

        def contar(modelo, dominio):
            return modelos.execute_kw(db, uid, clave, modelo, 'search_count', [dominio])

        self.assertEqual(contar('logistica.bodega', [('active', '=', True)]), 1)
        for vehiculo in odoo['vehiculos']:
            self.assertEqual(contar('fleet.vehicle', [
                ('license_plate', '=', vehiculo['license_plate']), ('driver_id', '!=', False),
                ('traccar_device_id.unique_id', '=', vehiculo['uniqueId'])]), 1, vehiculo['license_plate'])
        for producto in odoo['productos']:
            self.assertEqual(contar('product.template', [
                ('name', '=', producto['name']), ('website_published', '=', True)]), 1, producto['name'])
        for pedido in simulacion['pedidos']:
            self.assertEqual(contar('sale.order', [
                ('client_order_ref', '=', pedido['ref']), ('state', '=', 'sale')]), 1, pedido['ref'])
            self.assertEqual(contar('logistica.entrega', [
                ('sale_order_id.client_order_ref', '=', pedido['ref'])]), 1, pedido['ref'])
        for usuario in odoo['usuarios_conductor']:
            self.assertEqual(contar('res.users', [
                ('login', '=', usuario['login']),
                ('groups_id', 'in', [modelos.execute_kw(
                    db, uid, clave, 'ir.model.data', 'check_object_reference',
                    ['logistica_conductor', 'group_conductor'])[1]])]), 1, usuario['login'])
            self.assertEqual(contar('res.partner', [
                ('name', '=', usuario['conductor']), ('is_driver', '=', True)]), 1, usuario['conductor'])

    def test_posiciones_de_los_tres_vehiculos(self):
        odoo, _traccar, _simulacion = schema.cargar()
        self._script('seeds/seed.py')
        self._script('seeds/simular.py')
        db, uid, clave, modelos = self._odoo()
        placas = [v['license_plate'] for v in odoo['vehiculos']]
        limite = time.time() + 90
        faltan = list(placas)
        while faltan and time.time() < limite:
            self._sincronizar()
            faltan = [placa for placa in placas if not modelos.execute_kw(
                db, uid, clave, 'logistica.traccar.posicion', 'search_count',
                [[('vehicle_id.license_plate', '=', placa)]])]
            if faltan:
                time.sleep(4)
        self.assertFalse(faltan, 'sin posiciones en Odoo para: %s' % ', '.join(faltan))

    def test_reinicio_traccar_sin_perdidas(self):
        self._exigir_reinicio()
        antes = self._contar('logistica.traccar.posicion')
        self._reiniciar('traccar')
        self._script('seeds/simular.py')
        self._sincronizar()
        self.assertGreaterEqual(self._contar('logistica.traccar.posicion'), antes)

    def test_reinicio_odoo_sin_perdidas(self):
        self._exigir_reinicio()
        antes = self._contar('logistica.traccar.posicion')
        self._reiniciar('odoo')
        self._sincronizar()
        self.assertGreaterEqual(self._contar('logistica.traccar.posicion'), antes)

    def _exigir_reinicio(self):
        if os.environ.get('E2E_REINICIO', '').strip() != '1':
            self.skipTest('Reinicio de contenedores desactivado. Defina E2E_REINICIO=1 para correrlo.')

    def _script(self, script):
        proceso = subprocess.run(
            [sys.executable, script], cwd=str(RAIZ), capture_output=True, text=True,
            env=os.environ.copy())
        self.assertEqual(
            proceso.returncode, 0,
            'fallo %s\n%s' % (script, proceso.stderr[-2000:]))
        return proceso.stdout

    def _odoo(self):
        url = os.environ['ODOO_URL'].rstrip('/')
        db = os.environ['ODOO_DB']
        usuario = os.environ['ODOO_USER']
        clave = os.environ['ODOO_PASSWORD']
        comun = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common', allow_none=True)
        uid = comun.authenticate(db, usuario, clave, {})
        self.assertTrue(uid, 'autenticacion de Odoo fallida')
        modelos = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object', allow_none=True)
        self._asegurar_gestor(db, uid, clave, modelos)
        return db, uid, clave, modelos

    def _asegurar_gestor(self, db, uid, clave, modelos):
        """action_sincronizar_ahora solo lo acepta un gestor de flota."""
        dato = modelos.execute_kw(
            db, uid, clave, 'ir.model.data', 'search_read',
            [[('module', '=', 'fleet'), ('name', '=', 'fleet_group_manager')]],
            {'fields': ['res_id'], 'limit': 1})
        self.assertTrue(dato, 'no existe el grupo fleet.fleet_group_manager')
        grupo = dato[0]['res_id']
        grupos = modelos.execute_kw(
            db, uid, clave, 'res.users', 'read', [[uid], ['groups_id']])[0]['groups_id']
        if grupo not in grupos:
            modelos.execute_kw(
                db, uid, clave, 'res.users', 'write', [[uid], {'groups_id': [(4, grupo)]}])

    def _sincronizar(self):
        db, uid, clave, modelos = self._odoo()
        servidores = modelos.execute_kw(
            db, uid, clave, 'traccar.server', 'search', [[]], {'limit': 1})
        self.assertTrue(servidores, 'no hay traccar.server; corra seeds/seed.py')
        modelos.execute_kw(
            db, uid, clave, 'traccar.server', 'action_sincronizar_ahora', [servidores])

    def _contar(self, modelo):
        db, uid, clave, modelos = self._odoo()
        return modelos.execute_kw(db, uid, clave, modelo, 'search_count', [[]])

    def _reiniciar(self, servicio):
        proceso = subprocess.run(
            ['docker', 'compose', 'restart', servicio], cwd=str(RAIZ),
            capture_output=True, text=True)
        self.assertEqual(proceso.returncode, 0, proceso.stderr[-1000:])
        limite = time.time() + 180
        while time.time() < limite:
            estado = subprocess.run(
                ['docker', 'compose', 'ps', '--format', '{{.Service}} {{.Health}}'],
                cwd=str(RAIZ), capture_output=True, text=True)
            for linea in estado.stdout.splitlines():
                if linea.strip() == '%s healthy' % servicio:
                    return
            time.sleep(3)
        self.fail('el servicio %s no quedo healthy' % servicio)


if __name__ == '__main__':
    unittest.main()
