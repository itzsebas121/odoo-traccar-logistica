-- Base logistica_dwh: vistas de consumo.

-- Contrato C3: conjunto de viajes para entrenamiento (la consume el servicio ML).
CREATE OR REPLACE VIEW v_viajes_entrenamiento AS
SELECT v.placa AS vehiculo_codigo,
       to_char(r.inicio_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS fecha_hora,
       zo.codigo AS zona_origen,
       zd.codigo AS zona_destino,
       r.procedencia
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
JOIN dim_zona zo ON zo.sk = r.zona_origen_sk
JOIN dim_zona zd ON zd.sk = r.zona_destino_sk;

-- Ruta de despacho: lo planificado frente a lo real. Las desviaciones son NULL si falta alguno de los dos valores.
CREATE OR REPLACE VIEW v_ruta_plan_vs_real AS
SELECT r.ruta_id_odoo, r.codigo, r.fecha, r.estado, v.placa, c.nombre AS conductor,
       r.km_planificado, r.km_real,
       ROUND(100.0 * (r.km_real - r.km_planificado) / NULLIF(r.km_planificado, 0), 1) AS desviacion_km_pct,
       r.min_planificado, r.min_real,
       ROUND(100.0 * (r.min_real - r.min_planificado) / NULLIF(r.min_planificado, 0), 1) AS desviacion_min_pct,
       r.paradas_total, r.paradas_entregadas, r.paradas_fallidas, r.paradas_pendientes,
       ROUND(100.0 * r.paradas_entregadas / NULLIF(r.paradas_total, 0), 1) AS pct_entregado,
       r.posiciones_gps, r.fuente_distancia, r.procedencia, r.inicio_utc, r.fin_utc
FROM fact_rutas r
LEFT JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
LEFT JOIN dim_conductor c ON c.sk = r.conductor_sk;

-- Dataset completo de viajes para el analisis y el entrenamiento del ML (amplia el contrato C3 sin cambiarlo).
-- Una fila por recorrido, REAL o SIMULADO. Las zonas pueden ser NULL (viaje sin coordenadas): para entrenar,
-- filtrar zona_origen y zona_destino no nulas. Horas y dias en la zona horaria de la operacion (ETL_TZ).
-- Privacidad (spec 12): las coordenadas solo se dan en viajes de una ruta de despacho; fuera de la operacion el
-- viaje puede empezar o terminar en el domicilio del conductor, asi que de esos solo se ven las zonas.
CREATE OR REPLACE VIEW v_ml_viajes AS
SELECT r.sk AS recorrido_sk,
       r.procedencia,
       v.placa AS vehiculo_codigo,
       c.nombre AS conductor,
       r.inicio_utc,
       r.fin_utc,
       to_char(r.inicio_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS fecha_hora,
       t.fecha_local,
       t.hora_local,
       t.dia_semana_local,
       t.franja,
       t.fin_de_semana,
       zo.codigo AS zona_origen,
       zd.codigo AS zona_destino,
       CASE WHEN r.ruta_id_odoo IS NOT NULL THEN r.lat_origen END AS lat_origen,
       CASE WHEN r.ruta_id_odoo IS NOT NULL THEN r.lon_origen END AS lon_origen,
       CASE WHEN r.ruta_id_odoo IS NOT NULL THEN r.lat_destino END AS lat_destino,
       CASE WHEN r.ruta_id_odoo IS NOT NULL THEN r.lon_destino END AS lon_destino,
       r.distancia_km,
       r.duracion_min,
       r.velocidad_media_kmh,
       r.velocidad_max_kmh,
       r.num_paradas,
       r.ruta_id_odoo,
       (r.ruta_id_odoo IS NOT NULL) AS en_ruta,
       (SELECT count(*) FROM fact_entregas e WHERE e.recorrido_sk = r.sk)::int AS entregas_vinculadas
FROM fact_recorridos r
JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
LEFT JOIN dim_conductor c ON c.sk = r.conductor_sk
LEFT JOIN dim_tiempo t ON t.sk = r.tiempo_inicio_sk
LEFT JOIN dim_zona zo ON zo.sk = r.zona_origen_sk
LEFT JOIN dim_zona zd ON zd.sk = r.zona_destino_sk;

-- Segunda fuente de etiquetas para el ML: destinos de negocio confirmados en Odoo. Una fila por parada con
-- resultado (entregado / no entregado), en el orden en que se visitaron dentro de su ruta. zona_origen es la
-- zona de la parada anterior de la misma ruta; en la primera es NULL (sale de la bodega, que no esta en el DWH).
CREATE OR REPLACE VIEW v_ml_transiciones_paradas AS
SELECT p.ruta_id_odoo,
       p.parada_id_odoo,
       p.orden,
       v.placa AS vehiculo_codigo,
       c.nombre AS conductor,
       COALESCE(p.cierre_utc, p.llegada_utc) AS momento_utc,
       t.fecha_local,
       t.hora_local,
       t.dia_semana_local,
       t.franja,
       lag(z.codigo) OVER w AS zona_origen,
       z.codigo AS zona_destino,
       p.estado AS resultado,
       p.procedencia
FROM fact_paradas p
LEFT JOIN dim_vehiculo v ON v.sk = p.vehiculo_sk
LEFT JOIN dim_conductor c ON c.sk = p.conductor_sk
LEFT JOIN dim_tiempo t ON t.sk = p.tiempo_sk
LEFT JOIN dim_zona z ON z.sk = p.zona_sk
WHERE p.estado IN ('entregado', 'no_entregado')
WINDOW w AS (PARTITION BY p.ruta_id_odoo ORDER BY COALESCE(p.cierre_utc, p.llegada_utc), p.orden, p.parada_id_odoo);

-- Ventas con su ubicacion aproximada para el pronostico de demanda por ubicacion. Una fila por linea de pedido
-- confirmado. Fecha y hora en la zona horaria de la operacion (ETL_TZ). lat_aprox/lon_aprox: punto de entrega del
-- pedido redondeado a ~110 m (puede ser NULL si el pedido no tiene ubicacion). categoria: ultimo nivel de la
-- categoria de Odoo ("Todos / Alimentos / Granos y cereales" -> "Granos y cereales"); grupo: el nivel anterior.
CREATE OR REPLACE VIEW v_ml_ventas_geo AS
SELECT s.linea_id_odoo,
       s.pedido_id_odoo,
       s.procedencia,
       s.fecha_pedido_utc,
       t.fecha_local,
       t.hora_local,
       t.dia_semana_local,
       t.fin_de_semana,
       p.sk AS producto_sk,
       p.producto_id_odoo,
       p.nombre AS producto,
       p.referencia,
       COALESCE(NULLIF(btrim(regexp_replace(p.categoria, '^.*/', '')), ''), '(sin categoria)') AS categoria,
       COALESCE(NULLIF(btrim(split_part(p.categoria, '/', GREATEST(array_length(string_to_array(p.categoria, '/'), 1) - 1, 1))), ''),
                '(sin grupo)') AS grupo,
       s.cliente_sk,
       z.codigo AS zona,
       s.lat_aprox,
       s.lon_aprox,
       s.cantidad,
       s.precio_unitario,
       s.subtotal
FROM fact_ventas s
LEFT JOIN dim_tiempo t ON t.sk = s.tiempo_sk
LEFT JOIN dim_producto p ON p.sk = s.producto_sk
LEFT JOIN dim_zona z ON z.sk = s.zona_sk;

-- Demanda diaria por producto y zona, con los dias sin venta en 0 (serie completa entre el primer y el ultimo dia
-- con ventas de cada procedencia). Es la referencia por zona; la agregacion por celda H3 o por cluster la hace el
-- servicio ML a partir de v_ml_ventas_geo, porque depende de la unidad espacial elegida.
CREATE OR REPLACE VIEW v_ml_demanda_diaria_zona AS
WITH v AS (
    SELECT procedencia, fecha_local, producto_sk, zona,
           SUM(cantidad) AS unidades, COUNT(DISTINCT pedido_id_odoo) AS pedidos, SUM(subtotal) AS importe
    FROM v_ml_ventas_geo
    WHERE fecha_local IS NOT NULL AND producto_sk IS NOT NULL
    GROUP BY 1, 2, 3, 4
), rango AS (
    SELECT procedencia, MIN(fecha_local) AS d0, MAX(fecha_local) AS d1 FROM v GROUP BY 1
), series AS (
    SELECT DISTINCT procedencia, producto_sk, zona FROM v
)
SELECT s.procedencia,
       d::date AS fecha_local,
       EXTRACT(ISODOW FROM d)::int AS dia_semana_local,
       s.producto_sk,
       s.zona,
       COALESCE(v.unidades, 0) AS unidades,
       COALESCE(v.pedidos, 0) AS pedidos,
       COALESCE(v.importe, 0) AS importe
FROM series s
JOIN rango r ON r.procedencia = s.procedencia
CROSS JOIN LATERAL generate_series(r.d0::timestamp, r.d1::timestamp, interval '1 day') AS d
LEFT JOIN v ON v.procedencia = s.procedencia AND v.producto_sk = s.producto_sk
           AND v.zona IS NOT DISTINCT FROM s.zona AND v.fecha_local = d::date;
