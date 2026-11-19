# Guía del dashboard para plataforma web y Power BI

Todo sale de `logistica_dwh` con el rol de solo lectura `dwh_ro`. Hay dos formas de consumirlo:

| Forma | Archivo | Cuándo usarla |
|---|---|---|
| **Vistas planas** `v_bi_*` | `services/etl/sql/dwh_bi_views.sql` | Power BI, Metabase, Looker Studio o una API web. Sin parámetros: se filtra por columna. |
| **Consultas con parámetros** | `services/bi/sql/olap_queries.sql` | Streamlit (`services/bi`) o un backend propio. Parámetros `%(desde)s`, `%(hasta)s`, `%(proc)s`. |

Las vistas las crea `etl bootstrap` (es aditivo, no borra datos). Fechas y horas son **locales** (`ETL_TZ`, America/Guayaquil). Toda fila trae `procedencia` (REAL o SIMULADO).

## 1. Catálogo

### Dimensiones (estrella)
| Vista | Clave | Uso |
|---|---|---|
| `v_bi_dim_fecha` | `fecha` | Calendario continuo con día de pago (quincena y fin de mes). |
| `v_bi_dim_producto` | `producto_sk` | Producto, categoría y grupo. |
| `v_bi_dim_cliente` | `cliente_sk` | Cliente y zona (sin teléfono ni dirección). |
| `v_bi_dim_zona` | `zona_sk` | Zona y centroide. |
| `v_bi_dim_vehiculo` | `vehiculo_sk` | Placa y capacidad. |

### Hechos
| Vista | Una fila por | Gráfico sugerido |
|---|---|---|
| `v_bi_ventas_diarias` | fecha × producto × zona | Línea de tendencia, barras por categoría. |
| `v_bi_pedidos` | pedido | Ticket promedio, pedidos por hora. |
| `v_bi_ventas_mapa` | fecha × punto (≈110 m) × categoría | Mapa de calor de demanda. |
| `v_bi_top_productos_zona` | mes × zona × producto, con `puesto` | Ranking: filtrar `puesto <= 5`. |
| `v_bi_demanda_real_vs_pronostico` | fecha × producto × unidad | Líneas real y pronóstico con banda p10–p90. |
| `v_bi_comparativa_modelos` | modelo × unidad × procedencia (última corrida) | **Tabla comparativa de modelos**. |
| `v_bi_corridas_modelo` | corrida del benchmark | Evolución del error del modelo elegido. |
| `v_bi_unidades_espaciales` | celda H3 o cluster | Mapa de las unidades (`geojson`). |
| `v_bi_recorridos` | recorrido GPS | Mapa de calor día × hora (`dia_semana`, `hora`). |
| `v_bi_od_viajes` | día × par origen-destino | Matriz o arcos entre zonas. |
| `v_bi_conductor_resumen` | día × conductor | Barras de km y recorridos. |
| `v_bi_entregas` | entrega | Estado, motivos, `a_tiempo`, `vinculada_gps`. |
| `v_bi_vinculo_gps` | día × resultado | % de entregas con recorrido GPS. |
| `v_bi_ruta_plan_vs_real` | ruta | Barras agrupadas km/min plan vs real. |
| `v_bi_paradas` | parada | Tiempo en parada por zona. |
| `v_bi_posiciones_ruta` | posición GPS | Línea del recorrido. **Filtrar siempre por `ruta_id_odoo`.** |
| `v_bi_etl_ejecuciones` | corrida del ETL | Calidad de los datos. |

## 2. Power BI

1. **Obtener datos → Base de datos PostgreSQL.** Servidor `localhost:5432` (publique el puerto de `db` o use un túnel), base `logistica_dwh`, credenciales de **base de datos** con usuario `dwh_ro` y la clave `DWH_DB_PASSWORD`.
2. Elija las vistas `v_bi_*`. Para las tablas de hechos use **Import** (programar actualización cada 15 min, como el ETL); `v_bi_posiciones_ruta` en **DirectQuery** con filtro de ruta.
3. **Relaciones** (muchos a uno, un solo sentido):
   - `v_bi_ventas_diarias[fecha]`, `v_bi_pedidos[fecha]`, `v_bi_entregas[fecha]`, `v_bi_recorridos[fecha]`, `v_bi_demanda_real_vs_pronostico[fecha]` → `v_bi_dim_fecha[fecha]`
   - `v_bi_ventas_diarias[producto_sk]`, `v_bi_demanda_real_vs_pronostico[producto_sk]` → `v_bi_dim_producto[producto_sk]`
   - `v_bi_ventas_diarias[zona_sk]`, `v_bi_entregas[zona_sk]` → `v_bi_dim_zona[zona_sk]`
   - `v_bi_pedidos[cliente_sk]`, `v_bi_entregas[cliente_sk]` → `v_bi_dim_cliente[cliente_sk]`
