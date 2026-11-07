# -*- coding: utf-8 -*-
{
    'name': 'Logística Conductor - Portal móvil',
    'version': '16.0.1.0.0',
    'category': 'Inventory/Logistics',
    'summary': 'Vista móvil restringida para que el conductor confirme carga, recorra paradas y registre entregas',
    'description': """
Portal del conductor
====================
- Grupo «Conductor de reparto» con reglas de registro: solo ve sus rutas, paradas y entregas.
- Confirmar carga, iniciar recorrido, registrar llegada, entregado y no entregado con motivo.
- Un doble clic no duplica eventos: la segunda petición se rechaza con 409.
- Sin acceso a la vista de administración.
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': ['logistica_despacho'],
    'data': [
        'security/security.xml',
        'views/conductor_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
