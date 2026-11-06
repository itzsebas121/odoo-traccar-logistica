# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class LogisticaConfiguracion(models.Model):
    _name = 'logistica.configuracion'
    _description = 'Configuración de Logística'

    name = fields.Char(default='Configuración de Logística', readonly=True)
    arrival_radius_m = fields.Integer(string='Radio de llegada (m)', default=50)
    gps_stale_after_seconds = fields.Integer(
        string='GPS desactualizado tras (s)', default=300)
    dispatch_cutoff = fields.Float(
        string='Hora de corte de despacho', default=14.0,
        help='Hora del día (0-24) a partir de la cual los pedidos pasan al siguiente despacho.')
    route_recalculation_policy = fields.Selection(
        [('solo_pendientes', 'Recalcular solo paradas pendientes')],
        string='Política de recálculo de ruta', default='solo_pendientes', required=True)

    @api.constrains('arrival_radius_m', 'gps_stale_after_seconds', 'dispatch_cutoff')
    def _check_valores(self):
        for rec in self:
            if rec.arrival_radius_m <= 0 or rec.gps_stale_after_seconds <= 0:
                raise ValidationError(_('El radio y el tiempo de GPS desactualizado deben ser positivos.'))
            if not 0 <= rec.dispatch_cutoff <= 24:
                raise ValidationError(_('La hora de corte debe estar entre 0 y 24.'))

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
