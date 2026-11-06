# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class LogisticaConfiguracion(models.Model):
    """Parámetros del checkout sobre la configuración única de logística."""
    _inherit = 'logistica.configuracion'

    # Rectángulo de cobertura (aproximado: Ambato). Si min >= max en algún eje,
    # la cobertura se considera no definida y solo se valida el rango.
    coverage_lat_min = fields.Float(string='Latitud mínima de cobertura', digits=(10, 7), default=-1.35)
    coverage_lat_max = fields.Float(string='Latitud máxima de cobertura', digits=(10, 7), default=-1.15)
    coverage_lon_min = fields.Float(string='Longitud mínima de cobertura', digits=(10, 7), default=-78.70)
    coverage_lon_max = fields.Float(string='Longitud máxima de cobertura', digits=(10, 7), default=-78.52)
    checkout_auto_confirm = fields.Boolean(
        string='Confirmar pedidos web al completar el pago de prueba', default=True,
        help='D5: con el método de pago de prueba (payment_custom) el pedido se confirma '
             'sin aprobación manual si su destino y datos son válidos.')

    @api.constrains('coverage_lat_min', 'coverage_lat_max', 'coverage_lon_min', 'coverage_lon_max')
    def _check_cobertura(self):
        for rec in self:
            for valor in (rec.coverage_lat_min, rec.coverage_lat_max):
                if not -90 <= valor <= 90:
                    raise ValidationError(_('La latitud de cobertura debe estar entre -90 y 90.'))
            for valor in (rec.coverage_lon_min, rec.coverage_lon_max):
                if not -180 <= valor <= 180:
                    raise ValidationError(_('La longitud de cobertura debe estar entre -180 y 180.'))

    def cobertura(self):
        """``(lat_min, lat_max, lon_min, lon_max)`` o ``None`` si no está definida."""
        self.ensure_one()
        if self.coverage_lat_min < self.coverage_lat_max and self.coverage_lon_min < self.coverage_lon_max:
            return (self.coverage_lat_min, self.coverage_lat_max,
                    self.coverage_lon_min, self.coverage_lon_max)
        return None
