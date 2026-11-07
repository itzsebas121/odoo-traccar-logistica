# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.logistica_entregas.models.logistica_entrega_evento import MOTIVOS_NO_ENTREGA

from .logistica_ruta import ESTADOS_ACTIVOS

CAMPOS_PROTEGIDOS = frozenset({
    'route_id', 'entrega_id', 'state', 'arrival_candidate_at', 'actual_arrival_at', 'completed_at'})


class LogisticaRutaParada(models.Model):
    _name = 'logistica.ruta.parada'
    _description = 'Parada de Ruta'
    _order = 'route_id, sequence, id'

    route_id = fields.Many2one(
        'logistica.ruta', string='Ruta', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Orden', default=10)
    entrega_id = fields.Many2one(
        'logistica.entrega', string='Entrega', required=True, ondelete='restrict', index=True,
        domain=[('state', '=', 'preparado')])
    sale_order_id = fields.Many2one(related='entrega_id.sale_order_id', string='Pedido', readonly=True)
    partner_id = fields.Many2one(related='entrega_id.partner_id', string='Cliente', readonly=True)
    destination_address = fields.Char(related='entrega_id.destination_address', string='Dirección', readonly=True)
    latitude = fields.Float(related='entrega_id.latitude', string='Latitud', digits=(10, 7), readonly=True)
    longitude = fields.Float(related='entrega_id.longitude', string='Longitud', digits=(10, 7), readonly=True)
    state = fields.Selection(
        [('pendiente', 'Pendiente'), ('entregado', 'Entregado'), ('no_entregado', 'No entregado')],
        string='Resultado', default='pendiente', required=True, index=True, copy=False)
    arrival_candidate_at = fields.Datetime(string='Posible llegada (GPS)', copy=False)
    actual_arrival_at = fields.Datetime(string='Llegada registrada', copy=False)
    completed_at = fields.Datetime(string='Resultado registrado', copy=False)
    failed_reason = fields.Selection(MOTIVOS_NO_ENTREGA, string='Motivo de no entrega')
    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('ruta_entrega_uniq', 'unique(route_id, entrega_id)',
         'La entrega ya está en esta ruta.'),
    ]

    # ------------------------------------------------------------------
    # Creación, escritura y borrado
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Ruta = self.env['logistica.ruta']
        Entrega = self.env['logistica.entrega']
        for vals in vals_list:
            ruta = Ruta.browse(vals.get('route_id')).exists()
            if ruta and ruta.state != 'borrador':
                raise UserError(_(
                    'No se pueden agregar paradas a la ruta %s: ya no está en borrador. '
                    'El pedido nuevo queda para la siguiente ruta.') % ruta.name)
            entrega = Entrega.sudo().browse(vals.get('entrega_id')).exists()
            if entrega:
                if entrega.state != 'preparado':
                    raise UserError(_(
                        'La entrega %s no está preparada para despacho.') % entrega.name)
                en_otra = self.sudo().search_count([
                    ('entrega_id', '=', entrega.id),
                    ('route_id.state', 'in', ESTADOS_ACTIVOS),
                    ('route_id', '!=', ruta.id)])
                if en_otra:
                    raise UserError(_('La entrega %s ya está en otra ruta activa.') % entrega.name)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            protegidos = CAMPOS_PROTEGIDOS.intersection(vals)
            if protegidos:
                raise UserError(_('Los campos %s de la parada no se modifican manualmente.') % (
                    ', '.join(sorted(protegidos))))
            if 'sequence' in vals and any(p.route_id.state != 'borrador' for p in self):
                raise UserError(_('El orden de las paradas solo se cambia en una ruta en borrador.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('module_uninstall'):
            for parada in self:
                if parada.route_id.state != 'borrador':
                    raise UserError(_('Solo se pueden quitar paradas de una ruta en borrador.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Acciones sobre la parada (delegan en la entrega)
    # ------------------------------------------------------------------
    def _bloquear(self):
        self.ensure_one()
        self.flush_recordset(['state', 'actual_arrival_at'])
        self.env.cr.execute('SELECT 1 FROM logistica_ruta_parada WHERE id = %s FOR UPDATE', (self.id,))
        self.invalidate_recordset(['state', 'actual_arrival_at'])

    def _preparar_registro(self):
        """Valida actor, ruta en recorrido y parada pendiente. Bloquea la fila contra doble clic."""
        self.ensure_one()
        ruta = self.route_id
        ruta._exigir_actor()
        if ruta.state != 'en_recorrido':
            raise UserError(_('La ruta %s no está en recorrido.') % ruta.name)
        self._bloquear()
        if self.state != 'pendiente':
            raise UserError(_('Evento ya registrado: la parada ya fue marcada como «%s».') % dict(
                self._fields['state'].selection)[self.state])

    def action_marcar_llegada(self):
        """Llegada registrada por una persona. No cambia el estado de la entrega."""
        for parada in self:
            parada._preparar_registro()
            if parada.actual_arrival_at:
                raise UserError(_('Evento ya registrado: la llegada de esta parada ya fue anotada.'))
            parada.entrega_id._registrar_evento_gps('llegada_registrada')
            parada.sudo().write({'actual_arrival_at': fields.Datetime.now()})
        return True

    def action_marcar_entregado(self):
        for parada in self:
            parada._preparar_registro()
            parada.entrega_id.action_marcar_entregado()
            parada.sudo().write({
                'state': 'entregado', 'completed_at': fields.Datetime.now(), 'failed_reason': False})
        return True

    def action_marcar_no_entregado(self, motivo, notas=None):
        if not motivo or motivo not in dict(MOTIVOS_NO_ENTREGA):
            raise ValidationError(_('Debe indicar un motivo de no entrega válido.'))
        for parada in self:
            parada._preparar_registro()
            parada.entrega_id.action_marcar_no_entregado(motivo, notas)
            parada.sudo().write({
                'state': 'no_entregado', 'completed_at': fields.Datetime.now(),
                'failed_reason': motivo, 'notes': notas or False})
        return True

    # Botones de la vista: leen el motivo escrito en la propia fila.
    def action_ui_no_entregado(self):
        for parada in self:
            parada.action_marcar_no_entregado(parada.failed_reason, parada.notes)
        return True

    def action_open_navigation(self):
        self.ensure_one()
        if not (self.latitude or self.longitude):
            raise UserError(_('Esta parada no tiene coordenadas válidas.'))
        url = 'https://www.google.com/maps/dir/?api=1&destination=%s,%s' % (self.latitude, self.longitude)
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}
