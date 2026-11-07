# -*- coding: utf-8 -*-
"""Ruta sugerida desde el servicio de rutas (contrato C1, GET /route). Nunca bloquea la predicción."""
import logging

import requests

_logger = logging.getLogger(__name__)

TIMEOUT_S = 15
PARAM_URL = 'logistica.routing_url'


def route(env, origen, destino):
    """Devuelve {'geometry': [[lat, lon], ...], 'distance_km', 'duration_min', 'source'} o None si no hay ruta."""
    url = (env['ir.config_parameter'].sudo().get_param(PARAM_URL) or '').strip().rstrip('/')
    if not url:
        return None
    params = {'origin_lat': origen[0], 'origin_lon': origen[1],
              'dest_lat': destino[0], 'dest_lon': destino[1]}
    try:
        respuesta = requests.get(url + '/route', params=params, timeout=TIMEOUT_S)
        if respuesta.status_code != 200:
            _logger.warning('routing_route_http status=%s', respuesta.status_code)
            return None
        return respuesta.json()
    except (requests.RequestException, ValueError) as exc:
        _logger.warning('routing_route_error error=%s', exc)
        return None
