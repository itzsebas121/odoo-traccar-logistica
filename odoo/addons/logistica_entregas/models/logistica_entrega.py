# -*- coding: utf-8 -*-
import secrets
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .logistica_entrega_evento import MOTIVOS_NO_ENTREGA

ESTADOS = [
    ('pendiente_preparacion', 'Pendiente de preparación'),
    ('en_preparacion', 'En preparación'),
    ('preparado', 'Preparado para despacho'),
    ('asignado', 'Asignado a ruta'),
    ('en_recorrido', 'En recorrido'),
    ('entregado', 'Entregado'),
    ('no_entregado', 'No entregado'),
    ('pendiente_reprogramacion', 'Pendiente de reprogramación'),
    ('devuelto_bodega', 'Devuelto a bodega'),
]

# Máquina de estados (§8.2). Única fuente de verdad de transiciones permitidas.
TRANSICIONES = {
    'pendiente_preparacion': {'en_preparacion'},
    'en_preparacion': {'preparado'},
    'preparado': {'asignado'},
    'asignado': {'en_recorrido', 'preparado', 'pendiente_reprogramacion'},
    'en_recorrido': {'entregado', 'no_entregado', 'pendiente_reprogramacion'},
    'no_entregado': {'preparado', 'devuelto_bodega', 'pendiente_reprogramacion'},
    'pendiente_reprogramacion': {'preparado', 'devuelto_bodega'},
    'entregado': set(),
    'devuelto_bodega': set(),
}

TOKEN_VIGENCIA_DIAS = 90

# Solo el servidor (env.su) los escribe; la Tarea 8 fija route_id con sudo (R23).
CAMPOS_PROTEGIDOS = frozenset({
    'sale_order_id', 'route_id', 'tracking_token',
    'tracking_token_expires', 'tracking_token_revoked'})
# Una corrección no-su de estos campos queda auditada como 'destino_corregido' (R22).
CAMPOS_DESTINO = ('latitude', 'longitude', 'destination_address',
                  'delivery_reference', 'recipient_name')


def _nuevo_token():
    return secrets.token_urlsafe(32)


def _vence_token():
    return fields.Datetime.now() + timedelta(days=TOKEN_VIGENCIA_DIAS)


