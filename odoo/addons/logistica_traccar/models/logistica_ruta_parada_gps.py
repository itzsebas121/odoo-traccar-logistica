# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .logistica_traccar_util import haversine_m


class LogisticaRutaParadaGps(models.Model):
    _inherit = 'logistica.ruta.parada'

    @api.model
    def _paradas_en_recorrido(self, vehiculo):
        """Paradas pendientes de la ruta en recorrido del vehículo que aún no tienen posible llegada."""
        return self.sudo().search([
            ('route_id.vehicle_id', '=', vehiculo.id),
            ('route_id.state', '=', 'en_recorrido'),
            ('state', '=', 'pendiente'),
            ('arrival_candidate_at', '=', False),
        ])

    def _check_proximidad(self, latitud, longitud, gps_time=None):
        """Llegada por proximidad (§6.4): dentro del radio configurado registra ``posible_llegada``.

        Nunca cambia el estado de la entrega: solo una persona marca «entregado» (§1.1 regla 9).
        Devuelve las paradas marcadas.
        """
        radio = self.env['logistica.configuracion'].sudo().get_config().arrival_radius_m
        ahora = fields.Datetime.now()
        marcadas = self.browse()
        for parada in self.sudo():
            entrega = parada.entrega_id
            if (parada.state != 'pendiente' or parada.arrival_candidate_at
                    or parada.route_id.state != 'en_recorrido' or entrega.state != 'en_recorrido'):
                continue
            if haversine_m(latitud, longitud, entrega.latitude, entrega.longitude) > radio:
                continue
            hora = gps_time or ahora
            entrega.action_marcar_llegada(gps={
                'available': True, 'latitude': latitud, 'longitude': longitud,
                'time': hora, 'age_seconds': max(int((ahora - hora).total_seconds()), 0)})
            parada.write({'arrival_candidate_at': hora})
            marcadas |= parada
        return marcadas
