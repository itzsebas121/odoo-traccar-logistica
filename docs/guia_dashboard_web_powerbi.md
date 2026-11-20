# Guía del dashboard para plataforma web y Power BI

Todo sale de `logistica_dwh` con el rol de solo lectura `dwh_ro`. Hay dos formas de consumirlo:

| Forma | Archivo | Cuándo usarla |
|---|---|---|
| **Vistas planas** `v_bi_*` | `services/etl/sql/dwh_bi_views.sql` | Power BI, Metabase, Looker Studio o una API web. Sin parámetros: se filtra por columna. |
| **Consultas con parámetros** | `services/bi/sql/olap_queries.sql` | Streamlit (`services/bi`) o un backend propio. Parámetros `%(desde)s`, `%(hasta)s`, `%(proc)s`. |

**Plataforma web ya hecha:** la pestaña **Tablero** del asistente (`http://localhost:8003/#/tablero`, login de
administrador de Odoo). Backend `services/agente/app/tablero.py` (`/api/tablero/{resumen,demanda,pronostico,operacion,opciones}`,
caché de 60 s) y frontend `services/agente/web/src/components/tablero/` (shadcn/ui + Recharts + Leaflet; mapa con teselas de
Esri, que no piden clave). Necesita `DWH_DB_PASSWORD` en el servicio `agente`; sin DWH el usuario ve un mensaje simple y el
detalle (qué comando correr) queda en el log del servicio. El pronóstico lo llena `ml-predecir`.

Filtros del tablero (parámetros de la URL; cada pestaña usa los que le sirven):

| Filtro | Parámetro | Resumen | Demanda | Pronóstico | Operación |
|---|---|---|---|---|---|
| Periodo y fechas | `desde`, `hasta` | sí | sí | sí (historia que se muestra) | sí |
| Zona | `zona` (código) | sí | sí | sí (zona más cercana a cada unidad de ubicación del modelo) | sí (entregas, y rutas con paradas en la zona) |
| Categoría de producto | `categoria` | sí | sí | sí | — |
| Conductor | `conductor` | — | — | — | sí |
| Tipo de datos (solo si hay datos de demostración) | `procedencia` | sí | sí | sí | sí |

`/api/tablero/opciones` devuelve las zonas, categorías y conductores para llenar las listas. En el Resumen hay además un
panel con el pronóstico de todo el negocio.

**Pestaña Pronóstico** (`/api/tablero/pronostico` y `/api/tablero/pronostico_detalle`). Está pensada para decidir qué llevar
a cada zona, sin elegir de una lista: mapa de zonas (tamaño = unidades esperadas, color = si sube o baja frente a la
semana pasada), lo que más sube y baja (ordenado por unidades de diferencia, no por porcentaje), y la hoja de reposición
(producto × zona, con «Esperado» y «Con margen»). Tocar una zona o un producto lo enfoca en el mapa, el gráfico y las
listas. Criterios, tomados de prácticas de planificación de demanda:

- **Excepciones por impacto:** se priorizan los cambios que más pesan; con menos de 10 unidades vendidas la semana
  pasada no se calcula un porcentaje (7 → 24 sería «+244 %») y se muestra la diferencia en unidades.
- **Acierto a la vista:** «Error semana pasada» es el error por producto (suma de diferencias absolutas ÷ vendido), que no
  deja que un producto compense a otro; cada producto lleva su fiabilidad (alta hasta 15 %, media hasta 30 %).
- **Incertidumbre:** el rango probable (p10–p90, «8 de cada 10») solo se muestra para un producto; sumar rangos de
  muchas series no es válido. «Con margen» es el extremo alto del rango.
- **Una sola fuente de datos:** celdas producto × zona (`v_bi_demanda_real_vs_pronostico`, con `zona_aprox`); mapa, hoja y
  listas se calculan en el navegador a partir de ellas.
- **Sin textos de relleno:** las aclaraciones van como texto al pasar el cursor, no en pantalla.

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
| `v_bi_lineas_venta` | línea de pedido | Filtros por zona y categoría sin contar dos veces un pedido: pedidos = `COUNT(DISTINCT pedido_id_odoo)`. |
| `v_bi_pedidos` | pedido | Ticket promedio, pedidos por hora. |
| `v_bi_ventas_mapa` | fecha × punto (ubicación exacta del pedido) × categoría | Mapa de calor de demanda. |
| `v_bi_top_productos_zona` | mes × zona × producto, con `puesto` | Ranking: filtrar `puesto <= 5`. |
| `v_bi_demanda_real_vs_pronostico` | fecha × producto × unidad | Líneas real y pronóstico con banda p10–p90. `zona_aprox` = zona más cercana al centro de la unidad (para filtrar por zona). |
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
2. Elija las vistas `v_bi_*`. Para las tablas de hechos use **Import** (programar la actualización después de las corridas del ETL: 03:00 y 12:00); `v_bi_posiciones_ruta` en **DirectQuery** con filtro de ruta.
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
4. **Comparativa de modelos**: `v_bi_comparativa_modelos` ordenada por `wape_7d` (con `wape_7d_zona`, `mejora_pct` y `sesgo`), con el elegido resaltado.
5. **Operación**: recorridos (día × hora), km por conductor, plan vs real, entregas a tiempo, % vinculadas a GPS.
6. **Calidad del ETL**: `v_bi_etl_ejecuciones`.