class LogisticaEntrega(models.Model):
    _name = 'logistica.entrega'
    _description = 'Entrega Logística'
    _order = 'id desc'

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True)
    sale_order_id = fields.Many2one(
        'sale.order', string='Pedido de venta', required=True,
        ondelete='restrict', index=True, copy=False)
    partner_id = fields.Many2one('res.partner', string='Cliente', index=True)
    latitude = fields.Float(string='Latitud', digits=(10, 7))
    longitude = fields.Float(string='Longitud', digits=(10, 7))
    destination_address = fields.Char(string='Dirección de destino')
    delivery_reference = fields.Text(string='Referencia / instrucciones de entrega')
    recipient_name = fields.Char(string='Destinatario')
    phone = fields.Char(string='Teléfono')
    state = fields.Selection(
        ESTADOS, string='Estado', default='pendiente_preparacion',
        required=True, index=True, copy=False)
    tracking_token = fields.Char(
        string='Token de seguimiento', default=lambda self: _nuevo_token(),
        copy=False, readonly=True, index=True,
        groups='fleet.fleet_group_manager')
    tracking_token_expires = fields.Datetime(
        string='Vencimiento del token', default=lambda self: _vence_token(), copy=False,
        groups='fleet.fleet_group_manager')
    tracking_token_revoked = fields.Boolean(string='Token revocado', default=False, copy=False,
        groups='fleet.fleet_group_manager')
    # Se reemplazan por route_stop_ids (One2many) y route_id (Many2one computado)
    # en la Tarea 8, cuando exista logistica.ruta.parada.entrega_id.
    route_id = fields.Integer(string='ID de ruta', copy=False)
    event_ids = fields.One2many(
        'logistica.entrega.evento', 'entrega_id', string='Eventos', readonly=True)

    _sql_constraints = [
        ('sale_order_uniq', 'unique(sale_order_id)',
         'Ya existe una entrega para este pedido.'),
        ('tracking_token_uniq', 'unique(tracking_token)',
         'El token de seguimiento debe ser único.'),
    ]

    # ------------------------------------------------------------------
    # Creación
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('state', 'pendiente_preparacion') != 'pendiente_preparacion':
                raise UserError(_(
                    'El estado de la entrega solo se cambia mediante sus acciones.'))
            if not vals.get('name') and vals.get('sale_order_id'):
                order = self.env['sale.order'].sudo().browse(vals['sale_order_id'])
                vals['name'] = 'ENT/%s' % order.name
            vals.setdefault('name', '/')
        records = super().create(vals_list)
        for rec in records:
            rec._registrar_evento('creado')
        return records

    # ------------------------------------------------------------------
    # Máquina de estados
    # ------------------------------------------------------------------
    def write(self, vals):
        if self.env.su:
            return super().write(vals)
        if 'state' in vals:
            raise UserError(_(
                'El estado de la entrega solo se cambia mediante sus acciones.'))
        protegidos = CAMPOS_PROTEGIDOS.intersection(vals)
        if protegidos:
            raise UserError(_(
                'Los campos %s de la entrega no se modifican manualmente.') % (
                ', '.join(sorted(protegidos))))
        destino = [f for f in CAMPOS_DESTINO if f in vals]
        anteriores = {rec.id: {f: rec[f] for f in destino} for rec in self} if destino else {}
        res = super().write(vals)
        for rec in self:
            cambios = [
                '%s: %s -> %s' % (f, anteriores[rec.id][f], rec[f])
                for f in destino if anteriores[rec.id][f] != rec[f]]
            if cambios:
                rec._registrar_evento('destino_corregido', notes='\n'.join(cambios))
        return res

    def _bloquear(self):
        """Bloquea la fila para que un doble clic/reintento concurrente espere."""
        self.ensure_one()
        self.flush_recordset(['state'])
        self.env.cr.execute(
            'SELECT 1 FROM logistica_entrega WHERE id = %s FOR UPDATE', (self.id,))
        self.invalidate_recordset(['state'])

    def _transicionar(self, desde, hacia):
        """Valida y aplica una transición. Único punto de cambio de estado.

        ``desde``: estado o iterable de estados esperados.
        """
        self.ensure_one()
        self._bloquear()
        esperados = {desde} if isinstance(desde, str) else set(desde)
        if self.state == hacia:
            raise UserError(_('Evento ya registrado: la entrega %s ya está en estado «%s».') % (
                self.name, dict(ESTADOS)[hacia]))
        if self.state not in esperados or hacia not in TRANSICIONES.get(self.state, set()):
            raise UserError(_('Transición no permitida: de «%s» a «%s» (entrega %s).') % (
                dict(ESTADOS)[self.state], dict(ESTADOS)[hacia], self.name))
        self.sudo().write({'state': hacia})

    # ------------------------------------------------------------------
    # Eventos y GPS
    # ------------------------------------------------------------------
    def _registrar_evento(self, tipo, **vals):
        self.ensure_one()
        vals.setdefault('route_id', self.route_id)
        return self.env['logistica.entrega.evento'].sudo().create(dict(
            vals, entrega_id=self.id, event_type=tipo,
            user_id=vals.get('user_id', self.env.user.id)))

    def _vehiculo_asignado(self):
        """Vehículo de la ruta de la entrega, si el módulo de despacho está instalado."""
        self.ensure_one()
        if self.route_id and 'logistica.ruta' in self.env:
            ruta = self.env['logistica.ruta'].sudo().browse(self.route_id).exists()
            if ruta and 'vehicle_id' in ruta._fields:
                return ruta.vehicle_id
        return self.env['fleet.vehicle']

    def _gps_snapshot(self):
        """Última posición conocida del vehículo asignado.

        Devuelve ``{'available', 'latitude', 'longitude', 'time', 'age_seconds'}``.
        ``available`` es False si no hay vehículo, módulo GPS o posición.
        """
        self.ensure_one()
        vacio = {'available': False, 'latitude': 0.0, 'longitude': 0.0,
                 'time': False, 'age_seconds': 0}
        if 'traccar.device' not in self.env:
            return vacio
        vehiculo = self._vehiculo_asignado()
        if not vehiculo:
            return vacio
        Device = self.env['traccar.device'].sudo()
        if 'last_position_time' not in Device._fields:
            return vacio
        # El vínculo real vive en la ficha de flota (fleet.vehicle.traccar_device_id, F1-R20);
        # traccar.device.vehicle_id no se usa para resolver el vehículo.
        device = Device.browse()
        if 'traccar_device_id' in vehiculo._fields:
            device = vehiculo.sudo().traccar_device_id
        if not device or not device.last_position_time:
            return vacio
        age = (fields.Datetime.now() - device.last_position_time).total_seconds()
        return {'available': True, 'latitude': device.last_latitude,
                'longitude': device.last_longitude, 'time': device.last_position_time,
                'age_seconds': max(int(age), 0)}

    def _registrar_evento_gps(self, tipo, gps=None, **vals):
        """Registra un evento con el GPS complementario; si no hay GPS añade
        además la incidencia ``gps_no_disponible``."""
        self.ensure_one()
        gps = gps or self._gps_snapshot()
        disponible = bool(gps.get('available', True)) and (
            gps.get('latitude') or gps.get('longitude'))
        if disponible:
            vals.update(
                gps_available=True,
                gps_latitude=gps.get('latitude', 0.0),
                gps_longitude=gps.get('longitude', 0.0),
                gps_time=gps.get('time') or False,
                gps_age_seconds=int(gps.get('age_seconds') or 0))
        else:
            vals['gps_available'] = False
        evento = self._registrar_evento(tipo, **vals)
        if not disponible:
            self._registrar_evento('gps_no_disponible', notes=_(
                'Sin posición GPS al registrar «%s».') % tipo)
        return evento

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def action_marcar_preparado(self):
        for rec in self:
            rec._transicionar('en_preparacion', 'preparado')
            rec._registrar_evento('preparado')
        return True

    def action_marcar_asignado(self, route_id=None):
        """Uso del despacho (Tarea 8): ruta aprobada."""
        for rec in self:
            rec._transicionar('preparado', 'asignado')
            if route_id:
                rec.sudo().write({'route_id': route_id})
            rec._registrar_evento('asignado')
        return True

    def action_marcar_en_recorrido(self):
        """Uso del despacho: la ruta inicia su recorrido."""
        for rec in self:
            rec._transicionar('asignado', 'en_recorrido')
            rec._registrar_evento_gps('inicio_recorrido')
        return True

    def action_marcar_llegada(self, gps=None):
        """Registra una posible llegada. Nunca cambia el estado (§1.1 regla 9)."""
        for rec in self:
            if rec.state != 'en_recorrido':
                raise UserError(_(
                    'Solo se puede registrar la llegada de una entrega en recorrido.'))
            rec._registrar_evento_gps('posible_llegada', gps=gps)
        return True

    def action_marcar_entregado(self):
        for rec in self:
            rec._transicionar('en_recorrido', 'entregado')
            rec._registrar_evento_gps('entregado')
        return True

    def action_marcar_no_entregado(self, motivo, notas=None):
        claves = dict(MOTIVOS_NO_ENTREGA)
        if not motivo or motivo not in claves:
            raise ValidationError(_('Debe indicar un motivo de no entrega válido.'))
        for rec in self:
            rec._transicionar('en_recorrido', 'no_entregado')
            rec._registrar_evento_gps('no_entregado', failure_reason=motivo, notes=notas)
        return True

    def action_reprogramar(self):
        for rec in self:
            rec._transicionar(('no_entregado', 'pendiente_reprogramacion'), 'preparado')
            rec.sudo().write({'route_id': 0})
            rec._registrar_evento('reprogramado')
        return True

    def action_devolver_bodega(self):
        for rec in self:
            rec._transicionar(('no_entregado', 'pendiente_reprogramacion'), 'devuelto_bodega')
            rec._registrar_evento('devuelto_bodega')
        return True

    # ------------------------------------------------------------------
    # Seguimiento público
    # ------------------------------------------------------------------
    def action_revocar_token(self):
        """Revoca el enlace público de seguimiento (§12, R24).

        Solo gestores de flota; la escritura se hace con sudo porque el campo
        está protegido frente a escrituras manuales (R23)."""
        if not self.env.user.has_group('fleet.fleet_group_manager'):
            raise UserError(_('Solo un gestor de flota puede revocar el enlace de seguimiento.'))
        self.sudo().write({'tracking_token_revoked': True})
        return True

    @api.model
    def get_by_tracking_token(self, token):
        """Entrega con token vigente y no revocado; vacío en cualquier otro caso.

        Devuelve un recordset sudo (uso desde controladores públicos).
        """
        if not token or not isinstance(token, str):
            return self.browse()
        return self.sudo().search([
            ('tracking_token', '=', token),
            ('tracking_token_revoked', '=', False),
            ('tracking_token_expires', '>', fields.Datetime.now()),
        ], limit=1)
