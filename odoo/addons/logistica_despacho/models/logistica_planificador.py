# -*- coding: utf-8 -*-
import math

from markupsafe import Markup, escape

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
        string='Vehículos', help='Vacío = todos los vehículos con conductor que no tengan ya una ruta ese día.')
    entrega_ids = fields.Many2many(
        'logistica.entrega', 'logistica_planificador_entrega_rel', 'planificador_id', 'entrega_id',
        string='Pedidos / Entregas',
        help='Vacío = todas las entregas listas para salir. Seleccione solo si desea limitar la ruta a pedidos específicos.')
    time_limit_s = fields.Integer(string='Tiempo máximo del optimizador (s)', default=5)
    resumen = fields.Html(string='Resumen', compute='_compute_resumen', sanitize=False)

    # ------------------------------------------------------------------ evaluación
    def _evaluar(self):
        """Clasifica las entregas por despachar: (listas, [(entrega, motivo), ...]) — nada queda fuera en silencio."""
        self.ensure_one()
        config = self.env['logistica.configuracion'].sudo().get_config()
        en_ruta = self.env['logistica.ruta.parada'].sudo().search([
            ('route_id.state', 'in', ESTADOS_ACTIVOS)]).mapped('entrega_id').ids
        candidatas = self.env['logistica.entrega'].search([
            ('estado_simple', '=', 'por_despachar'), ('id', 'not in', en_ruta)], order='id')
        if self.entrega_ids:
            candidatas &= self.entrega_ids
        corte = None
        if self.date == config.hoy_local():
            corte = config.inicio_corte_utc(self.date)
        listas = self.env['logistica.entrega']
        excluidas = []
        for entrega in candidatas:
            if entrega.state != 'preparado':
                excluidas.append((entrega, _('esperando preparación en bodega')))
            elif not _coordenadas_validas(entrega.latitude, entrega.longitude):
                excluidas.append((entrega, _('sin ubicación válida en el mapa')))
            elif config.fuera_de_radio(entrega.latitude, entrega.longitude):
                excluidas.append((entrega, _('fuera de la cobertura')))
            elif corte and entrega.sale_order_id.date_order and entrega.sale_order_id.date_order > corte:
                excluidas.append((entrega, _('confirmado después de la hora de corte: sale mañana')))
            else:
                listas |= entrega
        return listas, excluidas

    def _entregas_candidatas(self):
        """Entregas preparadas, con destino válido, en cobertura y sin ruta activa (§1.1 reglas 5 a 7)."""
        return self._evaluar()[0]

    def _vehiculos_disponibles(self):
        vehiculos = self.vehicle_ids or self.env['fleet.vehicle'].search([('driver_id', '!=', False)])
        ocupados = self.env['logistica.ruta'].sudo().search([
            ('date', '=', self.date), ('state', 'in', ESTADOS_ACTIVOS)]).mapped('vehicle_id').ids
        return vehiculos.filtered(lambda v: v.driver_id and v.id not in ocupados)

    @api.depends('date', 'vehicle_ids', 'entrega_ids')
    def _compute_resumen(self):
        for wiz in self:
            listas, excluidas = wiz._evaluar()
            vehiculos = wiz._vehiculos_disponibles()
            capacidad = sum(max(v.logistica_capacidad, 0) for v in vehiculos)
            partes = [Markup('<div class="o_logistica_resumen">'),
                      Markup('<p><b>%s</b> entregas listas para salir · <b>%s</b> vehículos con conductor '
                             '(capacidad %s)</p>') % (len(listas), len(vehiculos), capacidad)]
            if listas and capacidad < len(listas):
                partes.append(Markup('<p class="text-warning">%s</p>') % _(
                    'La capacidad no alcanza para todas: las que sobren quedarán para el siguiente despacho.'))
            if excluidas:
                partes.append(Markup('<p class="text-danger mb-1"><b>%s</b></p>') % _(
                    'No saldrán en este despacho:'))
                partes.append(Markup('<ul class="mb-0">'))
                for entrega, motivo in excluidas[:30]:
                    partes.append(Markup('<li>%s — %s</li>') % (
                        escape(entrega.sale_order_id.name or entrega.name), escape(motivo)))
                if len(excluidas) > 30:
                    partes.append(Markup('<li>… %s más</li>') % (len(excluidas) - 30))
                partes.append(Markup('</ul>'))
            partes.append(Markup('</div>'))
            wiz.resumen = Markup('').join(partes)

    # ------------------------------------------------------------------ propuesta
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
        entregas, excluidas = self._evaluar()
        if not entregas:
            detalle = ''.join('\n• %s: %s' % (e.sale_order_id.name or e.name, m) for e, m in excluidas[:15])
            raise UserError(_('No hay entregas listas para despachar.') + detalle)

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
        sin_ruta = []
        for item in resultado.get('unassigned') or []:
            entrega = entregas_por_id.get(item.get('id'))
            if entrega:
                entrega._registrar_evento('no_asignado', notes=item.get('reason') or 'sin_ruta')
                sin_ruta.append(entrega.sale_order_id.name or entrega.name)

        accion_rutas = {
            'type': 'ir.actions.act_window',
            'name': _('Rutas propuestas'),
            'res_model': 'logistica.ruta',
            'view_mode': 'tree,form',
            'views': [[False, 'tree'], [False, 'form']],
            'domain': [('id', 'in', creadas.ids)],
            'context': {'logistica_rutas_propuestas': True},
        }
        avisos = []
        if sin_ruta:
            avisos.append(_('%(n)d sin lugar en los vehículos (quedan para el siguiente despacho): %(l)s') % {
                'n': len(sin_ruta), 'l': ', '.join(sin_ruta[:8])})
        if excluidas:
            avisos.append(_('%d no salen hoy; revise el resumen del planificador.') % len(excluidas))
        if not avisos:
            return accion_rutas
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('%(r)d rutas propuestas con %(e)d entregas') % {
                    'r': len(creadas), 'e': len(entregas) - len(sin_ruta)},
                'message': ' '.join(avisos), 'type': 'warning', 'sticky': True,
                'next': accion_rutas,
            },
        }
