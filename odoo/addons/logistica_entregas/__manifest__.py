# -*- coding: utf-8 -*-
{
    'name': 'Logística - Entregas',
    'version': '16.0.1.0.0',
    'category': 'Inventory/Logistics',
    'summary': 'Entrega logística por pedido: estados, eventos auditables y seguimiento',
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': ['base', 'sale_management', 'logistica_base'],
    'data': [
        'security/ir.model.access.csv',
        'views/logistica_entrega_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
