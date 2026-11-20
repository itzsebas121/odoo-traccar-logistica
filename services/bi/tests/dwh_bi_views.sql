-- Base logistica_dwh: vistas planas para dashboards (Power BI, plataforma web, Streamlit).
-- Sin parametros: Power BI (Import o DirectQuery) y una API web las consumen directo y filtran por sus columnas.
-- Las lee el rol de solo lectura dwh_ro. Fechas y horas en la zona horaria de la operacion (ETL_TZ, columnas *_local);
-- las *_utc solo sirven para filtrar ventanas exactas. Toda fila lleva `procedencia` (REAL o SIMULADO, spec 12).
-- Modelo en estrella para Power BI: relacionar los hechos con v_bi_dim_fecha (fecha), v_bi_dim_producto
-- (producto_sk), v_bi_dim_cliente (cliente_sk) y v_bi_dim_zona (zona_sk). Ver docs/guia_dashboard_web_powerbi.md.

-- ================================================================= dimensiones
-- Calendario local continuo: del primer dia con datos hasta 30 dias despues del ultimo (cubre los pronosticos).
CREATE OR REPLACE VIEW v_bi_dim_fecha AS
WITH r AS (
    SELECT LEAST(MIN(fecha_local), CURRENT_DATE) AS d0, GREATEST(MAX(fecha_local), CURRENT_DATE) + 30 AS d1
    FROM dim_tiempo
)
SELECT d::date AS fecha,
       EXTRACT(YEAR FROM d)::int AS anio,
       EXTRACT(QUARTER FROM d)::int AS trimestre,
       EXTRACT(MONTH FROM d)::int AS mes,
       (ARRAY['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre',
              'noviembre','diciembre'])[EXTRACT(MONTH FROM d)::int] AS nombre_mes,
       to_char(d, 'YYYY-MM') AS anio_mes,
       EXTRACT(WEEK FROM d)::int AS semana_iso,
       to_char(d, 'IYYY-"S"IW') AS anio_semana,
       EXTRACT(DAY FROM d)::int AS dia,
       EXTRACT(ISODOW FROM d)::int AS dia_semana,              -- 1 = lunes
       (ARRAY['lunes','martes','miércoles','jueves','viernes','sábado','domingo'])[EXTRACT(ISODOW FROM d)::int]
           AS nombre_dia,
       EXTRACT(ISODOW FROM d) >= 6 AS fin_de_semana,
       -- dias de pago en Ecuador (quincena y fin de mes) y el dia siguiente
       (EXTRACT(DAY FROM d) IN (1, 15, 16)
        OR d::date = (date_trunc('month', d) + interval '1 month - 1 day')::date) AS dia_de_pago
FROM r, generate_series(r.d0::timestamp, r.d1::timestamp, interval '1 day') AS d
WHERE r.d0 IS NOT NULL;

CREATE OR REPLACE VIEW v_bi_dim_producto AS
SELECT p.sk AS producto_sk, p.producto_id_odoo, p.nombre AS producto, p.referencia,
       COALESCE(NULLIF(btrim(regexp_replace(p.categoria, '^.*/', '')), ''), '(sin categoria)') AS categoria,
       COALESCE(NULLIF(btrim(split_part(p.categoria, '/', GREATEST(array_length(string_to_array(p.categoria, '/'), 1) - 1, 1))), ''),
                '(sin grupo)') AS grupo,
       p.precio_lista
FROM dim_producto p;

-- Sin direcciones ni telefonos (spec 12): nombre, ciudad y zona.
CREATE OR REPLACE VIEW v_bi_dim_cliente AS
SELECT c.sk AS cliente_sk, c.cliente_id_odoo, c.nombre AS cliente, c.ciudad, z.sk AS zona_sk, z.codigo AS zona
FROM dim_cliente c
LEFT JOIN dim_zona z ON z.sk = c.zona_sk;

CREATE OR REPLACE VIEW v_bi_dim_zona AS
SELECT z.sk AS zona_sk, z.codigo AS zona, z.nombre, z.latitud, z.longitud, z.activa
FROM dim_zona z;

CREATE OR REPLACE VIEW v_bi_dim_vehiculo AS
SELECT v.sk AS vehiculo_sk, v.placa, v.modelo, v.capacidad, v.procedencia
FROM dim_vehiculo v;

