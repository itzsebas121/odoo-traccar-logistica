# -*- coding: utf-8 -*-
import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from ..services import routing_client
from .logistica_ruta import ESTADOS_ACTIVOS


def _coordenadas_validas(lat, lon):
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if math.isnan(lat) or math.isnan(lon):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)


class LogisticaPlanificador(models.TransientModel):
    _name = 'logistica.planificador'
    _description = 'Planificador de despacho'

    date = fields.Date(string='Fecha de despacho', required=True, default=fields.Date.context_today)
    bodega_id = fields.Many2one(
        'logistica.bodega', string='Bodega de salida',
        default=lambda self: self.env['logistica.bodega'].get_bodega_activa().id)
    vehicle_ids = fields.Many2many(
        'fleet.vehicle', 'logistica_planificador_vehicle_rel', 'planificador_id', 'vehicle_id',
        string='Vehículos', help='Vacío = todos los vehículos con conductor.')
    time_limit_s = fields.Integer(string='Tiempo máximo del optimizador (s)', default=5)

    def _entregas_candidatas(self):
        """Entregas preparadas, con destino válido y sin ruta activa (§1.1 reglas 5 a 7)."""
        en_ruta = self.env['logistica.ruta.parada'].sudo().search([
            ('route_id.state', 'in', ESTADOS_ACTIVOS)]).mapped('entrega_id').ids
        entregas = self.env['logistica.entrega'].search([
            ('state', '=', 'preparado'), ('id', 'not in', en_ruta)], order='id')
        return entregas.filtered(lambda e: _coordenadas_validas(e.latitude, e.longitude))

    def _vehiculos_disponibles(self):
        vehiculos = self.vehicle_ids or self.env['fleet.vehicle'].search([('driver_id', '!=', False)])
        ocupados = self.env['logistica.ruta'].sudo().search([
            ('date', '=', self.date), ('state', 'in', ESTADOS_ACTIVOS)]).mapped('vehicle_id').ids
        return vehiculos.filtered(lambda v: v.driver_id and v.id not in ocupados)

    def action_proponer(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('fleet.fleet_group_manager')):
            raise AccessError(_('Solo un gestor de flota puede planificar el despacho.'))
        bodega = self.bodega_id or self.env['logistica.bodega'].get_bodega_activa()
        if not bodega:
            raise UserError(_('No hay una bodega activa configurada.'))
        vehiculos = self._vehiculos_disponibles()
        if not vehiculos:
            raise UserError(_(
                'No hay vehículos con conductor disponibles para el %s.') % self.date)
        entregas = self._entregas_candidatas()
        if not entregas:
            raise UserError(_('No hay entregas preparadas para despachar.'))

        payload = {
            'depot': {'lat': bodega.latitude, 'lon': bodega.longitude},
            'stops': [{'id': e.id, 'lat': e.latitude, 'lon': e.longitude, 'demand': 1}
                      for e in entregas],
            'vehicles': [{'id': v.id, 'capacity': max(v.logistica_capacidad, 0)} for v in vehiculos],
            'time_limit_s': max(self.time_limit_s or 5, 1),
        }
        resultado = routing_client.optimize(self.env, payload)

        entregas_por_id = {e.id: e for e in entregas}
        vehiculos_por_id = {v.id: v for v in vehiculos}
        Ruta = self.env['logistica.ruta']
        creadas = Ruta
        for ruta_api in resultado.get('routes') or []:
            vehiculo = vehiculos_por_id.get(ruta_api.get('vehicle_id'))
            paradas = sorted(
                (p for p in ruta_api.get('stops') or [] if p.get('id') in entregas_por_id),
                key=lambda p: p.get('sequence') or 0)
            if not vehiculo or not paradas:
                continue
            creadas |= Ruta.create({
                'date': self.date,
                'bodega_id': bodega.id,
                'vehicle_id': vehiculo.id,
                'driver_id': vehiculo.driver_id.id,
                'planned_distance_km': ruta_api.get('distance_km') or 0.0,
                'planned_duration_min': ruta_api.get('duration_min') or 0.0,
                'optimization_version': resultado.get('optimization_version'),
                'distance_source': resultado.get('source'),
                'stop_ids': [(0, 0, {'entrega_id': p['id'], 'sequence': p.get('sequence') or 0})
                             for p in paradas],
            })
        for item in resultado.get('unassigned') or []:
            entrega = entregas_por_id.get(item.get('id'))
            if entrega:
                entrega._registrar_evento('no_asignado', notes=item.get('reason') or 'sin_ruta')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rutas propuestas'),
            'res_model': 'logistica.ruta',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', creadas.ids)],
        }
