# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from ..models.logistica_traccar_util import knots_to_kmh, meters_to_km, valid_latlon


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestUtilTraccar(TransactionCase):
    """Conversiones puras usadas por el conector y el cron de sincronización."""

    def test_knots_to_kmh(self):
        self.assertEqual(knots_to_kmh(10), 18.52)
        self.assertEqual(knots_to_kmh(0), 0.0)
        self.assertEqual(knots_to_kmh(1), 1.85)  # redondeo a 2 decimales

    def test_valid_latlon_rechaza_origen_nulo(self):
        self.assertIs(valid_latlon(0, 0), False)

    def test_valid_latlon_rechaza_fuera_de_rango(self):
        self.assertIs(valid_latlon(95, 0), False)
        self.assertIs(valid_latlon(-90.5, 10), False)
        self.assertIs(valid_latlon(10, 180.5), False)
        self.assertIs(valid_latlon(10, -181), False)

    def test_valid_latlon_rechaza_none(self):
        self.assertIs(valid_latlon(None, -78.6), False)
        self.assertIs(valid_latlon(-1.2, None), False)

    def test_valid_latlon_acepta_limites_y_coordenadas_normales(self):
        self.assertIs(valid_latlon(90, 180), True)
        self.assertIs(valid_latlon(-90, -180), True)
        self.assertIs(valid_latlon(45.0, -120.0), True)
        self.assertIs(valid_latlon(0, 10), True)  # solo uno de los dos en cero

    def test_meters_to_km(self):
        self.assertEqual(meters_to_km(1500), 1.5)
        self.assertEqual(meters_to_km(0), 0.0)


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestModelosPosicionEvento(TransactionCase):
    """Posiciones y eventos GPS: claves únicas por id de Traccar y borrado en cascada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env['traccar.server'].create({'name': 'Servidor de prueba'})
        cls.device = cls.env['traccar.device'].create({
            'name': 'Dispositivo de prueba',
            'unique_id': 'TEST-MODELOS-1',
            'traccar_id': 501,
            'server_id': server.id,
        })

    def _posicion(self, traccar_position_id, device=None, **vals):
        return self.env['logistica.traccar.posicion'].create(dict({
            'device_id': (device or self.device).id,
            'traccar_position_id': traccar_position_id,
            'fix_time': '2026-11-06 12:00:00',
            'latitude': 45.0,
            'longitude': -120.0,
            'speed_kmh': 18.52,
            'odometer_km': 12.5,
            'valid': True,
        }, **vals))

    def _evento(self, traccar_event_id, **vals):
        return self.env['logistica.traccar.evento'].create(dict({
            'device_id': self.device.id,
            'traccar_event_id': traccar_event_id,
            'event_type': 'geofenceEnter',
            'event_time': '2026-11-06 12:00:00',
            'geofence_traccar_id': 3,
            'position_traccar_id': 1,
            'attributes': '{"ignition": true}',
        }, **vals))

    def _usuario(self, login, *group_xmlids):
        grupos = [self.env.ref(xmlid).id for xmlid in group_xmlids]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'groups_id': [(6, 0, grupos)],
        })

    def test_dispositivo_nuevo_activo_sin_watermark(self):
        self.assertTrue(self.device.is_active)
        self.assertFalse(self.device.position_watermark)

    def test_campos_obligatorios_rechazan_nulo(self):
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._posicion(traccar_position_id=None)
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._posicion(traccar_position_id=7006, fix_time=None)
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._evento(traccar_event_id=None)

    def test_usuario_interno_no_escribe_watermark_ni_activo(self):
        user = self._usuario('usuario-interno-device', 'base.group_user')
        device = self.device.with_user(user)
        with self.assertRaises(AccessError):
            device.write({'position_watermark': '2026-11-06 12:00:00'})
        with self.assertRaises(AccessError):
            device.write({'is_active': False})
        self.assertTrue(self.device.is_active)

    def test_gestor_de_flota_escribe_dispositivo(self):
        manager = self._usuario(
            'gestor-flota-device', 'base.group_user', 'fleet.fleet_group_manager')
        self.device.with_user(manager).write({'name': 'Dispositivo renombrado'})
        self.assertEqual(self.device.name, 'Dispositivo renombrado')

    def test_posicion_guarda_campos(self):
        posicion = self._posicion(traccar_position_id=7001)
        self.assertEqual(posicion.device_id, self.device)
        self.assertEqual(posicion.speed_kmh, 18.52)
        self.assertEqual(posicion.odometer_km, 12.5)
        self.assertTrue(posicion.valid)

    def test_traccar_position_id_unico(self):
        self._posicion(traccar_position_id=7002)
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._posicion(traccar_position_id=7002)

    def test_borrar_dispositivo_borra_sus_posiciones(self):
        server = self.device.server_id
        device = self.env['traccar.device'].create({
            'name': 'Dispositivo temporal',
            'unique_id': 'TEST-MODELOS-2',
            'traccar_id': 502,
            'server_id': server.id,
        })
        posicion = self._posicion(traccar_position_id=7003, device=device)
        device.unlink()
        self.assertFalse(posicion.exists())

    def test_evento_guarda_campos(self):
        evento = self._evento(traccar_event_id=8001)
        self.assertEqual(evento.device_id, self.device)
        self.assertEqual(evento.event_type, 'geofenceEnter')
        self.assertEqual(evento.geofence_traccar_id, 3)
        self.assertEqual(evento.position_traccar_id, 1)
        self.assertEqual(evento.attributes, '{"ignition": true}')

    def test_traccar_event_id_unico(self):
        self._evento(traccar_event_id=8002)
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._evento(traccar_event_id=8002)

    def test_usuario_interno_solo_lee(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Usuario interno de prueba',
            'login': 'usuario-interno-modelos',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        posicion = self._posicion(traccar_position_id=7004)
        evento = self._evento(traccar_event_id=8003)

        posiciones = self.env['logistica.traccar.posicion'].with_user(user)
        eventos = self.env['logistica.traccar.evento'].with_user(user)
        self.assertTrue(posiciones.search([('id', '=', posicion.id)]))
        self.assertTrue(eventos.search([('id', '=', evento.id)]))

        with self.assertRaises(AccessError):
            posiciones.create({
                'device_id': self.device.id,
                'traccar_position_id': 7005,
                'fix_time': '2026-11-06 12:05:00',
            })
        with self.assertRaises(AccessError):
            posicion.with_user(user).write({'speed_kmh': 0.0})
        with self.assertRaises(AccessError):
            evento.with_user(user).write({'event_type': 'otro'})
