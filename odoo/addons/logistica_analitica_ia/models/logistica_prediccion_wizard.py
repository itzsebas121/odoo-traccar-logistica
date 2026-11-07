# -*- coding: utf-8 -*-
import json
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.logistica_base.models.logistica_zona import ZONA_CODES

from ..services import ml_client, routing_geometry


def _hora_actual(modelo):
    ahora = fields.Datetime.context_timestamp(modelo, datetime.now())
    return ahora.hour + ahora.minute / 60.0


class LogisticaPrediccionWizard(models.TransientModel):
    _name = 'logistica.prediccion.wizard'
    _description = 'Asistente: predecir destino'

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehículo', required=True)
    fecha = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    hora = fields.Float(string='Hora', required=True, default=lambda self: _hora_actual(self))
    origin_zone = fields.Selection(ZONA_CODES, string='Zona de origen')

    def _referencia_utc(self):
        """Fecha y hora elegidas (en la zona horaria del usuario) pasadas a UTC sin zona."""
        self.ensure_one()
        local = datetime.combine(self.fecha, time.min) + timedelta(minutes=round(self.hora * 60))
        zona = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        return zona.localize(local).astimezone(pytz.utc).replace(tzinfo=None)

    def action_predecir(self):
        """Consulta al modelo, guarda la auditoría y sugiere la ruta. No toca pedidos, entregas ni rutas."""
        self.ensure_one()
        if not self.origin_zone:
            raise ValidationError(_('La zona de origen es obligatoria.'))
        placa = self.vehicle_id.license_plate
        if not placa:
            raise UserError(_('El vehículo %s no tiene placa; el modelo identifica a los vehículos por su placa.')
                            % self.vehicle_id.display_name)
        referencia = self._referencia_utc()
        respuesta = ml_client.predict(self.env, {
            'vehicle_code': placa,
            'reference_datetime': referencia.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'origin_zone': self.origin_zone,
        })
        destino = respuesta.get('predicted_zone')
        if not destino:
            raise UserError(_('El modelo predictivo devolvió una respuesta sin destino.'))

        Zona = self.env['logistica.zona']
        origen_xy, destino_xy = Zona.centroide(self.origin_zone), Zona.centroide(destino)
        ruta = None
        if origen_xy != (0.0, 0.0) and destino_xy != (0.0, 0.0):
            ruta = routing_geometry.route(self.env, origen_xy, destino_xy)
        ruta = ruta or {}

        consulta = self.env['logistica.prediccion.consulta'].create({
            'vehicle_id': self.vehicle_id.id,
            'reference_datetime': referencia,
            'origin_zone': self.origin_zone,
            'predicted_zone': destino,
            'class_probabilities': json.dumps(respuesta.get('probabilities') or {}, sort_keys=True),
            'alternatives': json.dumps(respuesta.get('alternatives') or []),
            'model_version': respuesta.get('model_version'),
            'route_geometry': json.dumps(ruta.get('geometry') or []),
            'route_distance_km': ruta.get('distance_km') or 0.0,
            'route_duration_min': ruta.get('duration_min') or 0.0,
            'route_source': ruta.get('source') or False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'logistica.prediccion.consulta',
            'res_id': consulta.id,
            'view_mode': 'form',
            'target': 'current',
        }
