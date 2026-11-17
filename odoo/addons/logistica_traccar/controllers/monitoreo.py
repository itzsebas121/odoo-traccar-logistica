# -*- coding: utf-8 -*-
import json
import logging
import threading
import time
from datetime import timedelta

from werkzeug.exceptions import Forbidden

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# El recorrido de la ruta activa se limita para no pedir a Traccar un historial enorme.
MAX_RECORRIDO_H = 12
# El mapa se refresca cada 10 s por cada usuario abierto; el recorrido se reutiliza unos segundos para no
# pedir a Traccar un informe por vehículo y por pestaña en cada refresco (caché por proceso).
CACHE_RECORRIDO_S = 20
_CACHE_MAX = 500


class CacheRecorrido:
    """Caché en memoria con caducidad. Es por proceso; con varios workers cada uno tiene la suya."""

    def __init__(self, ttl_s):
        self.ttl = ttl_s
        self._datos = {}
        self._lock = threading.Lock()

    def obtener(self, clave, calcular, ahora=None):
        ahora = time.monotonic() if ahora is None else ahora
        with self._lock:
            item = self._datos.get(clave)
            if item and item[0] > ahora:
                return item[1]
        valor = calcular()
        with self._lock:
            if len(self._datos) >= _CACHE_MAX:
                self._datos = {c: v for c, v in self._datos.items() if v[0] > ahora}
            self._datos[clave] = (ahora + self.ttl, valor)
        return valor

    def reset(self):
        with self._lock:
            self._datos.clear()


CACHE = CacheRecorrido(CACHE_RECORRIDO_S)


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
        clave = (request.env.cr.dbname, dispositivo.id, ruta.id, str(ruta.started_at))
        return CACHE.obtener(clave, lambda: self._consultar_recorrido(ruta, dispositivo))

    def _consultar_recorrido(self, ruta, dispositivo):
        ahora = fields.Datetime.now()
        desde = max(ruta.started_at, ahora - timedelta(hours=MAX_RECORRIDO_H))
        try:
            # interactivo: un intento corto y sin escribir el estado del servidor (ver traccar.server._request).
            posiciones = dispositivo.server_id.get_route_report(dispositivo, desde, ahora, interactivo=True)
        except UserError as exc:
            _logger.warning('monitoreo_recorrido_error ruta=%s error=%s', ruta.id, exc)
            return []
        return [[p['latitude'], p['longitude']] for p in posiciones
                if p.get('latitude') is not None and p.get('longitude') is not None]
