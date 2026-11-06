# -*- coding: utf-8 -*-
import threading
import time
from collections import deque

from odoo import _, http
from odoo.http import request
from odoo.tools import format_date

from odoo.addons.website_sale.controllers.main import WebsiteSale

from ..models.sale_order import validar_destino

# Estado público simplificado (D8): nunca se muestran coordenadas, ruta,
# conductor ni datos del cliente.
ESTADO_PUBLICO = {
    'pendiente_preparacion': 'En preparación',
    'en_preparacion': 'En preparación',
    'preparado': 'Preparado',
    'asignado': 'Preparado',
    'en_recorrido': 'En ruta',
    'entregado': 'Entregado',
    'no_entregado': 'No entregado',
    'pendiente_reprogramacion': 'No entregado',
    'devuelto_bodega': 'En retorno a bodega',
}


class LimitadorPeticiones:
    """Límite de peticiones por clave (IP) en memoria, ventana deslizante.

    Es por proceso: con varios workers el límite efectivo se multiplica por
    el número de workers, lo cual es aceptable para frenar intentos masivos.
    """

    MAX_CLAVES = 10000

    def __init__(self, limite, ventana_s):
        self.limite = limite
        self.ventana = ventana_s
        self._marcas = {}
        self._lock = threading.Lock()

    def permitir(self, clave, ahora=None):
        ahora = time.monotonic() if ahora is None else ahora
        corte = ahora - self.ventana
        with self._lock:
            if len(self._marcas) > self.MAX_CLAVES:
                self._purgar(corte)
            marcas = self._marcas.setdefault(clave, deque())
            while marcas and marcas[0] <= corte:
                marcas.popleft()
            if len(marcas) >= self.limite:
                return False
            marcas.append(ahora)
            return True

    def _purgar(self, corte):
        for clave in [c for c, m in self._marcas.items() if not m or m[-1] <= corte]:
            del self._marcas[clave]

    def reset(self):
        with self._lock:
            self._marcas.clear()


LIMITADOR = LimitadorPeticiones(limite=30, ventana_s=60)


class LogisticaWebsiteSale(WebsiteSale):

    # ------------------------------------------------------------------
    # Datos mínimos: el teléfono es obligatorio (§3.1)
    # ------------------------------------------------------------------
    def _get_mandatory_fields_billing(self, country_id=False):
        req = super()._get_mandatory_fields_billing(country_id)
        return req if 'phone' in req else req + ['phone']

    def _get_mandatory_fields_shipping(self, country_id=False):
        req = super()._get_mandatory_fields_shipping(country_id)
        return req if 'phone' in req else req + ['phone']

    # ------------------------------------------------------------------
    # Destino en mapa
    # ------------------------------------------------------------------
    def checkout_form_validate(self, mode, all_form_values, data):
        error, error_message = super().checkout_form_validate(mode, all_form_values, data)
        order = request.website.sale_get_order()
        if order and not order.only_services:
            _lat, _lon, msg = validar_destino(
                request.env, all_form_values.get('delivery_latitude'),
                all_form_values.get('delivery_longitude'))
            if msg:
                error['delivery_latitude'] = 'error'
                error_message.append(msg)
        return error, error_message

    def _checkout_form_save(self, mode, checkout, all_values):
        partner_id = super()._checkout_form_save(mode, checkout, all_values)
        if not isinstance(partner_id, int):  # Forbidden
            return partner_id
        order = request.website.sale_get_order()
        if order and not order.only_services:
            lat, lon, msg = validar_destino(
                request.env, all_values.get('delivery_latitude'),
                all_values.get('delivery_longitude'))
            if not msg:
                # El destino se guarda en el pedido, nunca en el contacto (§3.1).
                order._logistica_fijar_destino(lat, lon, all_values.get('delivery_notes'))
        return partner_id

    @http.route()
    def address(self, **kw):
        response = super().address(**kw)
        qcontext = getattr(response, 'qcontext', None)
        if qcontext is not None:
            qcontext.update(self._logistica_valores_mapa(qcontext, kw))
        return response

    def _logistica_valores_mapa(self, qcontext, kw):
        order = qcontext.get('website_sale_order')
        lat = lon = ''
        notas = ''
        if kw.get('submitted') and qcontext.get('error'):
            lat = kw.get('delivery_latitude') or ''
            lon = kw.get('delivery_longitude') or ''
            notas = kw.get('delivery_notes') or ''
        elif order and order._logistica_destino_valido():
            lat, lon = order.delivery_latitude, order.delivery_longitude
            notas = order.delivery_notes or ''
        config = request.env['logistica.configuracion'].sudo().get_config()
        cobertura = config.cobertura()
        centro = request.env['logistica.zona'].sudo().centroide('centro')
        if centro == (0.0, 0.0) and cobertura:
            centro = ((cobertura[0] + cobertura[1]) / 2, (cobertura[2] + cobertura[3]) / 2)
        return {
            'logistica_destino': {
                'lat': lat, 'lon': lon, 'notas': notas,
                'centro': centro,
                'cobertura': ','.join(str(v) for v in cobertura) if cobertura else '',
            },
        }

    def checkout_check_address(self, order):
        redirection = super().checkout_check_address(order)
        if redirection:
            return redirection
        if not order.only_services:
            _lat, _lon, msg = validar_destino(
                request.env, order.delivery_latitude, order.delivery_longitude)
            if msg:
                return request.redirect('/shop/address?partner_id=%d' % order.partner_shipping_id.id)
        return None

    def _get_shop_payment_errors(self, order):
        errors = super()._get_shop_payment_errors(order)
        for msg in order._logistica_checkout_errores():
            errors.append((_('Faltan datos de entrega'), msg))
        return errors

    # ------------------------------------------------------------------
    # Confirmación: enlace de seguimiento o motivo del rechazo
    # ------------------------------------------------------------------
    def _prepare_shop_payment_confirmation_values(self, order):
        values = super()._prepare_shop_payment_confirmation_values(order)
        order_sudo = order.sudo()
        url = False
        entrega = order_sudo.logistica_entrega_ids[:1]
        if entrega:
            token = entrega.tracking_token
            if entrega.get_by_tracking_token(token):
                url = '%s/logistica/seguimiento/%s' % (order_sudo.get_base_url(), token)
        values['logistica_tracking_url'] = url
        values['logistica_errores'] = (
            order_sudo._logistica_checkout_errores()
            if order_sudo.state in ('draft', 'sent') else [])
        return values


class LogisticaSeguimiento(http.Controller):

    @http.route('/logistica/seguimiento/<string:token>', type='http', auth='public',
                methods=['GET'], website=True, sitemap=False)
    def logistica_seguimiento(self, token, **kw):
        ip = request.httprequest.remote_addr or 'desconocida'
        if not LIMITADOR.permitir(ip):
            return request.make_response(
                _('Demasiadas consultas. Intente de nuevo en un minuto.'), status=429,
                headers=[('Content-Type', 'text/plain; charset=utf-8'), ('Retry-After', '60')])
        # R16: el único acceso sudo es la búsqueda por token (dentro de
        # get_by_tracking_token); solo se copian tres valores simplificados.
        entrega = request.env['logistica.entrega'].get_by_tracking_token(token)
        if not entrega:
            raise request.not_found()
        pedido = entrega.sale_order_id
        seguimiento = {
            'pedido': pedido.name,
            'estado': ESTADO_PUBLICO.get(entrega.state, 'En preparación'),
            'fecha': format_date(request.env, pedido.date_order),
        }
        response = request.render('logistica_checkout.seguimiento_pedido',
                                  {'seguimiento': seguimiento})
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response
