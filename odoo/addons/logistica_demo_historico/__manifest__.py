# -*- coding: utf-8 -*-
{
    'name': 'Logística - Histórico de demostración',
    'version': '16.0.1.0.0',
    'category': 'Inventory/Logistics',
    'summary': 'Registra días históricos (pedidos, rutas y entregas) con fechas pasadas para entrenar el ML',
    'description': """
Histórico de demostración
=========================
Solo para el entorno académico o de demostración. Lo usa ``seeds/historico.py``.

- ``logistica.demo.historico.registrar_dia(datos)``: crea y confirma los pedidos del día y recorre cada ruta
  con las acciones de negocio de siempre (aprobar, confirmar carga, iniciar, llegada, entregado o no entregado,
  cerrar). Después escribe las fechas históricas (pedido, entrega, eventos, ruta y paradas), que las acciones
  fijan en «ahora».
- Solo un administrador (grupo Ajustes) puede llamarlo. Es idempotente: un pedido con la misma referencia de
  cliente o una ruta con la misma clave no se repiten.
- No cambia ninguna regla de negocio: las transiciones de estado son las de logistica_entregas y
  logistica_despacho.
    """,
    'author': 'Equipo Logística Inteligente',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'logistica_base', 'logistica_entregas', 'logistica_despacho'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
