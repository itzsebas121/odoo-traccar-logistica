# Guía para implementar los dashboards BI

**Estado:** documento de diseño para una implementación posterior. El ETL ya deja en el Data Warehouse todas las tablas y vistas que esta guía usa. `services/bi` ya tiene un panel Streamlit con cinco pestañas que funciona. Lo que se describe aquí es cómo completarlo hasta el dashboard académico definitivo.

**Requisito que cubre:** §10.3 de la [especificación](flujo_funcional_odoo_traccar.md) y el criterio «El dashboard BI utiliza el Data Warehouse y permite analizar rutas y entregas» de §13. Indicadores de referencia: distancia por vehículo, recorridos por día y hora, duración promedio, zonas visitadas, paradas, entregas por cliente, estado y cumplimiento de lo planificado.

**Regla que no se rompe:** los dashboards consultan **solo** `logistica_dwh`, con el rol `dwh_ro`. Nunca Odoo, Traccar ni staging. Hay una prueba que lo vigila: `services/bi/tests/test_no_odoo.py`.

---

## 1. Lo que ya existe

| Pieza | Dónde | Qué hace |
|---|---|---|
| Consultas OLAP | `services/bi/sql/olap_queries.sql` | Bloques `-- name: x` con parámetros `%(desde)s`, `%(hasta)s` y `%(proc)s`. Los que usan `GROUP BY ROLLUP` traen una fila de total. |
| Cargador | `services/bi/olap.py` | `cargar_consultas`, `consulta`, `indicadores`, `total`, `rango_fechas`. Conexión con `psycopg2.connect(**params())`. |
| Panel | `services/bi/app.py` | Pestañas «Recorridos GPS», «Rutas: plan vs real», «Entregas», «Ventas» y «Calidad del ETL». Filtros de fecha y procedencia. Aviso cuando hay datos SIMULADO. |
| Pruebas | `services/bi/tests/` | Base desechable con una copia **idéntica** de `dwh_schema.sql` y `dwh_views.sql` del ETL. |

## 2. Catálogo de indicadores

| Indicador (§10.3) | Fuente en el DWH | Consulta | Estado |
|---|---|---|---|
| Distancia por vehículo | `fact_recorridos` + `dim_vehiculo` | `distancia_vehiculo` | existe |
| Recorridos por día y hora | `fact_recorridos` + `dim_tiempo` | `recorridos_dia_hora` | existe; **agrupa por hora UTC** (ver 3.1) y falta el mapa de calor |
| Duración promedio | `fact_recorridos` | `duracion_promedio` | existe |
| Zonas visitadas | `fact_recorridos.zona_destino_sk` | `zonas_visitadas` | existe; falta el mapa |
| Paradas | `fact_recorridos.num_paradas`, `fact_paradas` | `paradas`, `tiempos_parada` | existe |
| Entregas por cliente | `fact_entregas` + `dim_cliente` | `entregas_cliente` | existe |
| Estado de las entregas y motivos | `fact_entregas` | `entregas_estado`, `motivos_no_entrega` | existe |
| Cumplimiento de lo planificado | `fact_entregas.a_tiempo`, `v_ruta_plan_vs_real` | `cumplimiento`, `plan_real_vehiculo`, `rutas_plan_real` | existe |
| Ventas | `fact_ventas` + `dim_producto` y `dim_zona` | `ventas_*` | existe |
| Calidad del ETL | `etl_ejecucion` | `etl_ejecuciones`, `etl_rechazos` | existe |
| **Recorrido reconstruido en el mapa** | `fact_posicion_gps` (+ `fact_rutas` para la ventana) | `posiciones_ruta` | **falta** |
| **Mapa de origen a destino** | `v_ml_viajes` (zonas; coordenadas solo en viajes con ruta) | `od_viajes` | **falta** |
| **Distancia y entregas por conductor** | `fact_recorridos.conductor_sk` (conductor de la ruta), `fact_entregas` | `conductor_resumen` | **falta** |
| **Entregas vinculadas al GPS** | `fact_entregas.recorrido_sk` | `vinculo_gps` | **falta** |
| **Modelo de destinos** | servicio ML `/metrics` (no es el DWH: es el resultado del modelo) | — | **falta** |

