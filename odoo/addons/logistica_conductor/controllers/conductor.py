# -*- coding: utf-8 -*-
import logging
import json
import requests

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.logistica_despacho.models.logistica_ruta import ESTADOS_RUTA
from odoo.addons.logistica_entregas.models.logistica_entrega_evento import MOTIVOS_NO_ENTREGA

_logger = logging.getLogger(__name__)

GRUPO_CONDUCTOR = 'logistica_conductor.group_conductor'
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
        """Obtiene geometría vial por segmentos desde el servicio de routing."""
        base = request.env['ir.config_parameter'].sudo().get_param(
            'logistica.routing_url') or 'http://routing:8000'
        coordenadas = [origen or [ruta.bodega_id.latitude, ruta.bodega_id.longitude]] + [
            [p.latitude, p.longitude] for p in puntos if p.latitude or p.longitude]
        geometria = []
        for origen, destino in zip(coordenadas, coordenadas[1:]):
            try:
                respuesta = requests.get(base.rstrip('/') + '/route', params={
                    'origin_lat': origen[0], 'origin_lon': origen[1],
                    'dest_lat': destino[0], 'dest_lon': destino[1]}, timeout=8)
                tramo = respuesta.json().get('geometry') if respuesta.status_code == 200 else []
                if tramo:
                    geometria.extend(tramo if not geometria else tramo[1:])
                    continue
            except (requests.RequestException, ValueError):
                pass
            geometria.extend([origen] if not geometria else [])
            geometria.append(destino)
        return geometria or coordenadas

    def _mapa_payload(self, ruta):
        # La ruta ya fue validada como propia; se usa sudo únicamente para leer
        # vehículo/dispositivo y construir el mapa, sin conceder acceso general
        # del conductor a fleet.vehicle o traccar.device.
        ruta_mapa = ruta.sudo()
        puntos = ruta.stop_ids.sorted('sequence')
        recorrido = []
        dispositivo = ruta_mapa.vehicle_id.traccar_device_id
        if dispositivo and ruta_mapa.started_at:
            try:
                posiciones = dispositivo.server_id.get_route_report(
                    dispositivo, ruta_mapa.started_at, fields.Datetime.now())
                recorrido = [[p['latitude'], p['longitude']] for p in posiciones
                             if p.get('latitude') is not None and p.get('longitude') is not None]
            except UserError:
                recorrido = []
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
        return {
            'ruta': ruta.name, 'estado': ruta.state,
            'origen': [ruta_mapa.bodega_id.latitude, ruta_mapa.bodega_id.longitude],
            'planificada': [[ruta_mapa.bodega_id.latitude, ruta_mapa.bodega_id.longitude]] +
                [[p.latitude, p.longitude] for p in puntos if p.latitude or p.longitude],
            'geometria': self._geometria_ruta(ruta_mapa, puntos_para_ruta, origen_recalculo),
            'recorrido': recorrido,
            'posicion': dispositivo._estado_gps() if dispositivo else None,
            'paradas': [{'orden': p.sequence, 'nombre': p.entrega_id.name,
                         'direccion': p.destination_address or '', 'latitud': p.latitude,
                         'longitud': p.longitude, 'estado': p.state} for p in puntos],
        }

    @http.route('/logistica/conductor/ruta/<int:route_id>/mapa-data', type='http', auth='user', csrf=False)
    def mapa_data(self, route_id, **kwargs):
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
