# -*- coding: utf-8 -*-
import json
from datetime import date
from unittest import mock

import requests

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

ML = 'odoo.addons.logistica_analitica_ia.services.ml_client'
RUTA = 'odoo.addons.logistica_analitica_ia.services.routing_geometry.route'

PREDICCION = {
    'predicted_zone': 'ficoa',
    'probabilities': {'ficoa': 0.5, 'centro': 0.3, 'huachi': 0.1, 'izamba': 0.06, 'atocha': 0.03, 'otra': 0.01},
    'alternatives': [
        {'zone': 'centro', 'probability': 0.3},
        {'zone': 'huachi', 'probability': 0.1},
        {'zone': 'izamba', 'probability': 0.06}],
    'model_version': 'v-test',
}
GEOMETRIA = {
    'geometry': [[-1.24, -78.61], [-1.23, -78.62], [-1.22, -78.63]],
    'distance_km': 3.4, 'duration_min': 9.0, 'source': 'estimado_haversine',
}


def _respuesta(datos, estado=200):
    resp = mock.Mock(status_code=estado)
    resp.json.return_value = datos
    return resp


@tagged('post_install', '-at_install', 'logistica_analitica_ia')
class TestPrediccion(TransactionCase):

    def setUp(self):
        super().setUp()
        marca = self.env['fleet.vehicle.model.brand'].create({'name': 'MarcaIA'})
        modelo = self.env['fleet.vehicle.model'].create({'name': 'ModeloIA', 'brand_id': marca.id})
        self.vehiculo = self.env['fleet.vehicle'].create({'model_id': modelo.id, 'license_plate': 'IAA-0001'})
        for codigo, nombre, lat, lon in (('centro', 'Centro', -1.2417, -78.6197), ('ficoa', 'Ficoa', -1.2200, -78.6300)):
            if not self.env['logistica.zona'].search([('code', '=', codigo)]):
                self.env['logistica.zona'].create({'code': codigo, 'name': nombre, 'latitude': lat, 'longitude': lon})

    def _wizard(self, **extra):
        valores = {'vehicle_id': self.vehiculo.id, 'fecha': date(2026, 11, 9), 'hora': 8.5, 'origin_zone': 'centro'}
        valores.update(extra)
        return self.env['logistica.prediccion.wizard'].create(valores)

    def _predecir(self, wizard=None):
        wizard = wizard or self._wizard()
        with mock.patch(ML + '.predict', return_value=dict(PREDICCION)) as predict, \
                mock.patch(RUTA, return_value=dict(GEOMETRIA)):
            accion = wizard.action_predecir()
        return accion, predict

    # ----------------------------------------------------------------- pruebas
    def test_consulta_guarda_auditoria(self):
        accion, predict = self._predecir()
        consulta = self.env['logistica.prediccion.consulta'].browse(accion['res_id'])
        self.assertEqual(consulta.predicted_zone, 'ficoa')
        self.assertEqual(consulta.model_version, 'v-test')
        self.assertEqual(consulta.vehicle_id, self.vehiculo)
        self.assertEqual(consulta.origin_zone, 'centro')
        self.assertEqual(consulta.user_id, self.env.user)
        self.assertEqual(len(json.loads(consulta.alternatives)), 3)
        self.assertEqual(json.loads(consulta.class_probabilities)['ficoa'], 0.5)
        payload = predict.call_args.args[1]
        self.assertEqual(payload['vehicle_code'], 'IAA-0001')
        self.assertEqual(payload['origin_zone'], 'centro')
        self.assertTrue(payload['reference_datetime'].endswith('Z'))

    def test_hora_se_envia_en_utc(self):
        self.env.user.tz = 'America/Guayaquil'  # UTC-5
        _accion, predict = self._predecir(self._wizard(hora=8.5))
        self.assertEqual(predict.call_args.args[1]['reference_datetime'], '2026-11-09T13:30:00Z')

    def test_no_asigna_pedidos(self):
        modelos = ('logistica.entrega', 'logistica.ruta', 'logistica.ruta.parada', 'sale.order')
        antes = {m: (self.env[m].search_count([]), sorted(self.env[m].search([]).mapped('write_date')))
                 for m in modelos}
        self._predecir()
        despues = {m: (self.env[m].search_count([]), sorted(self.env[m].search([]).mapped('write_date')))
                   for m in modelos}
        self.assertEqual(antes, despues)

    def test_ml_caido_mensaje_claro(self):
        consultas = self.env['logistica.prediccion.consulta'].search_count([])
        wizard = self._wizard()
        fallos = (
            mock.patch(ML + '.requests.request', side_effect=requests.ConnectionError('sin servicio')),
            mock.patch(ML + '.requests.request', return_value=_respuesta({}, 503)),
        )
        for parche in fallos:
            with parche:
                with self.assertRaises(UserError) as ctx:
                    wizard.action_predecir()
            self.assertIn('El modelo predictivo no está disponible', ctx.exception.args[0])
        self.assertEqual(self.env['logistica.prediccion.consulta'].search_count([]), consultas)

    def test_ruta_sugerida(self):
        accion, _predict = self._predecir()
        consulta = self.env['logistica.prediccion.consulta'].browse(accion['res_id'])
        self.assertEqual(json.loads(consulta.route_geometry), GEOMETRIA['geometry'])
        self.assertEqual(consulta.route_distance_km, 3.4)
        self.assertEqual(consulta.route_source, 'estimado_haversine')
        self.assertIn('3.40', consulta.resultado_html)
        self.assertIn('estimado_haversine', consulta.resultado_html)
        self.assertIn('estimación', consulta.resultado_html)

    def test_sin_ruta_no_bloquea_la_prediccion(self):
        wizard = self._wizard()
        with mock.patch(ML + '.predict', return_value=dict(PREDICCION)), mock.patch(RUTA, return_value=None):
            accion = wizard.action_predecir()
        consulta = self.env['logistica.prediccion.consulta'].browse(accion['res_id'])
        self.assertEqual(consulta.predicted_zone, 'ficoa')
        self.assertEqual(json.loads(consulta.route_geometry), [])
        self.assertFalse(consulta.route_source)

    def test_zona_origen_obligatoria(self):
        with self.assertRaises(ValidationError):
            self._wizard(origin_zone=False).action_predecir()
        with self.assertRaises(ValidationError):
            self.env['logistica.prediccion.consulta'].create({
                'vehicle_id': self.vehiculo.id, 'reference_datetime': '2026-11-09 13:30:00'})

    def test_probabilidades_suman_uno(self):
        accion, _predict = self._predecir()
        consulta = self.env['logistica.prediccion.consulta'].browse(accion['res_id'])
        self.assertAlmostEqual(sum(json.loads(consulta.class_probabilities).values()), 1.0, delta=1e-6)

    def test_consulta_es_auditoria_inmutable(self):
        accion, _predict = self._predecir()
        consulta = self.env['logistica.prediccion.consulta'].browse(accion['res_id'])
        with self.assertRaises(UserError):
            consulta.write({'predicted_zone': 'centro'})
        with self.assertRaises(UserError):
            consulta.unlink()

    def test_vehiculo_sin_placa(self):
        sin_placa = self.env['fleet.vehicle'].create({'model_id': self.vehiculo.model_id.id})
        with self.assertRaises(UserError):
            self._wizard(vehicle_id=sin_placa.id).action_predecir()

    def test_metricas_se_muestran(self):
        datos = {
            'model_version': 'v-test', 'accuracy': 0.764, 'precision_macro': 0.7, 'recall_macro': 0.68,
            'f1_macro': 0.69, 'baseline_accuracy': 0.259, 'baseline_f1': 0.1, 'n_train': 400, 'n_test': 100,
            'split_date': '2026-10-01', 'labels': ['centro', 'ficoa'], 'confusion_matrix': [[40, 10], [8, 42]],
        }
        with mock.patch(ML + '.metrics', return_value=datos):
            valores = self.env['logistica.prediccion.metricas'].default_get(
                ['accuracy', 'baseline_accuracy', 'confusion_html'])
        self.assertEqual(valores['accuracy'], 0.764)
        self.assertEqual(valores['baseline_accuracy'], 0.259)
        self.assertIn('centro', valores['confusion_html'])
        self.assertIn('42', valores['confusion_html'])
