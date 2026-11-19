# -*- coding: utf-8 -*-
import logging
import json
import requests

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.logistica_despacho.models.logistica_ruta import ESTADOS_RUTA
from odoo.addons.logistica_entregas.models.logistica_entrega_evento import MOTIVOS_NO_ENTREGA

_logger = logging.getLogger(__name__)

GRUPO_CONDUCTOR = 'logistica_conductor.group_conductor'
# Servicio de rutas: una sola petición por mapa; si tarda más se dibuja la línea recta.
TIMEOUT_GEOMETRIA_S = 8
TOPE_PUNTOS_GEOMETRIA = 100  # límite de /route/multi
ESTADOS_PARADA = {'pendiente': 'Pendiente', 'entregado': 'Entregado', 'no_entregado': 'No entregado'}


class ConductorController(http.Controller):
    """Portal móvil del conductor.

    Cada ruta o parada se resuelve con el entorno del usuario (las reglas de registro del grupo
    «Conductor de reparto» están activas) y se confirma con ``assert_driver``. No se usa sudo para
    los datos del conductor. Una ruta ajena y una inexistente responden igual para no revelar datos.
    """

    # ------------------------------------------------------------------ ayudas
    def _exigir_conductor(self):
        if not request.env.user.has_group(GRUPO_CONDUCTOR):
            raise Forbidden()

    def _ruta_propia(self, route_id):
        ruta = request.env['logistica.ruta'].browse(route_id)
        try:
            if not ruta.exists():
                return None
            ruta.assert_driver(request.env.user)
        except AccessError:
            return None
        return ruta

    def _parada_propia(self, stop_id):
        parada = request.env['logistica.ruta.parada'].browse(stop_id)
        try:
            if not parada.exists():
                return None
            parada.route_id.assert_driver(request.env.user)
        except AccessError:
            return None
        return parada

    def _error(self, estado, mensaje, volver='/logistica/conductor'):
        respuesta = request.render(
            'logistica_conductor.conductor_error', {'mensaje': mensaje, 'volver': volver})
        respuesta.status_code = estado
        return respuesta

    def _ejecutar(self, ruta, accion):
        """Corre ``accion`` dentro de un savepoint (un fallo no deja cambios a medias).
        Éxito: redirige a la ruta. Error: 403, 409 (ya registrado) o 400, con mensaje en español."""
        destino = '/logistica/conductor/ruta/%s' % ruta.id
        try:
            with request.env.cr.savepoint():
                accion()
        except AccessError:
            return self._error(403, _('No tiene permiso para esta acción.'), destino)
        except ValidationError as exc:
            return self._error(400, exc.args[0], destino)
        except UserError as exc:
            mensaje = exc.args[0]
            estado = 409 if 'ya registrado' in mensaje else 400
            return self._error(estado, mensaje, destino)
        return request.redirect(destino, code=303)

    # ------------------------------------------------------------------ páginas
    @http.route('/logistica/conductor', type='http', auth='user')
    def rutas(self, **kwargs):
        self._exigir_conductor()
        rutas = request.env['logistica.ruta'].search(
            [('driver_id', '=', request.env.user.partner_id.id)], order='date desc, id desc')
        return request.render('logistica_conductor.conductor_rutas', {
            'rutas': rutas, 'estados': dict(ESTADOS_RUTA)})

    @http.route('/logistica/conductor/ruta/<int:route_id>', type='http', auth='user')
    def ruta(self, route_id, **kwargs):
        self._exigir_conductor()
        ruta = self._ruta_propia(route_id)
        if not ruta:
            raise NotFound()
        paradas = ruta.stop_ids.sorted('sequence')
        siguiente = False
        if ruta.state == 'en_recorrido':
            siguiente = next((p for p in paradas if p.state == 'pendiente'), False)
        mapa = self._mapa_payload(ruta)
        return request.render('logistica_conductor.conductor_ruta', {
            'ruta': ruta, 'paradas': paradas, 'siguiente': siguiente,
            'estados': dict(ESTADOS_RUTA), 'estados_parada': ESTADOS_PARADA,
            'motivos': MOTIVOS_NO_ENTREGA, 'mapa_json': json.dumps(mapa, ensure_ascii=False)})

    def _geometria_ruta(self, ruta, puntos, origen=None):
        """Geometría vial de toda la ruta en UNA llamada al servicio de routing (POST /route/multi).

        Antes se pedía tramo por tramo y en serie (unos 2 s por tramo contra OSRM), lo que dejaba la página
        del conductor esperando decenas de segundos. Si el servicio falla se usa la línea recta."""
        base = request.env['ir.config_parameter'].sudo().get_param(
            'logistica.routing_url') or 'http://routing:8000'
        coordenadas = [origen or [ruta.bodega_id.latitude, ruta.bodega_id.longitude]] + [
            [p.latitude, p.longitude] for p in puntos if p.latitude or p.longitude]
        if len(coordenadas) < 2:
            return coordenadas
        try:
            respuesta = requests.post(base.rstrip('/') + '/route/multi', json={
                'points': [{'lat': lat, 'lon': lon} for lat, lon in coordenadas[:TOPE_PUNTOS_GEOMETRIA]]},
                timeout=TIMEOUT_GEOMETRIA_S)
            if respuesta.status_code == 200:
                geometria = respuesta.json().get('geometry') or []
                if len(geometria) >= 2:
                    return geometria
            else:
                _logger.warning('conductor_geometria_http status=%s', respuesta.status_code)
        except (requests.RequestException, ValueError) as exc:
            _logger.warning('conductor_geometria_error error=%s', exc)
        return coordenadas

    def _mapa_payload(self, ruta):
        # La ruta ya fue validada como propia; se usa sudo únicamente para leer
        # vehículo/dispositivo y construir el mapa, sin conceder acceso general
        # del conductor a fleet.vehicle o traccar.device.
        ruta_mapa = ruta.sudo()
        puntos = ruta.stop_ids.sorted('sequence')
        dispositivo = ruta_mapa.vehicle_id.traccar_device_id
        # Mismo recorrido que el mapa de monitoreo: posiciones ya guardadas en Odoo (logistica_traccar).
        recorrido = ruta_mapa._recorrido_gps()
        gps = dispositivo._estado_gps() if dispositivo else None
        origen_dinamico = None
        if ruta_mapa.state == 'en_recorrido' and gps and gps.get('tiene_posicion'):
            ultima = gps['ultima_ubicacion_conocida']
            origen_dinamico = [ultima['latitud'], ultima['longitud']]
        puntos_pendientes = [p for p in puntos if p.state == 'pendiente']
        # Cuando la ruta ya no tiene pendientes, conservar la geometría completa
        # para que el conductor pueda revisar el recorrido planificado.
        puntos_para_ruta = puntos_pendientes or list(puntos)
        origen_recalculo = origen_dinamico if puntos_pendientes else None
        aviso = None
        if not dispositivo:
            aviso = _('Este vehículo no tiene GPS asignado: no se puede mostrar el recorrido real.')
        elif ruta_mapa.state == 'en_recorrido' and not recorrido:
            aviso = _('Aún no llegan posiciones GPS desde la salida. Revise que Traccar Client esté activo '
                      'y use el identificador «%s».') % dispositivo.unique_id
        return {
            'aviso': aviso,
            'ruta': ruta.name, 'estado': ruta.state,
            'origen': [ruta_mapa.bodega_id.latitude, ruta_mapa.bodega_id.longitude],
            'planificada': [[ruta_mapa.bodega_id.latitude, ruta_mapa.bodega_id.longitude]] +
                [[p.latitude, p.longitude] for p in puntos if p.latitude or p.longitude],
            'geometria': self._geometria_ruta(ruta_mapa, puntos_para_ruta, origen_recalculo),
            'recorrido': recorrido,
            'posicion': gps,
            'paradas': [{'orden': p.sequence, 'nombre': p.entrega_id.name,
                         'direccion': p.destination_address or '', 'latitud': p.latitude,
                         'longitud': p.longitude, 'estado': p.state} for p in puntos],
        }

    @http.route('/logistica/conductor/ruta/<int:route_id>/mapa-data', type='http', auth='user', methods=['GET'])
    def mapa_data(self, route_id, **kwargs):
        self._exigir_conductor()
        ruta = self._ruta_propia(route_id)
        if not ruta:
            raise NotFound()
        payload = self._mapa_payload(ruta)
        return request.make_response(json.dumps(payload, ensure_ascii=False),
                                     headers=[('Content-Type', 'application/json')])

    # ------------------------------------------------------------- acciones de ruta
    def _accion_ruta(self, route_id, nombre_metodo, *args):
        self._exigir_conductor()
        ruta = self._ruta_propia(route_id)
        if not ruta:
            return self._error(403, _('No tiene permiso para esta ruta.'))
        return self._ejecutar(ruta, lambda: getattr(ruta, nombre_metodo)(*args))

    @http.route('/logistica/conductor/ruta/<int:route_id>/salir',
                type='http', auth='user', methods=['POST'])
    def salir(self, route_id, **kwargs):
        """Fase A: confirma la carga (si falta) e inicia el recorrido en un solo paso."""
        return self._accion_ruta(route_id, 'action_salir_a_ruta')

    @http.route('/logistica/conductor/ruta/<int:route_id>/confirmar-carga',
                type='http', auth='user', methods=['POST'])
    def confirmar_carga(self, route_id, **kwargs):
        return self._accion_ruta(route_id, 'action_confirmar_carga')

    @http.route('/logistica/conductor/ruta/<int:route_id>/iniciar',
                type='http', auth='user', methods=['POST'])
    def iniciar(self, route_id, **kwargs):
        return self._accion_ruta(route_id, 'action_iniciar_recorrido')

    @http.route('/logistica/conductor/ruta/<int:route_id>/cerrar',
                type='http', auth='user', methods=['POST'])
    def cerrar(self, route_id, **kwargs):
        return self._accion_ruta(route_id, 'action_cerrar')

    @http.route('/logistica/conductor/ruta/<int:route_id>/interrumpir',
                type='http', auth='user', methods=['POST'])
    def interrumpir(self, route_id, motivo=None, **kwargs):
        if not (motivo or '').strip():
            self._exigir_conductor()
            return self._error(400, _('Debe indicar el motivo de la interrupción.'),
                               '/logistica/conductor/ruta/%s' % route_id)
        return self._accion_ruta(route_id, 'action_interrumpir', motivo.strip())

    # ------------------------------------------------------------ acciones de parada
    def _accion_parada(self, stop_id, nombre_metodo, *args):
        self._exigir_conductor()
        parada = self._parada_propia(stop_id)
        if not parada:
            return self._error(403, _('No tiene permiso para esta parada.'))
        return self._ejecutar(parada.route_id, lambda: getattr(parada, nombre_metodo)(*args))

    @http.route('/logistica/conductor/parada/<int:stop_id>/llegada',
                type='http', auth='user', methods=['POST'])
    def llegada(self, stop_id, **kwargs):
        return self._accion_parada(stop_id, 'action_marcar_llegada')

    @http.route('/logistica/conductor/parada/<int:stop_id>/entregado',
                type='http', auth='user', methods=['POST'])
    def entregado(self, stop_id, **kwargs):
        return self._accion_parada(stop_id, 'action_marcar_entregado')

    @http.route('/logistica/conductor/parada/<int:stop_id>/no-entregado',
                type='http', auth='user', methods=['POST'])
    def no_entregado(self, stop_id, motivo=None, notas=None, **kwargs):
        if not motivo:
            self._exigir_conductor()
            parada = self._parada_propia(stop_id)
            volver = '/logistica/conductor/ruta/%s' % parada.route_id.id if parada else '/logistica/conductor'
            return self._error(400, _('Debe indicar el motivo de la no entrega.'), volver)
        return self._accion_parada(stop_id, 'action_marcar_no_entregado', motivo, (notas or '').strip() or None)