-- ================================================================= ventas y demanda
-- Demanda diaria por producto y zona (lo que se vendio): base de los graficos de tendencia y de los KPI de venta.
CREATE OR REPLACE VIEW v_bi_ventas_diarias AS
SELECT g.fecha_local AS fecha, g.producto_sk, g.producto, g.categoria, g.grupo,
       z.sk AS zona_sk, COALESCE(g.zona, '(sin zona)') AS zona, g.procedencia,
       COUNT(*) AS lineas, COUNT(DISTINCT g.pedido_id_odoo) AS pedidos,
       SUM(g.cantidad) AS unidades, SUM(g.subtotal) AS importe
FROM v_ml_ventas_geo g
LEFT JOIN dim_zona z ON z.codigo = g.zona
WHERE g.fecha_local IS NOT NULL
GROUP BY g.fecha_local, g.producto_sk, g.producto, g.categoria, g.grupo, z.sk, g.zona, g.procedencia;

-- Una fila por linea de pedido, con su zona y categoria: base de los filtros del tablero (zona, categoria). Los pedidos
-- se cuentan con COUNT(DISTINCT pedido_id_odoo) (un pedido tiene varias lineas).
CREATE OR REPLACE VIEW v_bi_lineas_venta AS
SELECT g.fecha_local AS fecha, g.pedido_id_odoo, g.producto_sk, g.producto, g.categoria, g.grupo,
       COALESCE(g.zona, '(sin zona)') AS zona, g.procedencia, g.cantidad AS unidades, g.subtotal AS importe
FROM v_ml_ventas_geo g
WHERE g.fecha_local IS NOT NULL;

-- Pedidos (cabecera): ticket promedio, pedidos por cliente, por hora y por dia.
CREATE OR REPLACE VIEW v_bi_pedidos AS
SELECT s.pedido_id_odoo, MIN(s.pedido_ref) AS pedido_ref, MIN(t.fecha_local) AS fecha, MIN(t.hora_local) AS hora,
       MIN(s.cliente_sk) AS cliente_sk, MIN(s.zona_sk) AS zona_sk, MIN(s.estado_pedido) AS estado_pedido,
       COUNT(*) AS lineas, SUM(s.cantidad) AS unidades, SUM(s.subtotal) AS importe,
       MIN(s.entrega_id_odoo) AS entrega_id_odoo, MIN(s.procedencia) AS procedencia
FROM fact_ventas s
LEFT JOIN dim_tiempo t ON t.sk = s.tiempo_sk
GROUP BY s.pedido_id_odoo;

-- Puntos de demanda para el mapa de calor (ubicacion exacta del pedido, precision de Odoo) por dia y categoria.
CREATE OR REPLACE VIEW v_bi_ventas_mapa AS
SELECT g.fecha_local AS fecha, g.lat_aprox AS latitud, g.lon_aprox AS longitud, COALESCE(g.zona, '(sin zona)') AS zona,
       g.categoria, g.grupo, g.procedencia,
       COUNT(DISTINCT g.pedido_id_odoo) AS pedidos, SUM(g.cantidad) AS unidades, SUM(g.subtotal) AS importe
FROM v_ml_ventas_geo g
WHERE g.lat_aprox IS NOT NULL AND g.fecha_local IS NOT NULL
GROUP BY g.fecha_local, g.lat_aprox, g.lon_aprox, g.zona, g.categoria, g.grupo, g.procedencia;

-- Ranking de productos por zona y mes (1 = el mas vendido de esa zona ese mes).
CREATE OR REPLACE VIEW v_bi_top_productos_zona AS
SELECT x.*, RANK() OVER (PARTITION BY x.anio_mes, x.zona, x.procedencia ORDER BY x.unidades DESC) AS puesto
FROM (
    SELECT to_char(g.fecha_local, 'YYYY-MM') AS anio_mes, COALESCE(g.zona, '(sin zona)') AS zona,
           g.producto_sk, g.producto, g.categoria, g.procedencia,
           SUM(g.cantidad) AS unidades, SUM(g.subtotal) AS importe, COUNT(DISTINCT g.pedido_id_odoo) AS pedidos
    FROM v_ml_ventas_geo g
    WHERE g.fecha_local IS NOT NULL
    GROUP BY 1, 2, 3, 4, 5, 6
) x;

