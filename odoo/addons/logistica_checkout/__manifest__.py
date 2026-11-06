# -*- coding: utf-8 -*-
{
    'name': 'Logística - Checkout y seguimiento público',
    'version': '16.0.1.0.0',
    'category': 'Website/Website',
    'summary': 'Selector de destino en mapa, confirmación automática de prueba y seguimiento por token',
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': ['website_sale', 'payment_custom', 'logistica_entregas'],
    'data': [
        'views/logistica_config_views.xml',
        'views/checkout_templates.xml',
        'views/confirmation_templates.xml',
        'views/tracking_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
