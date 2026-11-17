# -*- coding: utf-8 -*-
{
    'name': 'Logística - Datos de demostración',
    'version': '16.0.1.2.0',
    'summary': 'Carga el mercado de demostración (catálogo, clientes, historial de ventas, facturas y rutas)',
    'description': """
Mercado de demostración para Ambato (hasta Mocha): empresa en USD con plan contable genérico e IVA 0 % / 15 %,
catálogo con fotos, clientes con ubicación real, tres meses de pedidos entregados en rutas, facturas y pagos,
y los pedidos del día por despachar. Lo invoca seeds/seed.py con los datos de seeds/data.
    """,
    'category': 'Inventory/Delivery',
    'author': 'UTA',
    'license': 'LGPL-3',
    'depends': [
        'account', 'l10n_generic_coa', 'website_sale',
        'logistica_base', 'logistica_entregas', 'logistica_despacho', 'logistica_checkout', 'logistica_conductor',
    ],
    'data': [],
    'installable': True,
    'application': False,
}
