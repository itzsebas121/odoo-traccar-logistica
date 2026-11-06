# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestDeviceLink(TransactionCase):
    """Un dispositivo GPS Traccar solo puede estar vinculado a un vehículo (§6.2)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'MarcaTest'})
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'ModeloTest', 'brand_id': brand.id})
        server = cls.env['traccar.server'].create({
            'name': 'S', 'base_url': 'http://traccar:8082',
            'username': 'u', 'password': 'p'})
        cls.dev = cls.env['traccar.device'].create({
            'name': 'D', 'unique_id': 'UID1', 'traccar_id': 1,
            'server_id': server.id})

    def _vehiculo(self, placa, **vals):
        return self.env['fleet.vehicle'].create(dict(
            model_id=self.model.id, license_plate=placa, **vals))

    def test_dispositivo_no_compartido(self):
        self._vehiculo('AAA-0001', traccar_device_id=self.dev.id)
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._vehiculo('AAA-0002', traccar_device_id=self.dev.id)
        # varios vehículos sin dispositivo siguen siendo válidos
        self._vehiculo('AAA-0003')
        self._vehiculo('AAA-0004')
