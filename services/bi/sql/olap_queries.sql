-- Consultas OLAP sobre el DWH. Parametros: %(desde)s, %(hasta)s (date o NULL) y
-- %(proc)s (arreglo de procedencias o NULL = todas). Las columnas k_* son las claves de agrupacion;
-- las consultas con GROUP BY ROLLUP incluyen una fila de total (todas las k_* en NULL). Para que un valor
-- vacio de la dimension no se confunda con esa fila, las claves se rellenan con '(sin ...)'.
-- `procedencias` indica de donde salen los datos de cada fila (REAL, SIMULADO o ambas).

-- name: distancia_vehiculo
SELECT COALESCE(v.placa, '(sin placa)') AS k_vehiculo, ROUND(SUM(r.distancia_km), 2) AS distancia_km,
       COUNT(*) AS recorridos, string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(v.placa, '(sin placa)'))
ORDER BY k_vehiculo NULLS LAST;

-- name: recorridos_dia_hora
-- Dia y hora LOCALES de la operacion (ETL_TZ): un viaje de las 08:00 locales cuenta en la hora 8, no en la 13 UTC.
SELECT t.fecha_local AS k_fecha, t.hora_local AS k_hora, COUNT(*) AS recorridos,
       string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
JOIN dim_tiempo t ON t.sk = r.tiempo_inicio_sk
WHERE (%(desde)s::date IS NULL OR t.fecha_local >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR t.fecha_local <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (t.fecha_local, t.hora_local)
ORDER BY k_fecha NULLS LAST, k_hora NULLS LAST;

-- name: duracion_promedio
SELECT COALESCE(v.placa, '(sin placa)') AS k_vehiculo, ROUND(AVG(r.duracion_min), 2) AS duracion_min,
       COUNT(*) AS recorridos, string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(v.placa, '(sin placa)'))
ORDER BY k_vehiculo NULLS LAST;

-- name: zonas_visitadas
SELECT z.codigo AS zona, z.nombre AS nombre, COUNT(*) AS visitas,
       string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
JOIN dim_zona z ON z.sk = r.zona_destino_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY z.codigo, z.nombre
ORDER BY visitas DESC, zona;

-- name: paradas
SELECT COALESCE(v.placa, '(sin placa)') AS k_vehiculo, SUM(r.num_paradas) AS paradas, COUNT(*) AS recorridos,
       string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(v.placa, '(sin placa)'))
ORDER BY k_vehiculo NULLS LAST;

-- name: entregas_cliente
SELECT COALESCE(c.nombre, '(sin nombre)') AS k_cliente, e.resultado AS k_resultado, COUNT(*) AS entregas,
       string_agg(DISTINCT e.procedencia, '+') AS procedencias
FROM fact_entregas e
JOIN dim_cliente c ON c.sk = e.cliente_sk
WHERE (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(c.nombre, '(sin nombre)'), e.resultado)
ORDER BY k_cliente NULLS LAST, k_resultado NULLS LAST;

-- name: entregas_estado
SELECT e.resultado AS k_resultado, COUNT(*) AS entregas, string_agg(DISTINCT e.procedencia, '+') AS procedencias
FROM fact_entregas e
WHERE (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (e.resultado)
ORDER BY k_resultado NULLS LAST;

-- name: motivos_no_entrega
SELECT COALESCE(e.motivo, '(sin motivo)') AS motivo, COUNT(*) AS entregas,
       string_agg(DISTINCT e.procedencia, '+') AS procedencias
FROM fact_entregas e
WHERE e.resultado = 'no_entregado'
  AND (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY COALESCE(e.motivo, '(sin motivo)')
ORDER BY entregas DESC, motivo;

-- name: cumplimiento
-- Cumplimiento de lo planificado: entregas hechas antes del limite del plan (inicio de la ruta + duracion
-- planificada) sobre las entregas evaluables (entregadas y con limite conocido).
SELECT COALESCE(v.placa, '(sin placa)') AS k_vehiculo,
       COUNT(*) FILTER (WHERE e.resultado = 'entregado') AS entregadas,
       COUNT(*) FILTER (WHERE e.a_tiempo IS NOT NULL) AS evaluables,
       COUNT(*) FILTER (WHERE e.a_tiempo) AS a_tiempo,
       ROUND(100.0 * COUNT(*) FILTER (WHERE e.a_tiempo)
             / NULLIF(COUNT(*) FILTER (WHERE e.a_tiempo IS NOT NULL), 0), 1) AS pct_a_tiempo,
       string_agg(DISTINCT e.procedencia, '+') AS procedencias
FROM fact_entregas e
JOIN dim_vehiculo v ON v.sk = e.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc, e.creado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(v.placa, '(sin placa)'))
ORDER BY k_vehiculo NULLS LAST;

-- name: plan_real_vehiculo
-- Rutas de despacho: lo planificado por el optimizador frente a lo recorrido segun el GPS.
SELECT COALESCE(v.placa, '(sin placa)') AS k_vehiculo, COUNT(*) AS rutas,
       ROUND(SUM(r.km_planificado), 2) AS km_planificado, ROUND(SUM(r.km_real), 2) AS km_real,
       ROUND(SUM(r.min_planificado), 1) AS min_planificado, ROUND(SUM(r.min_real), 1) AS min_real,
       SUM(r.paradas_total) AS paradas, SUM(r.paradas_entregadas) AS entregadas, SUM(r.paradas_fallidas) AS fallidas,
       string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_rutas r
LEFT JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.fecha >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.fecha <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(v.placa, '(sin placa)'))
ORDER BY k_vehiculo NULLS LAST;