-- ================================================================= modelo de pronostico (lo escribe el servicio ML)
-- Tabla comparativa de la ultima corrida del benchmark (todas las familias de modelos y unidades espaciales).
CREATE OR REPLACE VIEW v_bi_comparativa_modelos AS
SELECT e.*
FROM ml_evaluacion_modelos e
WHERE e.corrida_id = (SELECT corrida_id FROM ml_evaluacion_modelos ORDER BY corrida_utc DESC, sk DESC LIMIT 1);

-- Historico de corridas (para ver como cambia el modelo ganador y su error con mas datos).
CREATE OR REPLACE VIEW v_bi_corridas_modelo AS
SELECT corrida_id, MIN(corrida_utc) AS corrida_utc, COUNT(*) AS modelos_evaluados,
       COUNT(*) FILTER (WHERE estado = 'ok') AS modelos_ok,
       MAX(modelo) FILTER (WHERE elegido) AS modelo_elegido,
       MAX(unidad_espacial) FILTER (WHERE elegido) AS unidad_elegida,
       MIN(wape_7d) FILTER (WHERE elegido) AS wape_elegido
FROM ml_evaluacion_modelos
GROUP BY corrida_id;

CREATE OR REPLACE VIEW v_bi_unidades_espaciales AS
SELECT u.tipo, u.unidad_id, u.centro_lat AS latitud, u.centro_lon AS longitud, u.geojson, u.lineas, u.actualizado_utc
FROM ml_unidad_espacial u;

-- Pronostico frente a lo real. 'backtest': ultimo corte de prueba (las dos columnas); 'pronostico': dias futuros
-- (unidades_real NULL). Solo el ultimo model_version de cada tipo de registro (calculado una vez, no por fila: la
-- tabla crece con cada `ml-predecir`).
CREATE OR REPLACE VIEW v_bi_demanda_real_vs_pronostico AS
WITH ultima AS (
    SELECT DISTINCT ON (tipo_registro) tipo_registro, model_version
    FROM ml_pronostico_demanda
    ORDER BY tipo_registro, generado_utc DESC, sk DESC
)
SELECT f.tipo_registro, f.fecha_objetivo AS fecha, f.producto_sk, p.nombre AS producto,
       COALESCE(NULLIF(btrim(regexp_replace(p.categoria, '^.*/', '')), ''), '(sin categoria)') AS categoria,
       f.tipo_unidad, f.unidad_id, u.centro_lat AS latitud, u.centro_lon AS longitud,
       f.unidades_pred, f.unidades_real, f.p10, f.p90,
       f.unidades_pred - f.unidades_real AS error, ABS(f.unidades_pred - f.unidades_real) AS error_abs,
       f.modelo, f.model_version, f.generado_utc,
       za.codigo AS zona_aprox   -- zona del centro de la unidad, con la misma regla del ETL (para filtrar por zona)
FROM ml_pronostico_demanda f
LEFT JOIN dim_producto p ON p.sk = f.producto_sk
LEFT JOIN ml_unidad_espacial u ON u.tipo = f.tipo_unidad AND u.unidad_id = f.unidad_id
JOIN ultima ON ultima.tipo_registro = f.tipo_registro AND ultima.model_version = f.model_version
-- Misma regla que el ETL (etl/transform/zonas.py): centroide activo mas cercano por distancia haversine, sin contar la
-- zona residual 'otra'; a mas de 4 km de todos, 'otra'.
LEFT JOIN LATERAL (
    SELECT CASE WHEN c.km <= 4.0 THEN c.codigo
                ELSE (SELECT o.codigo FROM dim_zona o WHERE o.codigo = 'otra' LIMIT 1) END AS codigo
    FROM (
        SELECT z.codigo,
               2 * 6371.0 * asin(LEAST(1.0, sqrt(power(sin(radians(z.latitud - u.centro_lat) / 2), 2)
                   + cos(radians(u.centro_lat)) * cos(radians(z.latitud))
                     * power(sin(radians(z.longitud - u.centro_lon) / 2), 2)))) AS km
        FROM dim_zona z
        WHERE z.activa AND z.codigo <> 'otra' AND z.latitud IS NOT NULL AND z.longitud IS NOT NULL
          AND u.centro_lat IS NOT NULL
        ORDER BY 2
        LIMIT 1
    ) c
) za ON true;

