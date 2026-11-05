# -*- coding: utf-8 -*-
"""
Script de Seeds Reproducibles
Puebla datos base para pruebas de logística:
- Bodega Central (origen de todas las rutas)
- Marcas y modelos de vehículos de flota
- Dispositivos GPS Traccar de prueba
- Vehículos vinculados
"""
import os
import sys
import odoo
from odoo import api, SUPERUSER_ID

db_user = os.environ.get('USER', 'odoo')
db_password = os.environ.get('PASSWORD', '')
db_host = os.environ.get('HOST', 'db')
db_port = os.environ.get('PORT', '5432')
db_name = os.environ.get('ODOO_DB_NAME', 'logistica_dev')

odoo.tools.config.parse_config([
    '--db_host=' + db_host,
    '--db_port=' + db_port,
    '--db_user=' + db_user,
    '--db_password=' + db_password,
    '-d', db_name
])

registry = odoo.registry(db_name)
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})

    print("=== Sembrando Datos de Prueba (Seeds) ===")

    # 1. Bodega Principal
    warehouse = env['res.partner'].search([('name', '=', 'Bodega Central de Despacho')], limit=1)
    if not warehouse:
        warehouse = env['res.partner'].create({
            'name': 'Bodega Central de Despacho',
            'street': 'Calle 100 # 15-20',
            'city': 'Bogotá',
            'is_company': True,
            'comment': 'Punto de partida único de la flota según reglas de negocio.'
        })
        print("+ Creado Contacto Bodega Central ID:", warehouse.id)
    else:
        print("  Bodega Central ya existe ID:", warehouse.id)

    # 2. Servidor Traccar
    server = env['traccar.server'].search([('base_url', '=', 'http://traccar:8082')], limit=1)
    if not server:
        server = env['traccar.server'].create({
            'name': 'Servidor Traccar Local',
            'base_url': 'http://traccar:8082',
            'auth_type': 'basic',
            'username': 'admin@logistica.local',
            'password': 'traccar_admin_pass_dev2026',
        })
        print("+ Servidor Traccar configurado ID:", server.id)

    # 3. Marcas y Modelos
    brand = env['fleet.vehicle.model.brand'].search([('name', '=', 'Hino')], limit=1)
    if not brand:
        brand = env['fleet.vehicle.model.brand'].create({'name': 'Hino'})

    model = env['fleet.vehicle.model'].search([('name', '=', 'Dutro 300'), ('brand_id', '=', brand.id)], limit=1)
    if not model:
        model = env['fleet.vehicle.model'].create({'name': 'Dutro 300', 'brand_id': brand.id})

    # 4. Flota de Vehículos
    vehicles_data = [
        {'plate': 'LOG-001', 'vin': 'HINO300-2026-001'},
        {'plate': 'LOG-002', 'vin': 'HINO300-2026-002'},
    ]
    for vd in vehicles_data:
        veh = env['fleet.vehicle'].search([('license_plate', '=', vd['plate'])], limit=1)
        if not veh:
            veh = env['fleet.vehicle'].create({
                'model_id': model.id,
                'license_plate': vd['plate'],
                'vin_sn': vd['vin'],
            })
            print("+ Vehículo creado:", vd['plate'])
        else:
            print("  Vehículo existente:", vd['plate'])

    cr.commit()
    print("=== Seeds aplicados correctamente ===")

