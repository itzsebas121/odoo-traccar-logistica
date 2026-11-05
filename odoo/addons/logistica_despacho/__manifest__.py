# -*- coding: utf-8 -*-
{
    'name': 'Logística Despacho - Planificación de Rutas',
    'version': '16.0.1.0.0',
    'category': 'Inventory/Logistics',
    'summary': 'Planificación y gestión de rutas de despacho, asignación de flota y confirmación de entregas',
    'description': """
Módulo de Rutas y Despacho
==========================
- Agrupación de pedidos de venta en rutas de entrega.
- Asignación de vehículos (fleet.vehicle) y conductores (res.partner).
- Origen desde Bodega Central con orden de visitas programado.
- Estados de ruta: Borrador -> Confirmado -> En Tránsito -> Finalizado.
- Registro de resultado por parada: Entregado o No Entregado con motivo.
- Control de cierre de ruta al iniciar viaje (regla de negocio acordada).
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'fleet',
        'sale_management',
        'logistica_base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/logistica_ruta_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

