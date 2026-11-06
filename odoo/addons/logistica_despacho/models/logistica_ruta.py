# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class LogisticaRuta(models.Model):
    _name = 'logistica.ruta'
    _description = 'Ruta de Despacho y Entrega'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Código de Ruta',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Borrador')
    )
    date = fields.Date(
        string='Fecha de Despacho',
        required=True,
        default=fields.Date.context_today
    )
    warehouse_partner_id = fields.Many2one(
        'res.partner',
        string='Bodega Central de Salida',
        required=True,
        help='Punto de origen fijo desde el cual parte el vehículo.'
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='Vehículo Asignado',
        required=True
    )
    driver_id = fields.Many2one(
        'res.partner',
        string='Conductor Asignado',
        required=True,
        domain=[('is_driver', '=', True)]
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmada / Carga Lista'),
        ('in_progress', 'En Ruta / En Tránsito'),
        ('done', 'Finalizada'),
        ('cancel', 'Cancelada'),
    ], string='Estado de Ruta', default='draft', readonly=True)

    start_datetime = fields.Datetime(string='Hora de Salida', readonly=True)
    end_datetime = fields.Datetime(string='Hora de Retorno', readonly=True)

    stop_ids = fields.One2many(
        'logistica.ruta.parada',
        'route_id',
        string='Paradas de Entrega'
    )

    total_stops = fields.Integer(string='Total Paradas', compute='_compute_stop_metrics')
    delivered_stops = fields.Integer(string='Entregadas', compute='_compute_stop_metrics')
    failed_stops = fields.Integer(string='No Entregadas', compute='_compute_stop_metrics')
    pending_stops = fields.Integer(string='Pendientes', compute='_compute_stop_metrics')
    progress = fields.Float(string='% Progreso', compute='_compute_stop_metrics')

    @api.depends('stop_ids', 'stop_ids.state')
    def _compute_stop_metrics(self):
        for route in self:
            total = len(route.stop_ids)
            delivered = sum(1 for s in route.stop_ids if s.state == 'delivered')
            failed = sum(1 for s in route.stop_ids if s.state == 'failed')
            pending = sum(1 for s in route.stop_ids if s.state == 'pending')
            route.total_stops = total
            route.delivered_stops = delivered
            route.failed_stops = failed
            route.pending_stops = pending
            route.progress = ((delivered + failed) / total * 100.0) if total > 0 else 0.0

    @api.model
    def create(self, vals):
        if vals.get('name', _('Borrador')) == _('Borrador'):
            seq_val = self.env['ir.sequence'].next_by_code('logistica.ruta') or _('RUTA/%s') % fields.Date.today()
            vals['name'] = seq_val
        return super(LogisticaRuta, self).create(vals)

    def write(self, vals):
        # Regla de negocio acordada: si la ruta ya está en tránsito, no permitir agregar nuevas paradas
        for route in self:
            if route.state in ('in_progress', 'done') and 'stop_ids' in vals:
                # Comprobar si se intenta agregar paradas nuevas
                for cmd in vals['stop_ids']:
                    if isinstance(cmd, (list, tuple)) and cmd[0] == 0:
                        raise UserError(_('No se pueden agregar nuevos pedidos a una ruta que ya está en marcha o finalizada.'))
        return super(LogisticaRuta, self).write(vals)

    def action_confirm(self):
        for route in self:
            if not route.stop_ids:
                raise UserError(_('Debe agregar al menos una parada de entrega antes de confirmar la ruta.'))
            route.state = 'confirmed'
            # delivery_status eliminado (Task 5); Task 8 reescribe el módulo

    def action_start_route(self):
        for route in self:
            if route.state != 'confirmed':
                raise UserError(_('Solo se puede iniciar una ruta que esté en estado Confirmada.'))
            route.write({
                'state': 'in_progress',
                'start_datetime': fields.Datetime.now(),
            })
            # delivery_status eliminado (Task 5); Task 8 reescribe el módulo

    def action_finish_route(self):
        for route in self:
            if route.state != 'in_progress':
                raise UserError(_('Solo se puede finalizar una ruta que esté En Tránsito.'))
            # Verificar si hay paradas pendientes
            if route.pending_stops > 0:
                raise UserError(_('Aún quedan %d parada(s) pendientes de registrar como Entregada o No Entregada.') % route.pending_stops)
            route.write({
                'state': 'done',
                'end_datetime': fields.Datetime.now(),
            })

    def action_cancel(self):
        for route in self:
            if route.state == 'done':
                raise UserError(_('No se puede cancelar una ruta finalizada.'))
            route.state = 'cancel'
            # delivery_status eliminado (Task 5); Task 8 reescribe el módulo

    def action_open_google_maps_route(self):
        self.ensure_one()
        # Generar ruta en Google Maps desde origen pasando por todas las paradas
        origin = f"{self.warehouse_partner_id.delivery_latitude},{self.warehouse_partner_id.delivery_longitude}"
        waypoints = [f"{stop.latitude},{stop.longitude}" for stop in self.stop_ids if stop.latitude and stop.longitude]
        if not waypoints:
            raise UserError(_('Las paradas no tienen coordenadas registradas.'))
        destination = waypoints[-1]
        via_points = "|".join(waypoints[:-1])
        url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}"
        if via_points:
            url += f"&waypoints={via_points}"
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
