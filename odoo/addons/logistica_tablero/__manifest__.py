# -*- coding: utf-8 -*-
{
    'name': 'Logística - Tablero de indicadores',
    'version': '16.0.1.0.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Ventas, demanda por ubicación, pronóstico y operación desde el DWH, dentro de Odoo',
    'description': """
Tablero de indicadores
======================
- Las mismas secciones que el tablero del asistente: Resumen, Demanda (con mapa), Pronóstico y Operación.
- Filtros por periodo, zona, categoría, procedencia y conductor.
- Lee el DWH (vistas v_bi_*) con el rol de solo lectura dwh_ro: no toca los datos de Odoo.
- API JSON en /logistica/tablero/api/<sección> para gerentes de ventas o de flota.
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': ['logistica_base', 'spreadsheet_dashboard', 'sale_management', 'fleet'],
    'data': [
        'views/tablero_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'logistica_tablero/static/src/tablero/tablero.scss',
            'logistica_tablero/static/src/tablero/tablero.js',
            'logistica_tablero/static/src/tablero/tablero.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
