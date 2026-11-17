# -*- coding: utf-8 -*-
import math
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

ZONA_HORARIA = 'America/Guayaquil'


def distancia_km(lat1, lon1, lat2, lon2):
    """Distancia en línea recta (haversine) en kilómetros."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((f2 - f1) / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


class LogisticaConfiguracion(models.Model):
    _name = 'logistica.configuracion'
    _description = 'Configuración de Logística'

    name = fields.Char(default='Configuración de Logística', readonly=True)
    arrival_radius_m = fields.Integer(string='Radio de llegada (m)', default=50)
    gps_stale_after_seconds = fields.Integer(
        string='GPS desactualizado tras (s)', default=300)
    dispatch_cutoff = fields.Float(
        string='Hora de corte de despacho', default=14.0,
        help='Hora del día (0-24). Los pedidos confirmados hoy después de esta hora se despachan al día siguiente.')
    route_recalculation_policy = fields.Selection(
        [('solo_pendientes', 'Recalcular solo paradas pendientes')],
        string='Política de recálculo de ruta', default='solo_pendientes', required=True)
    require_preparation = fields.Boolean(
        string='Los pedidos se preparan en bodega antes de despachar', default=False,
        help='Desactivado: cada pedido confirmado queda listo para despachar. Activado: alguien debe marcarlo '
             '«Preparado» (de uno en uno o en lote desde la lista de entregas).')
    coverage_radius_km = fields.Float(
        string='Radio de cobertura desde la bodega (km)', default=0.0,
        help='Entregas solo dentro de este radio en línea recta desde la bodega activa. 0 = sin límite por radio.')
    max_delivery_attempts = fields.Integer(
        string='Intentos de entrega antes de pedir atención', default=2,
        help='Una entrega fallida vuelve sola a «Por despachar» hasta este número de intentos. '
             'Con «Dirección incorrecta» siempre pasa a «Requiere atención». 0 = siempre decide el administrador.')

    @api.constrains('arrival_radius_m', 'gps_stale_after_seconds', 'dispatch_cutoff', 'coverage_radius_km',
                    'max_delivery_attempts')
    def _check_valores(self):
        for rec in self:
            if rec.arrival_radius_m <= 0 or rec.gps_stale_after_seconds <= 0:
                raise ValidationError(_('El radio y el tiempo de GPS desactualizado deben ser positivos.'))
            if not 0 <= rec.dispatch_cutoff <= 24:
                raise ValidationError(_('La hora de corte debe estar entre 0 y 24.'))
            if rec.coverage_radius_km < 0 or rec.max_delivery_attempts < 0:
                raise ValidationError(_('El radio de cobertura y los intentos no pueden ser negativos.'))

    @api.model
    def get_config(self):
        conf = self.search([], limit=1)
        if not conf:
            conf = self.sudo().create({})
        return self.browse(conf.id)

    @api.model_create_multi
    def create(self, vals_list):
        if self.search_count([]) or len(vals_list) > 1:
            raise ValidationError(_('Solo puede existir una configuración de logística.'))
        return super().create(vals_list)

    def unlink(self):
        raise ValidationError(_('La configuración de logística no se puede eliminar.'))

    # ------------------------------------------------------------------
    # Reglas compartidas por checkout, pedidos y despacho
    # ------------------------------------------------------------------
    def distancia_a_bodega_km(self, lat, lon):
        """Km desde la bodega activa, o None si no hay bodega con coordenadas."""
        bodega = self.env['logistica.bodega'].sudo().get_bodega_activa()
        if not bodega or not (bodega.latitude or bodega.longitude):
            return None
        return distancia_km(bodega.latitude, bodega.longitude, lat, lon)

    def fuera_de_radio(self, lat, lon):
        """Mensaje de error si el punto supera el radio de cobertura; False si está dentro o no hay radio."""
        self.ensure_one()
        if not self.coverage_radius_km:
            return False
        distancia = self.distancia_a_bodega_km(lat, lon)
        if distancia is not None and distancia > self.coverage_radius_km:
            return _('La ubicación de entrega queda a %(d).1f km de la bodega; la cobertura llega a %(r).1f km.') % {
                'd': distancia, 'r': self.coverage_radius_km}
        return False

    def inicio_corte_utc(self, dia):
        """Momento (UTC, sin zona) de la hora de corte del día dado, en hora de Ecuador."""
        self.ensure_one()
        horas = int(self.dispatch_cutoff)
        minutos = int(round((self.dispatch_cutoff - horas) * 60))
        local = pytz.timezone(ZONA_HORARIA).localize(datetime.combine(dia, time(min(horas, 23), minutos)))
        if horas >= 24:
            local += timedelta(hours=1)
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def hoy_local(self):
        return datetime.now(pytz.timezone(ZONA_HORARIA)).date()
