# -*- coding: utf-8 -*-
{
    'name': 'Logística Analítica IA - Destinos probables',
    'version': '16.0.1.0.0',
    'category': 'Inventory/Logistics',
    'summary': 'Consulta de destinos probables con el modelo predictivo y ruta vial sugerida',
    'description': """
Analítica con IA
================
- Asistente «Predecir destino»: vehículo, fecha, hora y zona de origen.
- Muestra destino probable, alternativas con probabilidades y la ruta en un mapa.
- Cada consulta queda guardada como auditoría; no se puede editar ni borrar.
- Métricas del modelo: accuracy, F1, matriz de confusión y comparación con el predictor base.
- No asigna pedidos ni modifica entregas o rutas: solo apoya la decisión de la persona.
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': ['logistica_traccar', 'logistica_despacho'],
    'data': [
        'security/ir.model.access.csv',
        'views/prediccion_views.xml',
        'views/mapa_templates.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
