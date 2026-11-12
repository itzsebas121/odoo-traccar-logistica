# -*- coding: utf-8 -*-
"""Cliente HTTP del servicio de rutas (contrato C1). La URL sale de logistica.routing_url."""
import logging

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# El optimizador admite hasta 30 s de cálculo; el cliente necesita margen para
# serialización y red antes de declarar el servicio caído.
TIMEOUT_S = 45
PARAM_URL = 'logistica.routing_url'


def _base_url(env):
    url = (env['ir.config_parameter'].sudo().get_param(PARAM_URL) or '').strip()
    if not url:
        raise UserError(_('Falta el parámetro del sistema «%s».') % PARAM_URL)
    return url.rstrip('/')


def optimize(env, payload):
    """POST /optimize. Devuelve el JSON del servicio o lanza UserError con un mensaje claro."""
    try:
        respuesta = requests.post(_base_url(env) + '/optimize', json=payload, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        _logger.warning('routing_optimize_error error=%s', exc)
        raise UserError(_('El servicio de rutas no está disponible. Intente de nuevo más tarde.'))
    if respuesta.status_code != 200:
        _logger.warning('routing_optimize_http status=%s', respuesta.status_code)
        raise UserError(_('El servicio de rutas rechazó la solicitud (HTTP %s).') % respuesta.status_code)
    try:
        return respuesta.json()
    except ValueError:
        raise UserError(_('El servicio de rutas devolvió una respuesta no válida.'))
