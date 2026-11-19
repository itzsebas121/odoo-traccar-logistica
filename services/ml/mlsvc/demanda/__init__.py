"""Pronostico de demanda de articulos por ubicacion (producto x unidad espacial x dia).

- datos:     lectura de v_ml_ventas_geo (DWH, rol dwh_ro), CSV o datos sinteticos.
- espacial:  unidades espaciales (celdas H3, KMeans, DBSCAN, zona) a partir de lat/lon.
- panel:     series diarias rellenas con ceros y cortes temporales (backtest con origen movil).
- features:  variables sin fuga del futuro (rezagos >= horizonte, calendario de Ecuador, ubicacion).
- modelos:   registro de modelos (baselines, intermitentes, estadisticos, ML, deep learning, fundacional).
- benchmark: tabla comparativa de todos los modelos.
- train:     entrena el ganador y publica el pronostico.
"""
HORIZONTE = 7