-- name: rutas_plan_real
SELECT r.codigo AS ruta, r.fecha, r.placa AS vehiculo, r.conductor, r.estado,
       r.km_planificado, r.km_real, r.desviacion_km_pct, r.min_planificado, r.min_real, r.desviacion_min_pct,
       r.paradas_total, r.paradas_entregadas, r.paradas_fallidas, r.pct_entregado, r.posiciones_gps,
       r.fuente_distancia, r.procedencia
FROM v_ruta_plan_vs_real r
WHERE (%(desde)s::date IS NULL OR r.fecha >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.fecha <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
ORDER BY r.fecha DESC, r.codigo;

-- name: tiempos_parada
-- Tiempo en cada parada (de la llegada al resultado) y tiempo desde el inicio de la ruta, por zona de destino.
SELECT COALESCE(z.nombre, '(sin zona)') AS k_zona, COUNT(*) AS paradas,
       COUNT(*) FILTER (WHERE p.estado = 'no_entregado') AS fallidas,
       ROUND(AVG(p.min_en_parada), 1) AS min_en_parada, ROUND(AVG(p.min_desde_inicio_ruta), 1) AS min_desde_inicio,
       string_agg(DISTINCT p.procedencia, '+') AS procedencias
FROM fact_paradas p
LEFT JOIN dim_zona z ON z.sk = p.zona_sk
LEFT JOIN dim_tiempo t ON t.sk = p.tiempo_sk
WHERE (%(desde)s::date IS NULL OR t.fecha >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR t.fecha <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR p.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(z.nombre, '(sin zona)'))
ORDER BY k_zona NULLS LAST;

-- name: ventas_cliente
SELECT COALESCE(c.nombre, '(sin nombre)') AS k_cliente, COUNT(DISTINCT s.pedido_id_odoo) AS pedidos,
       ROUND(SUM(s.cantidad), 2) AS unidades, ROUND(SUM(s.subtotal), 2) AS importe,
       string_agg(DISTINCT s.procedencia, '+') AS procedencias
FROM fact_ventas s
LEFT JOIN dim_cliente c ON c.sk = s.cliente_sk
WHERE (%(desde)s::date IS NULL OR s.fecha_pedido_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR s.fecha_pedido_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR s.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(c.nombre, '(sin nombre)'))
ORDER BY k_cliente NULLS LAST;

-- name: ventas_producto
SELECT COALESCE(p.nombre, '(sin nombre)') AS k_producto, ROUND(SUM(s.cantidad), 2) AS unidades,
       ROUND(SUM(s.subtotal), 2) AS importe, string_agg(DISTINCT s.procedencia, '+') AS procedencias
FROM fact_ventas s
LEFT JOIN dim_producto p ON p.sk = s.producto_sk
WHERE (%(desde)s::date IS NULL OR s.fecha_pedido_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR s.fecha_pedido_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR s.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(p.nombre, '(sin nombre)'))
ORDER BY k_producto NULLS LAST;

-- name: ventas_zona
SELECT COALESCE(z.nombre, '(sin zona)') AS k_zona, COUNT(DISTINCT s.pedido_id_odoo) AS pedidos,
       ROUND(SUM(s.subtotal), 2) AS importe, string_agg(DISTINCT s.procedencia, '+') AS procedencias
FROM fact_ventas s
LEFT JOIN dim_zona z ON z.sk = s.zona_sk
WHERE (%(desde)s::date IS NULL OR s.fecha_pedido_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR s.fecha_pedido_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR s.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(z.nombre, '(sin zona)'))
ORDER BY k_zona NULLS LAST;

-- name: od_viajes
-- Pares origen-destino entre zonas (mapa de flujos o matriz). Fecha local.
SELECT COALESCE(zona_origen, '(sin zona)') AS zona_origen, COALESCE(zona_destino, '(sin zona)') AS zona_destino,
       COUNT(*) AS viajes, ROUND(AVG(distancia_km), 2) AS km_promedio,
       string_agg(DISTINCT procedencia, '+') AS procedencias
FROM v_ml_viajes
WHERE (%(desde)s::date IS NULL OR fecha_local >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR fecha_local <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR procedencia = ANY(%(proc)s::text[]))
GROUP BY 1, 2
ORDER BY viajes DESC, zona_origen, zona_destino;

-- name: conductor_resumen
-- Conductor de la ruta del viaje; sin ruta, el que tenia el vehiculo cuando se cargo el viaje.
SELECT COALESCE(c.nombre, '(sin conductor)') AS k_conductor, COUNT(*) AS recorridos,
       ROUND(SUM(r.distancia_km), 1) AS km, COUNT(DISTINCT r.ruta_id_odoo) AS rutas,
       string_agg(DISTINCT r.procedencia, '+') AS procedencias
FROM fact_recorridos r
LEFT JOIN dim_conductor c ON c.sk = r.conductor_sk
LEFT JOIN dim_tiempo t ON t.sk = r.tiempo_inicio_sk
WHERE (%(desde)s::date IS NULL OR t.fecha_local >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR t.fecha_local <= %(hasta)s::date)
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

-- name: demanda_producto_zona
-- Unidades vendidas por zona y producto (base del mapa de demanda y del ranking por sector). Fecha local.
SELECT zona, producto, categoria, SUM(unidades) AS unidades, SUM(pedidos) AS pedidos, ROUND(SUM(importe), 2) AS importe,
       string_agg(DISTINCT procedencia, '+') AS procedencias
FROM v_bi_ventas_diarias
WHERE (%(desde)s::date IS NULL OR fecha >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR fecha <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR procedencia = ANY(%(proc)s::text[]))
GROUP BY zona, producto, categoria
ORDER BY zona, unidades DESC;

-- name: ventas_categoria
SELECT COALESCE(categoria, '(sin categoria)') AS k_categoria, SUM(unidades) AS unidades, SUM(pedidos) AS pedidos,
       ROUND(SUM(importe), 2) AS importe, string_agg(DISTINCT procedencia, '+') AS procedencias
FROM v_bi_ventas_diarias
WHERE (%(desde)s::date IS NULL OR fecha >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR fecha <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (COALESCE(categoria, '(sin categoria)'))
ORDER BY k_categoria NULLS LAST;

-- name: ventas_dia_semana
-- Patron semanal de la demanda (1 = lunes): promedio de unidades por dia de la semana.
SELECT EXTRACT(ISODOW FROM fecha)::int AS dia_semana, COUNT(DISTINCT fecha) AS dias, SUM(unidades) AS unidades,
       ROUND(SUM(unidades)::numeric / NULLIF(COUNT(DISTINCT fecha), 0), 2) AS unidades_por_dia,
       string_agg(DISTINCT procedencia, '+') AS procedencias
FROM v_bi_ventas_diarias
WHERE (%(desde)s::date IS NULL OR fecha >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR fecha <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR procedencia = ANY(%(proc)s::text[]))
GROUP BY 1
ORDER BY 1;

-- name: pronostico_vs_real
-- Modelo de demanda: backtest (pronosticado frente a real) y pronostico de los proximos dias, por fecha. No filtra
-- por fecha ni procedencia: el pronostico es del modelo vigente (ver comparativa_modelos para su procedencia).
SELECT tipo_registro, fecha, ROUND(SUM(unidades_pred), 2) AS unidades_pred, ROUND(SUM(unidades_real), 2) AS unidades_real,
       ROUND(SUM(p10), 2) AS p10, ROUND(SUM(p90), 2) AS p90, MAX(modelo) AS modelo, MAX(model_version) AS model_version
FROM v_bi_demanda_real_vs_pronostico
WHERE (%(proc)s::text[] IS NULL OR TRUE)
GROUP BY tipo_registro, fecha
ORDER BY fecha, tipo_registro;

-- name: comparativa_modelos
-- Tabla comparativa de la ultima corrida del benchmark (ordenada por WAPE 7d dentro de cada unidad y procedencia).
SELECT procedencia, unidad_espacial, puesto, modelo, familia, libreria, estado, wape_7d, wape_7d_zona, wape_7d_total,
       mejora_pct, wape, mae, rmse, mase, sesgo,
       seg_entrenar, mb_dependencias, elegido, detalle
FROM v_bi_comparativa_modelos
WHERE (%(proc)s::text[] IS NULL OR TRUE)
ORDER BY procedencia, unidad_espacial, puesto NULLS LAST, modelo;

-- name: etl_ejecuciones
-- Bitacora del ETL (no depende de la procedencia). Las mas recientes primero.
SELECT x.lote_id, x.modo, x.estado, x.inicio_utc, ROUND(EXTRACT(EPOCH FROM (x.fin_utc - x.inicio_utc))::numeric, 1) AS segundos,
       (SELECT COALESCE(SUM(v::numeric), 0) FROM jsonb_each_text(x.cargados) AS c(k, v)) AS filas_cargadas,
       (SELECT COALESCE(SUM(v::numeric), 0) FROM jsonb_each_text(x.rechazados) AS c(k, v)) AS filas_rechazadas,
       jsonb_array_length(x.omitidos) AS omitidos, x.error
FROM etl_ejecucion x
WHERE (%(desde)s::date IS NULL OR x.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR x.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR TRUE)
ORDER BY x.lote_id DESC
LIMIT 50;

-- name: etl_rechazos
-- Filas rechazadas por regla de calidad en las corridas del periodo.
SELECT c.k AS motivo, SUM(c.v::numeric) AS filas, COUNT(*) AS corridas
FROM etl_ejecucion x, jsonb_each_text(x.rechazados) AS c(k, v)
WHERE (%(desde)s::date IS NULL OR x.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR x.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR TRUE)
GROUP BY c.k
ORDER BY filas DESC, motivo;
