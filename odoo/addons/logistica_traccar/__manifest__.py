# -*- coding: utf-8 -*-
{
    'name': 'Logística Traccar - Rastreo GPS',
    'version': '16.0.1.1.0',
    'category': 'Inventory/Logistics',
    'summary': 'Integración y sincronización de vehículos Odoo con Traccar GPS Server',
    'description': """
Módulo de Integración con Traccar GPS
=====================================
Permite:
- Configurar servidores Traccar y autenticación mediante API REST.
- Probar conectividad interna entre Odoo y Traccar.
- Sincronizar dispositivos GPS registrados en Traccar.
- Vincular vehículos de Flota (fleet.vehicle) con dispositivos GPS Traccar.
- Consultar el estado operativo y posiciones geográficas de los vehículos.
    """,
    'author': 'Equipo Logística Inteligente',
    'website': 'https://github.com/sebas/odoo-traccar-logistica',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'fleet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/traccar_cron.xml',
        'views/traccar_server_views.xml',
        'views/traccar_device_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

