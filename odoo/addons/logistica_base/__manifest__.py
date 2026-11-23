# -*- coding: utf-8 -*-
{
    'name': 'Logística Base - Coordenadas y Zonas',
    'version': '16.0.1.3.0',
    'category': 'Inventory/Logistics',
    'summary': 'Geolocalización de contactos, zonas de entrega y pedidos de venta',
    'description': """
Módulo Base de Logística
========================
- Agrega coordenadas geográficas (Latitud, Longitud) a Contactos (res.partner).
- Agrega campo de Zona de Entrega (Centro, Ficoa, Huachi, Izamba, etc.).
- Hereda las coordenadas del cliente al Pedido de Venta (sale.order).
- Permite editar y validar el punto de entrega en la orden de venta.
- Vistas de formulario integradas con enlace directo para ver en Google Maps / OpenStreetMap.
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'sale_management',
        'account',
        'fleet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/logistica_zona_data.xml',
        'data/logistica_config_data.xml',
        'views/logistica_config_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'logistica_base/static/src/css/shadcn_backend.css',
            'logistica_base/static/src/css/bitacora_systray.css',
            'logistica_base/static/src/js/bitacora_sidebar.js',
            'logistica_base/static/src/xml/bitacora_navbar.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