## 3. Consultas que faltan

Se añaden a `olap_queries.sql` con el mismo formato que las demás: parámetros `%(desde)s`, `%(hasta)s` y `%(proc)s` con cast explícito, claves `k_*` rellenas con `'(sin ...)'` y `ROLLUP` cuando haga falta una fila de total. Las tres se comprobaron contra el esquema actual del DWH.

```sql
-- name: od_viajes
-- Pares origen-destino entre zonas (mapa de flujos o matriz). Fecha local.
SELECT COALESCE(zona_origen, '(sin zona)') AS k_origen, COALESCE(zona_destino, '(sin zona)') AS k_destino,
       COUNT(*) AS viajes, ROUND(AVG(distancia_km), 2) AS km_promedio,
       string_agg(DISTINCT procedencia, '+') AS procedencias
FROM v_ml_viajes
WHERE (%(desde)s::date IS NULL OR fecha_local >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR fecha_local <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR procedencia = ANY(%(proc)s::text[]))
GROUP BY 1, 2
ORDER BY viajes DESC;

-- name: conductor_resumen
-- Conductor de la ruta del viaje; sin ruta, el que tenia el vehiculo cuando se cargo el viaje.
SELECT COALESCE(c.nombre, '(sin conductor)') AS k_conductor, COUNT(*) AS recorridos,
       ROUND(SUM(r.distancia_km), 1) AS km, COUNT(DISTINCT r.ruta_id_odoo) AS rutas,
       string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
LEFT JOIN dim_conductor c ON c.sk = r.conductor_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(c.nombre, '(sin conductor)'))
ORDER BY k_conductor NULLS LAST;

-- name: vinculo_gps
-- Entregas cerradas con un recorrido GPS verificable (spec 10.2).
SELECT resultado AS k_resultado, COUNT(*) AS entregas, COUNT(recorrido_sk) AS con_recorrido,
       ROUND(100.0 * COUNT(recorrido_sk) / NULLIF(COUNT(*), 0), 1) AS pct_vinculadas,
       string_agg(DISTINCT procedencia, '+') AS procedencias
FROM fact_entregas
WHERE completado_utc IS NOT NULL
  AND (%(desde)s::date IS NULL OR completado_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR completado_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (resultado)
ORDER BY k_resultado NULLS LAST;
```

El recorrido en el mapa es por ruta, no por período, así que no va en `indicadores()`. Va en una función aparte de `olap.py`, por ejemplo `posiciones_ruta(conn, ruta_id)`:

```sql
SELECT g.gps_time_utc, g.latitud, g.longitud, g.velocidad_kmh
FROM fact_rutas r
JOIN fact_posicion_gps g ON g.vehiculo_sk = r.vehiculo_sk
 AND g.gps_time_utc BETWEEN r.inicio_utc AND COALESCE(r.fin_utc, now())
WHERE r.ruta_id_odoo = %(ruta)s
ORDER BY g.gps_time_utc;
```

### 3.1. Corrección pendiente en las consultas que ya existen

`recorridos_dia_hora` agrupa por `t.fecha` y `t.hora`, que son la fecha y la hora **UTC** de `dim_tiempo`. Así, el panel muestra los recorridos por hora UTC: un viaje de las 08:00 locales aparece a las 13:00. Hay que agrupar por `t.fecha_local` y `t.hora_local`, y en general usar las columnas `*_local` de `dim_tiempo` en todo lo que se muestra por día u hora. Los filtros de fecha de las consultas usan `inicio_utc::date`, que da el día según el `TimeZone` de la sesión de PostgreSQL; solo es el día UTC si la sesión está en UTC. Para la operación de Ecuador solo cambia el día de los viajes de después de las 19:00 locales; se puede filtrar por `t.fecha_local` para que coincida exactamente.

## 4. Diseño de páginas

