# -*- coding: utf-8 -*-
import logging

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, http
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
        return request.render('logistica_conductor.conductor_ruta', {
            'ruta': ruta, 'paradas': paradas, 'siguiente': siguiente,
            'estados': dict(ESTADOS_RUTA), 'estados_parada': ESTADOS_PARADA,
            'motivos': MOTIVOS_NO_ENTREGA})

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
