# -*- coding: utf-8 -*-
{
    'name': 'Logística Despacho - Planificación de Rutas',
    'version': '16.0.2.0.0',
    'category': 'Inventory/Logistics',
    'summary': 'Planificación, aprobación, carga y ejecución de rutas de despacho',
    'description': """
Módulo de Rutas y Despacho
==========================
- Planificador que propone rutas desde la bodega con el servicio de optimización.
- Estados de ruta: borrador, planificada, carga confirmada, en recorrido, cerrada,
  cancelada e interrumpida.
- Una ruta iniciada no admite pedidos nuevos.
- Resultado por parada: entregado o no entregado con motivo; los fallidos no cuentan como entregados.
- Toda acción se apoya en la máquina de estados de la entrega (logistica_entregas).
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'fleet',
        'sale_management',
        'logistica_base',
        'logistica_entregas',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/logistica_ruta_views.xml',
        'views/logistica_planificador_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
