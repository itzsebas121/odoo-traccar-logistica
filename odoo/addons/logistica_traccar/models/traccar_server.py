# -*- coding: utf-8 -*-
import base64
import json
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TraccarServer(models.Model):
    _name = 'traccar.server'
    _description = 'Configuración de Servidor Traccar GPS'

    name = fields.Char(string='Nombre de Servidor', required=True, default='Traccar Principal')
    base_url = fields.Char(
        string='URL del Servidor Traccar',
        required=True,
        default='http://traccar:8082',
        help='URL base interna o externa de Traccar (ejemplo: http://traccar:8082)'
    )
    auth_type = fields.Selection([
        ('basic', 'Autenticación Básica (Usuario y Contraseña)'),
        ('token', 'Token de Sesión / API Bearer'),
    ], string='Tipo de Autenticación', default='basic', required=True)

    username = fields.Char(string='Usuario / Correo Traccar', default='admin@logistica.local')
    password = fields.Char(string='Contraseña / Token Traccar')

    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Sin Verificar'),
        ('connected', 'Conectado'),
        ('error', 'Error de Conexión'),
    ], string='Estado de Conexión', default='draft', readonly=True)

    last_sync_date = fields.Datetime(string='Última Sincronización', readonly=True)
    last_error_message = fields.Text(string='Detalle del Último Error', readonly=True)

    device_ids = fields.One2many('traccar.device', 'server_id', string='Dispositivos Vinculados')
    device_count = fields.Integer(string='Total Dispositivos', compute='_compute_device_count')

    @api.depends('device_ids')
    def _compute_device_count(self):
        for rec in self:
            rec.device_count = len(rec.device_ids)

    def _get_auth_headers(self):
        self.ensure_one()
        headers = {'Accept': 'application/json'}
        if self.auth_type == 'basic':
            if not self.username or not self.password:
                raise UserError(_('Debe configurar usuario y contraseña para la autenticación básica.'))
            raw_credentials = f"{self.username}:{self.password}"
            encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
            headers['Authorization'] = f"Basic {encoded}"
        elif self.auth_type == 'token':
            if not self.password:
                raise UserError(_('Debe configurar el token de autorización.'))
            headers['Authorization'] = f"Bearer {self.password}"
        return headers

    def action_test_connection(self):
        self.ensure_one()
        url = self.base_url.rstrip('/') + '/api/server'
        headers = self._get_auth_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                version = data.get('version', 'Desconocida')
                self.write({
                    'state': 'connected',
                    'last_error_message': False,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Conexión Exitosa'),
                        'message': _('Conectado con éxito a Traccar Server v%s') % version,
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                self.write({
                    'state': 'error',
                    'last_error_message': error_msg,
                })
                raise UserError(_('Fallo de conexión a Traccar: %s') % error_msg)
        except requests.RequestException as e:
            error_msg = str(e)
            self.write({
                'state': 'error',
                'last_error_message': error_msg,
            })
            raise UserError(_('No se pudo establecer conexión con Traccar: %s') % error_msg)

    def action_sync_devices(self):
        self.ensure_one()
        url = self.base_url.rstrip('/') + '/api/devices'
        headers = self._get_auth_headers()
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                raise UserError(_('Error al consultar dispositivos: HTTP %s') % response.status_code)
            devices_data = response.json()
            device_model = self.env['traccar.device']
            synced_count = 0
            for item in devices_data:
                traccar_id = item.get('id')
                unique_id = str(item.get('uniqueId', ''))
                name = item.get('name') or unique_id
                status = item.get('status') or 'unknown'
                last_update = item.get('lastUpdate')

                existing = device_model.search([
                    ('server_id', '=', self.id),
                    ('traccar_id', '=', traccar_id)
                ], limit=1)

                vals = {
                    'name': name,
                    'unique_id': unique_id,
                    'status': status,
                    'server_id': self.id,
                }
                if existing:
                    existing.write(vals)
                else:
                    vals['traccar_id'] = traccar_id
                    device_model.create(vals)
                synced_count += 1

            self.write({
                'last_sync_date': fields.Datetime.now(),
                'state': 'connected',
                'last_error_message': False,
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sincronización Completada'),
                    'message': _('Se sincronizaron %d dispositivo(s) desde Traccar.') % synced_count,
                    'sticky': False,
                    'type': 'success',
                }
            }
        except requests.RequestException as e:
            self.write({
                'state': 'error',
                'last_error_message': str(e),
            })
            raise UserError(_('Error al sincronizar dispositivos: %s') % str(e))

