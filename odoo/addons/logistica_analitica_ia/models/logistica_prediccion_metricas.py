# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models

from ..services import ml_client


class LogisticaPrediccionMetricas(models.TransientModel):
    """Muestra las métricas del modelo (§10.4). Se llenan al abrir la pantalla; no se guarda nada."""
    _name = 'logistica.prediccion.metricas'
    _description = 'Métricas del modelo predictivo'

    model_version = fields.Char(string='Versión del modelo', readonly=True)
    accuracy = fields.Float(string='Exactitud (accuracy)', digits=(10, 4), readonly=True)
    precision_macro = fields.Float(string='Precisión (macro)', digits=(10, 4), readonly=True)
    recall_macro = fields.Float(string='Recall (macro)', digits=(10, 4), readonly=True)
    f1_macro = fields.Float(string='F1 (macro)', digits=(10, 4), readonly=True)
    baseline_accuracy = fields.Float(string='Exactitud del predictor base', digits=(10, 4), readonly=True)
    baseline_f1 = fields.Float(string='F1 del predictor base', digits=(10, 4), readonly=True)
    n_train = fields.Integer(string='Viajes de entrenamiento', readonly=True)
    n_test = fields.Integer(string='Viajes de prueba', readonly=True)
    split_date = fields.Char(string='Fecha de corte', readonly=True)
    confusion_html = fields.Html(string='Matriz de confusión', readonly=True, sanitize=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        datos = ml_client.metrics(self.env)
        for campo in ('model_version', 'accuracy', 'precision_macro', 'recall_macro', 'f1_macro',
                      'baseline_accuracy', 'baseline_f1', 'n_train', 'n_test'):
            if campo in datos:
                res[campo] = datos[campo]
        res['split_date'] = str(datos.get('split_date') or '')
        res['confusion_html'] = self._matriz_html(datos.get('labels') or [], datos.get('confusion_matrix') or [])
        return res

    @api.model
    def _matriz_html(self, etiquetas, matriz):
        if not etiquetas or not matriz:
            return Markup('<p>Sin matriz de confusión.</p>')
        cabecera = Markup('').join(Markup('<th>%s</th>') % e for e in etiquetas)
        filas = Markup('').join(
            Markup('<tr><th>%s</th>%s</tr>') % (
                etiquetas[i] if i < len(etiquetas) else i,
                Markup('').join(Markup('<td style="text-align:right">%s</td>') % v for v in fila))
            for i, fila in enumerate(matriz))
        return Markup(
            '<p>Filas: zona real. Columnas: zona predicha.</p>'
            '<table class="table table-sm"><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table>') % (
            cabecera, filas)
