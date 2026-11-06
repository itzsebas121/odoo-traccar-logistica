-- Consultas OLAP sobre el DWH. Parametros: %(desde)s, %(hasta)s (date o NULL) y
-- %(proc)s (arreglo de procedencias o NULL = todas). Las columnas k_* son las claves de agrupacion;
-- las consultas con GROUP BY ROLLUP incluyen una fila de total (todas las k_* en NULL).

-- name: distancia_vehiculo
SELECT v.placa AS k_vehiculo, ROUND(SUM(r.distancia_km), 2) AS distancia_km, COUNT(*) AS recorridos
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (v.placa)
ORDER BY k_vehiculo NULLS LAST;

-- name: recorridos_dia_hora
SELECT t.fecha AS k_fecha, t.hora AS k_hora, COUNT(*) AS recorridos
FROM fact_recorridos r
JOIN dim_tiempo t ON t.sk = r.tiempo_inicio_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (t.fecha, t.hora)
ORDER BY k_fecha NULLS LAST, k_hora NULLS LAST;

-- name: duracion_promedio
SELECT v.placa AS k_vehiculo, ROUND(AVG(r.duracion_min), 2) AS duracion_min, COUNT(*) AS recorridos
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (v.placa)
ORDER BY k_vehiculo NULLS LAST;

-- name: zonas_visitadas
SELECT z.codigo AS zona, z.nombre AS nombre, COUNT(*) AS visitas
FROM fact_recorridos r
JOIN dim_zona z ON z.sk = r.zona_destino_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY z.codigo, z.nombre
ORDER BY visitas DESC, zona;

-- name: paradas
SELECT v.placa AS k_vehiculo, SUM(r.num_paradas) AS paradas, COUNT(*) AS recorridos
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR r.inicio_utc::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR r.inicio_utc::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR r.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (v.placa)
ORDER BY k_vehiculo NULLS LAST;

-- name: entregas_cliente
SELECT c.nombre AS k_cliente, e.resultado AS k_resultado, COUNT(*) AS entregas
FROM fact_entregas e
JOIN dim_cliente c ON c.sk = e.cliente_sk
WHERE (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (c.nombre, e.resultado)
ORDER BY k_cliente NULLS LAST, k_resultado NULLS LAST;

-- name: entregas_estado
SELECT e.resultado AS k_resultado, COUNT(*) AS entregas
FROM fact_entregas e
WHERE (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (e.resultado)
ORDER BY k_resultado NULLS LAST;

-- name: cumplimiento
-- Cumplimiento de lo planificado: entregas completadas a tiempo / entregas completadas.
SELECT v.placa AS k_vehiculo,
       COUNT(*) FILTER (WHERE e.resultado = 'entregado') AS entregadas,
       COUNT(*) FILTER (WHERE e.resultado = 'entregado' AND e.completado_utc <= e.planificado_utc) AS a_tiempo,
       ROUND(100.0 * COUNT(*) FILTER (WHERE e.resultado = 'entregado' AND e.completado_utc <= e.planificado_utc)
             / NULLIF(COUNT(*) FILTER (WHERE e.resultado = 'entregado'), 0), 1) AS pct_a_tiempo
FROM fact_entregas e
JOIN dim_vehiculo v ON v.sk = e.vehiculo_sk
WHERE (%(desde)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc)::date >= %(desde)s::date)
  AND (%(hasta)s::date IS NULL OR COALESCE(e.completado_utc, e.planificado_utc)::date <= %(hasta)s::date)
  AND (%(proc)s::text[] IS NULL OR e.procedencia = ANY(%(proc)s::text[]))
GROUP BY ROLLUP (v.placa)
ORDER BY k_vehiculo NULLS LAST;