-- ================================================================= operacion: recorridos, rutas y entregas
-- Un recorrido GPS por fila, con dia y hora LOCAL (corrige el agrupado por hora UTC de la guia BI, punto 3.1).
-- procedencia: la del recorrido, salvo que su ruta sea del historial sintetico del demo (entonces SIMULADO: el GPS
-- de esas rutas lo manda seeds/gps_historico.py a Traccar).
CREATE OR REPLACE VIEW v_bi_recorridos AS
SELECT r.sk AS recorrido_sk, t.fecha_local AS fecha, t.hora_local AS hora, t.dia_semana_local AS dia_semana,
       t.franja, t.fin_de_semana, r.vehiculo_sk, v.placa, c.nombre AS conductor,
       zo.codigo AS zona_origen, zd.codigo AS zona_destino, r.distancia_km, r.duracion_min, r.num_paradas,
       r.velocidad_media_kmh, r.velocidad_max_kmh, r.ruta_id_odoo, (r.ruta_id_odoo IS NOT NULL) AS en_ruta,
       r.inicio_utc, r.fin_utc,
       CASE WHEN w.procedencia = 'SIMULADO' THEN 'SIMULADO' ELSE r.procedencia END AS procedencia
FROM fact_recorridos r
LEFT JOIN fact_rutas w ON w.ruta_id_odoo = r.ruta_id_odoo
LEFT JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk
LEFT JOIN dim_conductor c ON c.sk = r.conductor_sk
LEFT JOIN dim_tiempo t ON t.sk = r.tiempo_inicio_sk
LEFT JOIN dim_zona zo ON zo.sk = r.zona_origen_sk
LEFT JOIN dim_zona zd ON zd.sk = r.zona_destino_sk;

-- Flujos origen -> destino entre zonas, por dia (matriz o mapa de arcos entre centroides).
CREATE OR REPLACE VIEW v_bi_od_viajes AS
SELECT m.fecha_local AS fecha, COALESCE(m.zona_origen, '(sin zona)') AS zona_origen,
       COALESCE(m.zona_destino, '(sin zona)') AS zona_destino,
       zo.latitud AS lat_origen, zo.longitud AS lon_origen, zd.latitud AS lat_destino, zd.longitud AS lon_destino,
       m.procedencia, COUNT(*) AS viajes, ROUND(AVG(m.distancia_km), 2) AS km_promedio,
       ROUND(AVG(m.duracion_min), 1) AS min_promedio
FROM v_ml_viajes m
LEFT JOIN dim_zona zo ON zo.codigo = m.zona_origen
LEFT JOIN dim_zona zd ON zd.codigo = m.zona_destino
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8;

-- Actividad por conductor y dia: recorridos, km y rutas (conductor de la ruta o, fuera de ruta, el del vehiculo).
CREATE OR REPLACE VIEW v_bi_conductor_resumen AS
SELECT t.fecha_local AS fecha, COALESCE(c.nombre, '(sin conductor)') AS conductor,
       CASE WHEN w.procedencia = 'SIMULADO' THEN 'SIMULADO' ELSE r.procedencia END AS procedencia,
       COUNT(*) AS recorridos, ROUND(SUM(r.distancia_km), 1) AS km, ROUND(SUM(r.duracion_min), 1) AS minutos,
       COUNT(DISTINCT r.ruta_id_odoo) AS rutas
FROM fact_recorridos r
LEFT JOIN fact_rutas w ON w.ruta_id_odoo = r.ruta_id_odoo
LEFT JOIN dim_conductor c ON c.sk = r.conductor_sk
LEFT JOIN dim_tiempo t ON t.sk = r.tiempo_inicio_sk
GROUP BY 1, 2, 3;

-- Una entrega por fila: resultado, motivo, cumplimiento del plan, intentos y vinculo con un recorrido GPS.
CREATE OR REPLACE VIEW v_bi_entregas AS
SELECT e.entrega_id_odoo, e.pedido_id_odoo, e.ruta_id_odoo, t.fecha_local AS fecha,
       e.cliente_sk, cl.nombre AS cliente, e.zona_sk, z.codigo AS zona, v.placa, c.nombre AS conductor,
       e.resultado, e.motivo, e.estado_odoo, e.a_tiempo, e.intentos,
       (e.recorrido_sk IS NOT NULL) AS vinculada_gps,
       ROUND(EXTRACT(EPOCH FROM (e.completado_utc - e.creado_utc)) / 3600.0, 2) AS horas_pedido_a_cierre,
       e.creado_utc, e.planificado_utc, e.completado_utc, e.procedencia
