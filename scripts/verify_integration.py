# -*- coding: utf-8 -*-
import os
import sys
import odoo
from odoo import api, SUPERUSER_ID

db_user = os.environ.get('USER', 'odoo')
db_password = os.environ.get('PASSWORD', '')
db_host = os.environ.get('HOST', 'db')
db_port = os.environ.get('PORT', '5432')
db_name = 'logistica_dev'

print("[1/5] Conectando con Odoo ORM en la base de datos", db_name)
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

    # 1. Configurar Servidor Traccar
    print("[2/5] Verificando configuración del servidor Traccar...")
    server = env['traccar.server'].search([('base_url', '=', 'http://traccar:8082')], limit=1)
    if not server:
        server = env['traccar.server'].create({
            'name': 'Servidor Traccar Local',
            'base_url': 'http://traccar:8082',
            'auth_type': 'basic',
            'username': 'admin@logistica.local',
            'password': 'traccar_admin_pass_dev2026',
        })
    print("      Servidor configurado ID:", server.id, "| Nombre:", server.name)

    # 2. Probar conexión Odoo -> Traccar
    print("[3/5] Ejecutando action_test_connection()...")
    res_test = server.action_test_connection()
    print("      Estado del servidor:", server.state)
    print("      Mensaje:", res_test['params']['message'])

    # 3. Sincronizar dispositivos
    print("[4/5] Ejecutando action_sync_devices()...")
    res_sync = server.action_sync_devices()
    print("      Total dispositivos sincronizados:", server.device_count)
    for dev in server.device_ids:
        print("      -> Dispositivo:", dev.name, "| UniqueID:", dev.unique_id, "| Estado:", dev.status)

    # 4. Vincular con vehículo en fleet.vehicle
    print("[5/5] Vinculando dispositivo con vehículo de flota...")
    device = server.device_ids[0]
    brand = env['fleet.vehicle.model.brand'].search([('name', '=', 'Hino')], limit=1)
    if not brand:
        brand = env['fleet.vehicle.model.brand'].create({'name': 'Hino'})
    model_obj = env['fleet.vehicle.model'].search([('name', '=', 'Dutro 300')], limit=1)
    if not model_obj:
        model_obj = env['fleet.vehicle.model'].create({'name': 'Dutro 300', 'brand_id': brand.id})

    vehicle = env['fleet.vehicle'].search([('license_plate', '=', 'LOG-001')], limit=1)
    if not vehicle:
        vehicle = env['fleet.vehicle'].create({
            'model_id': model_obj.id,
            'license_plate': 'LOG-001',
            'traccar_device_id': device.id,
        })
    else:
        vehicle.write({'traccar_device_id': device.id})

    # 5. Obtener telemetría desde el vehículo
    res_pos = vehicle.action_fetch_traccar_position()
    print("      Vehículo:", vehicle.display_name, "| Placa:", vehicle.license_plate)
    print("      Telemetría obtenida:")
    print("      - Latitud:", vehicle.traccar_latitude)
    print("      - Longitud:", vehicle.traccar_longitude)
    print("      - Velocidad:", vehicle.traccar_speed, "km/h")
    print("      - Fecha/Hora:", vehicle.traccar_position_time)

    cr.commit()
    print("\n>>> TODAS LAS PRUEBAS DE INTEGRACION ODOO <-> TRACCAR EXITOSAS <<<")

