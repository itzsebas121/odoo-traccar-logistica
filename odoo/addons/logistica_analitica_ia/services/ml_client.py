# -*- coding: utf-8 -*-
"""Cliente HTTP del servicio de predicción (contrato C2). La URL sale de logistica.ml_url."""
import logging

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT_S = 15
PARAM_URL = 'logistica.ml_url'


def _no_disponible():
    return UserError(_('El modelo predictivo no está disponible. Revise que el servicio esté en marcha y entrenado.'))


def _base_url(env):
    url = (env['ir.config_parameter'].sudo().get_param(PARAM_URL) or '').strip()
    if not url:
        raise UserError(_('Falta el parámetro del sistema «%s».') % PARAM_URL)
    return url.rstrip('/')


def _llamar(env, metodo, ruta, **kwargs):
    try:
        respuesta = requests.request(metodo, _base_url(env) + ruta, timeout=TIMEOUT_S, **kwargs)
    except requests.RequestException as exc:
        _logger.warning('ml_error ruta=%s error=%s', ruta, exc)
        raise _no_disponible()
    if respuesta.status_code in (502, 503, 504):
        raise _no_disponible()
    if respuesta.status_code == 422:
        raise UserError(_('El modelo rechazó los datos de la consulta (zona o fecha no válidas).'))
    if respuesta.status_code != 200:
        _logger.warning('ml_http ruta=%s status=%s', ruta, respuesta.status_code)
        raise _no_disponible()
    try:
        return respuesta.json()
    except ValueError:
        raise _no_disponible()


def predict(env, payload):
    """POST /predict. payload: vehicle_code, reference_datetime (ISO 8601 UTC), origin_zone."""
    return _llamar(env, 'POST', '/predict', json=payload)


def metrics(env):
    """GET /metrics."""
    return _llamar(env, 'GET', '/metrics')