Filtros globales en la barra lateral: rango de fechas, procedencia (REAL, SIMULADO), **vehículo** y **zona** (nuevos). Los dos últimos son listas que salen de `dim_vehiculo` y `dim_zona`.

| Pestaña | Contenido | Gráfico |
|---|---|---|
| Recorridos GPS | Tarjetas de km totales, duración promedio y paradas. Distancia por vehículo. **Mapa de calor de día por hora**. Zonas visitadas. | barras; `heatmap` (Altair `rect`) |
| **Mapa** (nueva) | Selector de ruta: recorrido reconstruido como línea de posiciones, más las paradas coloreadas por resultado. Flujos de origen a destino entre centroides de zona. | `pydeck` (`PathLayer`, `ArcLayer`) o `st.map` |
| Rutas: plan vs real | Km y minutos planificados frente a reales, desviación en %, detalle por ruta y tiempos por parada. | barras agrupadas |
| Entregas | Por estado, motivos, por cliente, cumplimiento por vehículo y **% vinculadas al GPS**. | barras, tarjetas |
| **Conductores** (nueva) | Km, recorridos, rutas y entregas por conductor. Usa `fact_recorridos.conductor_sk`: el conductor de la ruta y, fuera de ruta, el que tenía el vehículo cuando se cargó el viaje (no se reescribe si el vehículo cambia de conductor). | barras |
| Ventas | Por producto, cliente y zona. | barras |
| **Modelo de destinos** (nueva) | Lee `GET http://ml:8000/metrics`: accuracy y F1 del modelo frente al predictor base, matriz de confusión como mapa de calor, número de ejemplos por procedencia, fecha de corte y `model_version`. Si el ML no responde, muestra un aviso y no rompe el panel. | tarjetas y heatmap |
| Calidad del ETL | Corridas, rechazos por regla y estado del último lote. | tabla, barras |

Pautas:

- Mostrar siempre la procedencia cuando haya datos SIMULADO (§12: «indicar cuándo un resultado es estimado/simulado»).
- La pestaña del modelo es la única que consulta un servicio que no es el DWH, porque muestra el resultado del modelo y no datos operativos. La URL va en una variable de entorno, `ML_URL`.
- Las fechas que se muestran son las locales (`fecha_local`, `hora_local`). Las `*_utc` solo sirven para filtrar ventanas.

## 5. Pasos de implementación

1. Añadir las consultas de la sección 3 a `olap_queries.sql`. Si una consulta necesita una columna nueva del DWH, se cambia primero el ETL (con `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) y se copian `dwh_schema.sql` y `dwh_views.sql` a `services/bi/tests/`.
2. Pruebas en `services/bi/tests/test_olap.py`, una por consulta, con datos sembrados en la base desechable (seguir el patrón existente). Incluir el caso sin datos y el caso con el filtro de procedencia.
3. Pestañas y gráficos nuevos en `app.py`. Si se usa `pydeck` o `altair`, añadirlo a `requirements.txt` con versión fija. `altair` ya viene con Streamlit.
4. Pestaña del modelo: añadir el servicio `ml` en `depends_on` (sin exigir que esté sano) y `ML_URL: http://ml:8000` en `compose.yaml`.
5. Verificar en vivo con `docker compose --profile analitica up -d bi` y abrir <http://localhost:8501>.

## 6. Criterios de aceptación

- [ ] Todas las pestañas leen solo del DWH con `dwh_ro`, salvo la del modelo, que lee `/metrics`. `test_no_odoo.py` sigue pasando.
- [ ] Cada indicador de §10.3 tiene al menos un gráfico y se puede filtrar por fecha y procedencia.
- [ ] El mapa reconstruye el recorrido de una ruta a partir de `fact_posicion_gps`.
- [ ] Se ve el porcentaje de entregas vinculadas al GPS.
- [ ] El panel sigue funcionando con el ML apagado y con el DWH vacío.
- [ ] Las pruebas de `services/bi` pasan, con `DWH_ADMIN_DSN` definida para las de base de datos.
