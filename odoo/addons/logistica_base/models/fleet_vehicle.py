# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    logistica_capacidad = fields.Integer(
        string='Capacidad (bultos)', default=10,
        help='1 entrega = 1 bulto.')

    @api.constrains('logistica_capacidad')
    def _check_capacidad(self):
        for rec in self:
            if rec.logistica_capacidad < 0:
                raise ValidationError(_('La capacidad del vehículo no puede ser negativa.'))

    # Con el contexto «logistica_con_conductor» (pantallas de despacho) el vehículo se muestra con su conductor:
    # «<placa> · <conductor> (<modelo>)». En el resto de Odoo el nombre no cambia.
    def name_get(self):
        if not self.env.context.get('logistica_con_conductor'):
            return super().name_get()
        salida = []
        for vehiculo in self:
            modelo = ' '.join(p for p in (vehiculo.model_id.brand_id.name, vehiculo.model_id.name) if p)
            nombre = vehiculo.license_plate or vehiculo.name
            if vehiculo.driver_id:
                nombre = '%s · %s' % (nombre, vehiculo.driver_id.name)
            else:
                nombre = _('%s · sin conductor') % nombre
            if modelo:
                nombre = '%s (%s)' % (nombre, modelo)
            salida.append((vehiculo.id, nombre))
        return salida

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        # En despacho también se busca por el nombre del conductor.
        if name and self.env.context.get('logistica_con_conductor'):
            args = list(args or []) + ['|', '|', ('license_plate', operator, name), ('name', operator, name),
                                       ('driver_id.name', operator, name)]
            return self._search(args, limit=limit, access_rights_uid=name_get_uid)
        return super()._name_search(name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid)
