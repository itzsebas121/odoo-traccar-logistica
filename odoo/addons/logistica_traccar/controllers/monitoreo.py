# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from werkzeug.exceptions import Forbidden

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# El recorrido de la ruta activa se limita para no pedir a Traccar un historial enorme.
MAX_RECORRIDO_H = 12


class MonitoreoController(http.Controller):
    """Mapa de monitoreo. Traccar se consulta solo desde el servidor: al navegador nunca llegan
    credenciales, la URL del servidor ni cabeceras de autenticación (§12)."""

    def _exigir_flota(self):
        # Odoo limita al grupo «Flota / Usuario» a los vehículos que conduce; el mapa muestra toda la
        # flota, así que lo ve solo quien gestiona la flota.
        if not request.env.user.has_group('fleet.fleet_group_manager'):
            raise Forbidden()

    @http.route('/logistica/monitoreo', type='http', auth='user')
    def pagina(self, **kwargs):
        self._exigir_flota()
        return request.render('logistica_traccar.monitoreo_pagina', {})

    @http.route('/logistica/monitoreo/data', type='http', auth='user')
    def data(self, **kwargs):
        self._exigir_flota()
        cuerpo = json.dumps(self._datos(), ensure_ascii=False)
        return request.make_response(cuerpo, headers=[('Content-Type', 'application/json')])

    # ------------------------------------------------------------------
    def _datos(self):
        env = request.env
        vehiculos = env['fleet.vehicle'].search([('traccar_device_id', '!=', False)])
        rutas = env['logistica.ruta'].search([('state', '=', 'en_recorrido')])
        por_vehiculo = {ruta.vehicle_id.id: ruta for ruta in rutas}
        salida = []
        for vehiculo in vehiculos:
            estado = vehiculo.traccar_device_id._estado_gps()
            ruta = por_vehiculo.get(vehiculo.id)
            item = {
                'vehiculo_id': vehiculo.id,
                'placa': vehiculo.license_plate or vehiculo.display_name,
                'conductor': vehiculo.driver_id.name or '',
                'gps': estado,
                'ruta': self._ruta(ruta) if ruta else None,
            }
            salida.append(item)
        return {'vehiculos': salida, 'generado': fields.Datetime.to_string(fields.Datetime.now())}

    def _ruta(self, ruta):
        paradas = [{
            'orden': p.sequence, 'estado': p.state,
            'latitud': p.latitude, 'longitud': p.longitude,
            'referencia': p.entrega_id.name,
            'posible_llegada': bool(p.arrival_candidate_at),
        } for p in ruta.stop_ids.sorted('sequence')]
        return {
            'nombre': ruta.name,
            'bodega': {'latitud': ruta.bodega_id.latitude, 'longitud': ruta.bodega_id.longitude},
            'paradas': paradas,
            'recorrido': self._recorrido(ruta),
        }

    def _recorrido(self, ruta):
        """Puntos [lat, lon] recorridos desde el inicio de la ruta, o [] si Traccar no responde."""
        dispositivo = ruta.vehicle_id.traccar_device_id
        if not dispositivo or not ruta.started_at:
            return []
        ahora = fields.Datetime.now()
        desde = max(ruta.started_at, ahora - timedelta(hours=MAX_RECORRIDO_H))
        try:
            posiciones = dispositivo.server_id.get_route_report(dispositivo, desde, ahora)
        except UserError as exc:
            _logger.warning('monitoreo_recorrido_error ruta=%s error=%s', ruta.id, exc)
            return []
        return [[p['latitude'], p['longitude']] for p in posiciones
                if p.get('latitude') is not None and p.get('longitude') is not None]
