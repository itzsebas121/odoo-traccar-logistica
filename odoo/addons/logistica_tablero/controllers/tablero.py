# -*- coding: utf-8 -*-
"""Tablero de indicadores dentro de Odoo.

- /logistica/tablero/app: la pagina del tablero. Es el MISMO panel React (shadcn) del asistente, compilado en
  static/app (`bash scripts/build_tablero_odoo.sh`). El menu de Odoo la muestra a pantalla completa.
- /logistica/tablero/api/<seccion>: los datos, con la misma URL, los mismos filtros (query string) y el mismo JSON
  que /api/tablero/<seccion> del asistente. Errores igual que alli: {'detalle': mensaje} con 401 (sin sesion),
  403 (sin permiso), 404 (seccion desconocida), 422 (filtro invalido) o 503 (DWH no disponible; el detalle tecnico
  va al log).

Solo para gerentes de ventas o de flota (y administradores). Lee el DWH con el rol dwh_ro; no toca la base de Odoo.
"""
import logging
import os

from odoo import http
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
PAGINA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'app',
                      'tablero-odoo.html')
SIN_PERMISO = 'El tablero de indicadores es solo para gerentes de ventas o de flota.'

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
    """(codigo HTTP, cuerpo) de una seccion. Sin efectos sobre Odoo."""
    if seccion not in tablero.SECCIONES:
        return 404, {'detalle': 'Sección desconocida: %s' % seccion}
    crudos = {k: params.get(k) for k in FILTROS[seccion]}
    try:
        f = tablero.filtros(**{k: (str(v) if v not in (None, False, '') else None) for k, v in crudos.items()})
    except ValueError as exc:
        return 422, {'detalle': str(exc)}
    extra = {}
    if seccion == 'pronostico_detalle' and params.get('producto_sk') not in (None, '', False):
        try:
            extra['producto_sk'] = int(params['producto_sk'])
        except (TypeError, ValueError):
            return 422, {'detalle': 'producto_sk debe ser un número'}
    clave = (seccion, f.clave(), tuple(sorted(extra.items())))
    try:
        return 200, _cache.obtener(clave, lambda: tablero.SECCIONES[seccion](dwh(), f, **extra))
    except tablero.SinDwh as exc:
        _logger.warning('tablero_sin_datos seccion=%s detalle=%s', seccion, exc)
        return 503, {'detalle': tablero.MENSAJE_USUARIO}


def _sin_sesion():
    return not request.session.uid or request.env.user._is_public()


class TableroController(http.Controller):

    @http.route('/logistica/tablero/api/<string:seccion>', type='http', auth='public', methods=['GET'],
                csrf=False)
    def api(self, seccion, **params):
        # auth='public' para responder 401 en JSON (con auth='user' Odoo redirige al login con una pagina HTML).
        if _sin_sesion():
            codigo, cuerpo = 401, {'detalle': 'Inicie sesión en Odoo.'}
        elif not puede_ver(request.env.user):
            codigo, cuerpo = 403, {'detalle': SIN_PERMISO}
        else:
            codigo, cuerpo = consultar(seccion, params)
        respuesta = request.make_json_response(cuerpo, status=codigo)
        respuesta.headers['Cache-Control'] = 'no-store'
        return respuesta

    @http.route('/logistica/tablero/app', type='http', auth='user', methods=['GET'])
    def app(self, **_kw):
        if not puede_ver(request.env.user):
            return request.make_response(SIN_PERMISO, [('Content-Type', 'text/plain; charset=utf-8')], status=403)
        if not os.path.isfile(PAGINA):
            return request.make_response(
                'Falta compilar el tablero: bash scripts/build_tablero_odoo.sh',
                [('Content-Type', 'text/plain; charset=utf-8')], status=503)
        with open(PAGINA, 'rb') as f:
            html = f.read()
        return request.make_response(html, [('Content-Type', 'text/html; charset=utf-8'),
                                             ('Cache-Control', 'no-store')])
