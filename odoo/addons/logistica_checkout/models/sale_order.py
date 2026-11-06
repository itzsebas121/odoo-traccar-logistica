# -*- coding: utf-8 -*-
import math

from odoo import fields, models, _

MSG_SIN_PIN = 'Indique la ubicación de entrega colocando el pin en el mapa.'
MSG_INVALIDA = 'La ubicación de entrega no es válida. Vuelva a colocar el pin en el mapa.'
MSG_FUERA = ('La ubicación de entrega está fuera de la zona de cobertura. '
             'Elija un punto dentro del área atendida.')
MSG_TELEFONO = 'Falta el teléfono de contacto para la entrega.'


def _vacio(valor):
    return valor is None or valor is False or (isinstance(valor, str) and not valor.strip())


def _a_float(valor):
    if valor is None or valor is False:
        return None
    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if math.isnan(numero) or math.isinf(numero):
        return None
    return numero


def validar_destino(env, lat_raw, lon_raw):
    """Valida un par de coordenadas del checkout.

    Devuelve ``(lat, lon, mensaje_error)``; ``mensaje_error`` es ``None`` si es válido.
    Reglas (§3.1): numérico, -90..90 / -180..180, distinto de (0, 0) y dentro del
    rectángulo de cobertura de ``logistica.configuracion`` cuando está definido.
    """
    if _vacio(lat_raw) and _vacio(lon_raw):
        return None, None, _(MSG_SIN_PIN)
    lat, lon = _a_float(lat_raw), _a_float(lon_raw)
    if lat is None or lon is None:
        return None, None, _(MSG_INVALIDA)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None, None, _(MSG_INVALIDA)
    cobertura = env['logistica.configuracion'].sudo().get_config().cobertura()
    if cobertura:
        lat_min, lat_max, lon_min, lon_max = cobertura
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            return None, None, _(MSG_FUERA)
    return lat, lon, None


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    delivery_location_confirmed_at = fields.Datetime(
        string='Ubicación confirmada el', copy=False, readonly=True,
        help='Momento en que el cliente fijó el pin de entrega en el checkout.')

    def _logistica_zona_cercana(self, lat, lon):
        """Código de la zona activa cuyo centroide está más cerca del punto."""
        zonas = self.env['logistica.zona'].sudo().search([])
        if not zonas:
            return False
        cercana = min(zonas, key=lambda z: (z.latitude - lat) ** 2 + (z.longitude - lon) ** 2)
        return cercana.code

    def _logistica_fijar_destino(self, lat, lon, notas=None):
        """Guarda el destino en el pedido (no en el contacto, §3.1)."""
        self.ensure_one()
        vals = {
            'delivery_latitude': lat,
            'delivery_longitude': lon,
            'delivery_location_confirmed_at': fields.Datetime.now(),
        }
        zona = self._logistica_zona_cercana(lat, lon)
        if zona:
            vals['delivery_zone'] = zona
        if notas is not None:
            vals['delivery_notes'] = notas or False
        self.write(vals)

    def _logistica_checkout_errores(self):
        """Motivos que impiden confirmar automáticamente un pedido web."""
        self.ensure_one()
        errores = []
        if not self.only_services:
            _lat, _lon, error = validar_destino(
                self.env, self.delivery_latitude, self.delivery_longitude)
            if error:
                errores.append(error)
        partner = self.partner_shipping_id or self.partner_id
        if not (partner.phone or partner.mobile or self.partner_id.phone or self.partner_id.mobile):
            errores.append(_(MSG_TELEFONO))
        return errores
