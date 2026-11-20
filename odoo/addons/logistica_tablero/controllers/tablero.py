# -*- coding: utf-8 -*-
"""API JSON del tablero de indicadores: /logistica/tablero/api/<seccion>.

Solo para gerentes de ventas o de flota (y administradores). Lee el DWH con el rol dwh_ro; no toca la base de Odoo.
Si el DWH no esta disponible responde {'error': ...} con un mensaje simple (el detalle tecnico va al log).
"""
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from .. import tablero

_logger = logging.getLogger(__name__)

GRUPOS = ('sales_team.group_sale_manager', 'fleet.fleet_group_manager', 'base.group_system')
# Filtros que usa cada seccion (los demas se ignoran, igual que en el asistente).
FILTROS = {
    'resumen': ('desde', 'hasta', 'procedencia', 'zona', 'categoria'),
    'demanda': ('desde', 'hasta', 'procedencia', 'zona', 'categoria'),
    'pronostico': ('desde', 'hasta', 'procedencia', 'zona', 'categoria'),
    'pronostico_detalle': ('desde', 'hasta', 'procedencia', 'zona', 'categoria'),
    'operacion': ('desde', 'hasta', 'procedencia', 'zona', 'conductor'),
    'opciones': (),
}

_dwh = None
_cache = tablero.Cache()


def dwh():
    """Conexion al DWH (se crea al primer uso; las pruebas la reemplazan por un DWH falso)."""
    global _dwh
    if _dwh is None:
        _dwh = tablero.Dwh.desde_entorno()
    return _dwh


def puede_ver(usuario):
    return any(usuario.has_group(g) for g in GRUPOS)


def consultar(seccion, params):
    """Datos de una seccion, o {'error': mensaje}. Sin efectos sobre Odoo."""
    if seccion not in tablero.SECCIONES:
        return {'error': 'Sección desconocida: %s' % seccion}
    crudos = {k: params.get(k) for k in FILTROS[seccion]}
    try:
        f = tablero.filtros(**{k: (str(v) if v not in (None, False) else None) for k, v in crudos.items()})
    except ValueError as exc:
        return {'error': str(exc)}
    extra = {}
    if seccion == 'pronostico_detalle' and params.get('producto_sk') not in (None, '', False):
        try:
            extra['producto_sk'] = int(params['producto_sk'])
        except (TypeError, ValueError):
            return {'error': 'producto_sk debe ser un número'}
    clave = (seccion, f.clave(), tuple(sorted(extra.items())))
    try:
        return _cache.obtener(clave, lambda: tablero.SECCIONES[seccion](dwh(), f, **extra))
    except tablero.SinDwh as exc:
        _logger.warning('tablero_sin_datos seccion=%s detalle=%s', seccion, exc)
        return {'error': tablero.MENSAJE_USUARIO}


class TableroController(http.Controller):

    @http.route('/logistica/tablero/api/<string:seccion>', type='json', auth='user', methods=['POST'])
    def api(self, seccion, **params):
        if not puede_ver(request.env.user):
            raise AccessError('El tablero de indicadores es solo para gerentes de ventas o de flota.')
        return consultar(seccion, params)