4. **Mapas:** en `v_bi_ventas_mapa` marque `latitud` y `longitud` como categoría de datos Latitud/Longitud y use el visual *Mapa* con `unidades` como tamaño. Para las unidades espaciales use `v_bi_unidades_espaciales[latitud, longitud]` o el visual *Shape map* con el `geojson`.
5. **Filtro de procedencia:** agregue un segmentador sobre `procedencia` en todas las páginas y un cuadro de texto avisando cuando haya SIMULADO.

### Medidas DAX
```dax
Unidades = SUM ( v_bi_ventas_diarias[unidades] )
Importe = SUM ( v_bi_ventas_diarias[importe] )
Pedidos = DISTINCTCOUNT ( v_bi_pedidos[pedido_id_odoo] )
Ticket promedio = DIVIDE ( SUM ( v_bi_pedidos[importe] ), [Pedidos] )
Unidades semana anterior = CALCULATE ( [Unidades], DATEADD ( v_bi_dim_fecha[fecha], -7, DAY ) )
Variación semanal % = DIVIDE ( [Unidades] - [Unidades semana anterior], [Unidades semana anterior] )

WAPE pronóstico =
DIVIDE (
    SUMX ( FILTER ( v_bi_demanda_real_vs_pronostico, v_bi_demanda_real_vs_pronostico[tipo_registro] = "backtest" ),
           ABS ( v_bi_demanda_real_vs_pronostico[unidades_pred] - v_bi_demanda_real_vs_pronostico[unidades_real] ) ),
    CALCULATE ( SUM ( v_bi_demanda_real_vs_pronostico[unidades_real] ),
                v_bi_demanda_real_vs_pronostico[tipo_registro] = "backtest" )
)

% entregas a tiempo =
DIVIDE ( CALCULATE ( COUNTROWS ( v_bi_entregas ), v_bi_entregas[a_tiempo] = TRUE () ),
         CALCULATE ( COUNTROWS ( v_bi_entregas ), NOT ISBLANK ( v_bi_entregas[a_tiempo] ) ) )
% vinculadas a GPS = AVERAGE ( v_bi_vinculo_gps[pct_vinculadas] ) / 100
```

## 3. Plataforma web

- **Datos históricos:** un backend con `psycopg2` (o el ORM que use) ejecuta las vistas `v_bi_*` con el rol `dwh_ro`. Las consultas con parámetros se cargan con `services/bi/olap.py` (`cargar_consultas`, `consulta`).
- **Pronóstico en tiempo real** (servicio ML, puerto 8002 local):

| Endpoint | Para qué |
|---|---|
| `POST /demanda/predict` | `{"producto_id": 7, "lat": -1.2417, "lon": -78.6197, "horizonte": 7}` → unidades por día con p10 y p90 en la unidad espacial de esa coordenada. También acepta `producto_sk` y `unidad_id`. |
| `GET /demanda/comparativa` | Tabla comparativa de modelos (JSON). |
| `GET /demanda/metrics` | Modelo elegido, WAPE, MAE, MASE, bandas. |
| `GET /demanda/unidades` | GeoJSON de las unidades espaciales para dibujar en el mapa. |
| `GET /demanda/health` | Si hay modelo cargado. |

Respuestas 503 = aún no hay modelo entrenado; 404 = el producto no tiene ventas en el historial.

## 4. Páginas sugeridas

1. **Resumen**: unidades, importe, pedidos, ticket, variación semanal; tendencia diaria.
2. **Demanda por ubicación**: mapa de calor (`v_bi_ventas_mapa`), ranking por zona, categoría × zona.
3. **Pronóstico**: real vs pronóstico con banda, WAPE, producto y unidad como filtros.
4. **Comparativa de modelos**: `v_bi_comparativa_modelos` ordenada por `wape`, con el elegido resaltado.
5. **Operación**: recorridos (día × hora), km por conductor, plan vs real, entregas a tiempo, % vinculadas a GPS.
6. **Calidad del ETL**: `v_bi_etl_ejecuciones`.
