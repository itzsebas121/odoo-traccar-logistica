# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

ESTADOS_RUTA = [
    ('borrador', 'Borrador'),
    ('planificada', 'Planificada'),
    ('carga_confirmada', 'Carga confirmada'),
    ('en_recorrido', 'En recorrido'),
    ('cerrada', 'Cerrada'),
    ('cancelada', 'Cancelada'),
    ('interrumpida', 'Interrumpida'),
]
# Una entrega solo puede estar en una ruta de estas.
ESTADOS_ACTIVOS = ('borrador', 'planificada', 'carga_confirmada', 'en_recorrido')
# Solo el servidor (sudo) escribe estos campos; las acciones validan antes.
CAMPOS_PROTEGIDOS = frozenset({
    'name', 'state', 'confirmed_load_at', 'started_at', 'finished_at', 'interrupt_reason'})


class LogisticaRuta(models.Model):
    _name = 'logistica.ruta'
    _description = 'Ruta de Despacho'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Código de ruta', required=True, copy=False, readonly=True,
        default=lambda self: _('Nuevo'))
    date = fields.Date(string='Fecha de despacho', required=True, default=fields.Date.context_today)
    bodega_id = fields.Many2one(
        'logistica.bodega', string='Bodega de salida', required=True, ondelete='restrict',
        default=lambda self: self.env['logistica.bodega'].get_bodega_activa().id)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Vehículo', required=True, ondelete='restrict', index=True)
    vehicle_plate = fields.Char(
        related='vehicle_id.license_plate', string='Placa', store=True, readonly=True)
    driver_id = fields.Many2one(
        'res.partner', string='Conductor', required=True, ondelete='restrict', index=True,
        domain=[('is_driver', '=', True)])
    state = fields.Selection(
        ESTADOS_RUTA, string='Estado', default='borrador', required=True,
        index=True, copy=False)
    planned_distance_km = fields.Float(string='Distancia planificada (km)', digits=(10, 2))
    planned_duration_min = fields.Float(string='Duración planificada (min)', digits=(10, 1))
    optimization_version = fields.Char(string='Versión del optimizador')
    distance_source = fields.Char(
        string='Fuente de distancias',
        help='osrm o estimado_haversine: indica si las distancias son por carretera o una estimación.')
    confirmed_load_at = fields.Datetime(string='Carga confirmada', copy=False)
    started_at = fields.Datetime(string='Inicio del recorrido', copy=False)
    finished_at = fields.Datetime(string='Fin del recorrido', copy=False)
    interrupt_reason = fields.Text(string='Motivo de cancelación o interrupción', copy=False)
    stop_ids = fields.One2many('logistica.ruta.parada', 'route_id', string='Paradas')

    total_stops = fields.Integer(string='Paradas', compute='_compute_metricas')
    delivered_stops = fields.Integer(string='Entregadas', compute='_compute_metricas')
    failed_stops = fields.Integer(string='No entregadas', compute='_compute_metricas')
    pending_stops = fields.Integer(string='Pendientes', compute='_compute_metricas')
    progress = fields.Float(string='Avance (%)', compute='_compute_metricas')

    @api.depends('stop_ids.state')
    def _compute_metricas(self):
        for ruta in self:
            total = len(ruta.stop_ids)
            entregadas = len(ruta.stop_ids.filtered(lambda s: s.state == 'entregado'))
            fallidas = len(ruta.stop_ids.filtered(lambda s: s.state == 'no_entregado'))
            ruta.total_stops = total
            ruta.delivered_stops = entregadas
            ruta.failed_stops = fallidas
            ruta.pending_stops = total - entregadas - fallidas
            ruta.progress = ((entregadas + fallidas) / total * 100.0) if total else 0.0

    # ------------------------------------------------------------------
    # Creación, escritura y borrado
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('state', 'borrador') != 'borrador':
                raise UserError(_('El estado de la ruta solo se cambia mediante sus acciones.'))
            if not vals.get('name') or vals['name'] == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('logistica.ruta') or _('Nuevo')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            protegidos = CAMPOS_PROTEGIDOS.intersection(vals)
            if protegidos:
                raise UserError(_('Los campos %s de la ruta no se modifican manualmente.') % (
                    ', '.join(sorted(protegidos))))
        if 'stop_ids' in vals:
            # Regla §1.1 #7 y §8.4: solo una ruta en borrador admite paradas nuevas o cambios.
            for ruta in self:
                if ruta.state != 'borrador':
                    raise UserError(_(
                        'No se pueden cambiar las paradas de la ruta %s: ya no está en borrador. '
                        'Los pedidos nuevos quedan para la siguiente ruta.') % ruta.name)
        return super().write(vals)

    def unlink(self):
        for ruta in self:
            if ruta.state not in ('borrador', 'cancelada') and not self.env.context.get('module_uninstall'):
                raise UserError(_('Solo se pueden eliminar rutas en borrador o canceladas.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Permisos y bloqueo
    # ------------------------------------------------------------------
    def assert_driver(self, user):
        """El usuario debe ser el conductor de la ruta (la comparación es por contacto)."""
        self.ensure_one()
        if not user or user.partner_id != self.driver_id:
            raise AccessError(_('Esta ruta no está asignada a su usuario.'))
        return True

    def _exigir_gestor(self):
        if not (self.env.su or self.env.user.has_group('fleet.fleet_group_manager')):
            raise AccessError(_('Solo un gestor de flota puede realizar esta acción.'))

    def _exigir_actor(self):
        """Gestor de flota o conductor de la ruta."""
        self.ensure_one()
        if self.env.su or self.env.user.has_group('fleet.fleet_group_manager'):
            return
        self.assert_driver(self.env.user)

    def _bloquear(self):
        """Bloquea la fila para que un doble clic o reintento concurrente espere su turno."""
        self.ensure_one()
        self.flush_recordset(['state'])
        self.env.cr.execute('SELECT 1 FROM logistica_ruta WHERE id = %s FOR UPDATE', (self.id,))
        self.invalidate_recordset(['state'])

    def _transicionar(self, desde, hacia, **extra):
        """Único punto de cambio de estado de la ruta."""
        self.ensure_one()
        self._bloquear()
        esperados = {desde} if isinstance(desde, str) else set(desde)
        etiquetas = dict(ESTADOS_RUTA)
        if self.state == hacia:
            raise UserError(_('Evento ya registrado: la ruta %s ya está en estado «%s».') % (
                self.name, etiquetas[hacia]))
        if self.state not in esperados:
            raise UserError(_('Transición no permitida: la ruta %s está «%s» y se pidió pasar a «%s».') % (
                self.name, etiquetas[self.state], etiquetas[hacia]))
        self.sudo().write(dict(extra, state=hacia))

    def _entregas(self):
        return self.stop_ids.sorted('sequence').mapped('entrega_id')

    # ------------------------------------------------------------------
    # Acciones (§8.3)
    # ------------------------------------------------------------------
    def action_aprobar_plan(self):
        """borrador → planificada. Las entregas pasan a «asignado»."""
        for ruta in self:
            ruta._exigir_gestor()
            if not ruta.stop_ids:
                raise UserError(_('La ruta %s no tiene paradas.') % ruta.name)
            if not ruta.vehicle_id or not ruta.driver_id:
                raise UserError(_('La ruta %s necesita vehículo y conductor.') % ruta.name)
            ruta._transicionar('borrador', 'planificada')
            for entrega in ruta._entregas():
                entrega.action_marcar_asignado(route_id=ruta.id)
        return True

    def action_confirmar_carga(self):
        """planificada → carga_confirmada (conductor o gestor)."""
        for ruta in self:
            ruta._exigir_actor()
            if not ruta.stop_ids:
                raise UserError(_('La ruta %s no tiene paradas: no hay carga que confirmar.') % ruta.name)
            ruta._transicionar('planificada', 'carga_confirmada', confirmed_load_at=fields.Datetime.now())
            for entrega in ruta._entregas():
                entrega._registrar_evento('carga_confirmada')
        return True

    def action_iniciar_recorrido(self):
        """carga_confirmada → en_recorrido. Desde aquí la ruta no admite pedidos nuevos."""
        for ruta in self:
            ruta._exigir_actor()
            otras = self.sudo().search_count([
                ('vehicle_id', '=', ruta.vehicle_id.id), ('state', '=', 'en_recorrido'),
                ('id', '!=', ruta.id)])
            if otras:
                raise UserError(_('El vehículo %s ya tiene otra ruta en recorrido.') % ruta.vehicle_plate)
            ruta._transicionar('carga_confirmada', 'en_recorrido', started_at=fields.Datetime.now())
            for entrega in ruta._entregas():
                entrega.action_marcar_en_recorrido()
        return True

    def action_cerrar(self):
        """en_recorrido → cerrada. Los fallidos no cuentan como entregados."""
        for ruta in self:
            ruta._exigir_actor()
            ruta._bloquear()
            pendientes = len(ruta.stop_ids.filtered(lambda s: s.state == 'pendiente'))
            if ruta.state == 'en_recorrido' and pendientes:
                raise UserError(_(
                    'Aún quedan %d parada(s) por registrar como entregadas o no entregadas.') % pendientes)
            ruta._transicionar('en_recorrido', 'cerrada', finished_at=fields.Datetime.now())
            for parada in ruta.stop_ids.filtered(lambda s: s.state == 'no_entregado'):
                parada.entrega_id._transicionar('no_entregado', 'pendiente_reprogramacion')
        return True

    def action_cancelar(self, motivo=None):
        """borrador, planificada o carga_confirmada → cancelada. Las entregas vuelven a «preparado»."""
        for ruta in self:
            ruta._exigir_gestor()
            estado_previo = ruta.state
            ruta._transicionar(
                ('borrador', 'planificada', 'carga_confirmada'), 'cancelada',
                interrupt_reason=motivo or False)
            if estado_previo != 'borrador':
                for entrega in ruta._entregas():
                    entrega._transicionar('asignado', 'preparado')
                    entrega._registrar_evento('desasignado', notes=motivo or _('Ruta cancelada'))
                    entrega.sudo().write({'route_id': 0})
        return True

    def action_interrumpir(self, motivo):
        """en_recorrido → interrumpida. Lo no entregado queda pendiente de reprogramación."""
        if not motivo or not str(motivo).strip():
            raise UserError(_('Debe indicar el motivo de la interrupción.'))
        for ruta in self:
            ruta._exigir_actor()
            ruta._transicionar(
                'en_recorrido', 'interrumpida', interrupt_reason=motivo,
                finished_at=fields.Datetime.now())
            for parada in ruta.stop_ids:
                entrega = parada.entrega_id
                if entrega.state == 'en_recorrido':
                    entrega._transicionar('en_recorrido', 'pendiente_reprogramacion')
                    entrega._registrar_evento('ruta_interrumpida', notes=motivo)
        return True

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def _abrir_motivo(self, accion):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Motivo'),
            'res_model': 'logistica.ruta.motivo',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ruta_id': self.id, 'default_accion': accion},
        }

    def action_abrir_cancelar(self):
        return self._abrir_motivo('cancelar')

    def action_abrir_interrumpir(self):
        return self._abrir_motivo('interrumpir')

    def action_open_google_maps_route(self):
        self.ensure_one()
        origen = '%s,%s' % (self.bodega_id.latitude, self.bodega_id.longitude)
        puntos = ['%s,%s' % (p.latitude, p.longitude) for p in self.stop_ids.sorted('sequence')
                  if p.latitude or p.longitude]
        if not puntos:
            raise UserError(_('Las paradas no tienen coordenadas registradas.'))
        url = 'https://www.google.com/maps/dir/?api=1&origin=%s&destination=%s' % (origen, puntos[-1])
        if len(puntos) > 1:
            url += '&waypoints=' + '|'.join(puntos[:-1])
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}
