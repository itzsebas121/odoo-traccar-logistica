# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'logistica_base')
class TestLogisticaBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'MarcaTest'})
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'ModeloTest', 'brand_id': brand.id})

    def _vehiculo(self, placa, **vals):
        return self.env['fleet.vehicle'].create(dict(
            model_id=self.model.id, license_plate=placa, **vals))

    def test_bodega_unica_activa(self):
        Bodega = self.env['logistica.bodega']
        activa = Bodega.get_bodega_activa()
        self.assertEqual(len(activa), 1)
        with self.assertRaises(ValidationError):
            Bodega.create({'name': 'Otra', 'latitude': -1.2, 'longitude': -78.6})
        # una inactiva sí se permite
        Bodega.create({'name': 'Otra', 'latitude': -1.2, 'longitude': -78.6,
                       'active': False})

    def test_get_config_conserva_entorno(self):
        Conf = self.env['logistica.configuracion']
        user = self.env['res.users'].create({
            'name': 'Interno', 'login': 'interno_cfg',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.assertFalse(Conf.with_user(user).get_config().env.su)
        self.assertEqual(Conf.with_user(user).get_config().env.uid, user.id)
        self.assertEqual(Conf.sudo().get_config(), Conf.get_config())
        self.assertTrue(Conf.sudo().get_config().env.su)

    def test_configuracion_por_defecto(self):
        conf = self.env['logistica.configuracion'].get_config()
        self.assertEqual(conf.arrival_radius_m, 50)
        self.assertEqual(conf.gps_stale_after_seconds, 300)
        self.assertEqual(conf.route_recalculation_policy, 'solo_pendientes')
        self.assertEqual(self._vehiculo('AAA-0003').logistica_capacidad, 10)
        self.assertEqual(self.env['logistica.configuracion'].get_config(), conf)

    def test_zonas_con_centroide(self):
        Zona = self.env['logistica.zona']
        codes = ['centro', 'ficoa', 'huachi', 'izamba', 'atocha', 'ingahurco', 'otra']
        self.assertEqual(set(Zona.search([]).mapped('code')), set(codes))
        for code in codes:
            lat, lon = Zona.centroide(code)
            self.assertTrue(lat and lon, code)
        self.assertNotEqual(Zona.centroide('centro'), Zona.centroide('ficoa'))

    def test_capacidad_no_negativa(self):
        with self.assertRaises(ValidationError):
            self._vehiculo('AAA-0004', logistica_capacidad=-1)