FROM fact_entregas e
LEFT JOIN dim_tiempo t ON t.sk = e.tiempo_sk
LEFT JOIN dim_cliente cl ON cl.sk = e.cliente_sk
LEFT JOIN dim_zona z ON z.sk = e.zona_sk
LEFT JOIN dim_vehiculo v ON v.sk = e.vehiculo_sk
LEFT JOIN dim_conductor c ON c.sk = e.conductor_sk;

-- Entregas cerradas con o sin recorrido GPS verificable (spec 10.2), por dia.
CREATE OR REPLACE VIEW v_bi_vinculo_gps AS
SELECT fecha, resultado, procedencia, COUNT(*) AS entregas, COUNT(*) FILTER (WHERE vinculada_gps) AS con_recorrido,
       ROUND(100.0 * COUNT(*) FILTER (WHERE vinculada_gps) / NULLIF(COUNT(*), 0), 1) AS pct_vinculadas
FROM v_bi_entregas
WHERE completado_utc IS NOT NULL
GROUP BY 1, 2, 3;

-- Ruta planificada frente a lo real (km, minutos, paradas), con la fecha local de despacho.
CREATE OR REPLACE VIEW v_bi_ruta_plan_vs_real AS
SELECT p.*, r.vehiculo_sk, r.conductor_sk
FROM v_ruta_plan_vs_real p
JOIN fact_rutas r ON r.ruta_id_odoo = p.ruta_id_odoo;

-- Paradas: tiempos en la parada y desde el inicio de la ruta, con su ubicacion por zona.
CREATE OR REPLACE VIEW v_bi_paradas AS
SELECT p.parada_id_odoo, p.ruta_id_odoo, p.entrega_id_odoo, p.orden, t.fecha_local AS fecha, z.codigo AS zona,
       v.placa, c.nombre AS conductor, p.estado, p.motivo, p.min_en_parada, p.min_desde_inicio_ruta,
       p.llegada_utc, p.cierre_utc, p.procedencia
FROM fact_paradas p
LEFT JOIN dim_tiempo t ON t.sk = p.tiempo_sk
LEFT JOIN dim_zona z ON z.sk = p.zona_sk
LEFT JOIN dim_vehiculo v ON v.sk = p.vehiculo_sk
LEFT JOIN dim_conductor c ON c.sk = p.conductor_sk;

-- Recorrido reconstruido de cada ruta de despacho: posiciones GPS del vehiculo dentro de la ventana de la ruta.
-- Filtrar SIEMPRE por ruta_id_odoo (es una vista grande).
CREATE OR REPLACE VIEW v_bi_posiciones_ruta AS
SELECT r.ruta_id_odoo, r.codigo, g.gps_time_utc, g.latitud, g.longitud, g.velocidad_kmh,
       ROW_NUMBER() OVER (PARTITION BY r.ruta_id_odoo ORDER BY g.gps_time_utc) AS orden
FROM fact_rutas r
JOIN fact_posicion_gps g ON g.vehiculo_sk = r.vehiculo_sk
 AND g.gps_time_utc BETWEEN r.inicio_utc AND COALESCE(r.fin_utc, now());

-- ================================================================= calidad del ETL
CREATE OR REPLACE VIEW v_bi_etl_ejecuciones AS
SELECT x.lote_id, x.modo, x.estado, x.inicio_utc, x.fin_utc,
       ROUND(EXTRACT(EPOCH FROM (x.fin_utc - x.inicio_utc))::numeric, 1) AS segundos,
       (SELECT COALESCE(SUM(v::numeric), 0) FROM jsonb_each_text(x.cargados) AS c(k, v)) AS filas_cargadas,
       (SELECT COALESCE(SUM(v::numeric), 0) FROM jsonb_each_text(x.rechazados) AS c(k, v)) AS filas_rechazadas,
       jsonb_array_length(x.omitidos) AS omitidos, x.error
FROM etl_ejecucion x;
