# -*- coding: utf-8 -*-
import json

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.logistica_base.models.logistica_zona import ZONA_CODES

ETIQUETAS_ZONA = dict(ZONA_CODES)


def etiqueta_zona(codigo):
    return ETIQUETAS_ZONA.get(codigo, codigo)


class LogisticaPrediccionConsulta(models.Model):
    """Auditoría de cada consulta al modelo predictivo (§5 M7). Solo se inserta."""
    _name = 'logistica.prediccion.consulta'
    _description = 'Consulta de destino probable'
    _order = 'id desc'

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehículo', required=True, ondelete='restrict')
    reference_datetime = fields.Datetime(string='Fecha y hora de referencia (UTC)', required=True)
    origin_zone = fields.Selection(ZONA_CODES, string='Zona de origen')
    predicted_zone = fields.Char(string='Destino probable')
    class_probabilities = fields.Text(string='Probabilidades (JSON)')
    alternatives = fields.Text(string='Alternativas (JSON)')
    model_version = fields.Char(string='Versión del modelo')
    route_geometry = fields.Text(string='Geometría de la ruta (JSON)')
    route_distance_km = fields.Float(string='Distancia (km)', digits=(10, 2))
    route_duration_min = fields.Float(string='Duración (min)', digits=(10, 1))
    route_source = fields.Char(
        string='Fuente de la ruta',
        help='osrm: por carretera. estimado_haversine: estimación en línea recta, no es una ruta real.')
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user, readonly=True)
    created_at = fields.Datetime(string='Consultado el', default=fields.Datetime.now, readonly=True)
    resultado_html = fields.Html(string='Resultado', compute='_compute_resultado_html', sanitize=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('origin_zone'):
                raise ValidationError(_('La zona de origen es obligatoria.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Las consultas del modelo predictivo son un registro de auditoría y no se pueden modificar.'))

    def unlink(self):
        if not self.env.context.get('module_uninstall'):
            raise UserError(_('Las consultas del modelo predictivo son un registro de auditoría y no se pueden eliminar.'))
        return super().unlink()

    def name_get(self):
        return [(rec.id, '%s → %s' % (
            rec.vehicle_id.license_plate or rec.vehicle_id.display_name,
            etiqueta_zona(rec.predicted_zone) or '?')) for rec in self]

    def _probabilidades(self):
        self.ensure_one()
        try:
            return json.loads(self.class_probabilities or '{}')
        except ValueError:
            return {}

    def _alternativas(self):
        self.ensure_one()
        try:
            return json.loads(self.alternatives or '[]')
        except ValueError:
            return []

    @api.depends('class_probabilities', 'alternatives', 'predicted_zone',
                 'route_distance_km', 'route_source')
    def _compute_resultado_html(self):
        for rec in self:
            filas = Markup('').join(
                Markup('<tr><td>%s</td><td style="text-align:right">%s</td></tr>') % (
                    etiqueta_zona(zona), '%.1f %%' % (prob * 100))
                for zona, prob in sorted(rec._probabilidades().items(), key=lambda t: -t[1]))
            alternativas = Markup(', ').join(
                Markup('%s (%s)') % (etiqueta_zona(a.get('zone')), '%.1f %%' % (a.get('probability', 0) * 100))
                for a in rec._alternativas())
            ruta = Markup('')
            if rec.route_source:
                ruta = Markup('<p>Ruta sugerida: <strong>%s km</strong>, %s min (fuente: %s)</p>') % (
                    '%.2f' % rec.route_distance_km, '%.0f' % rec.route_duration_min, rec.route_source)
                if rec.route_source == 'estimado_haversine':
                    ruta += Markup('<p><em>Es una estimación en línea recta, no una ruta por carretera.</em></p>')
            rec.resultado_html = Markup(
                '<h3>Destino probable: %s</h3><p>Alternativas: %s</p>'
                '<table class="table table-sm" style="max-width:420px"><thead><tr><th>Zona</th>'
                '<th style="text-align:right">Probabilidad</th></tr></thead><tbody>%s</tbody></table>%s') % (
                etiqueta_zona(rec.predicted_zone), alternativas or '—', filas, ruta)

    def action_ver_mapa(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/logistica/prediccion/%s/mapa' % self.id, 'target': 'new'}
