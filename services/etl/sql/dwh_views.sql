-- Base logistica_dwh: vista del contrato C3 (conjunto de viajes para entrenamiento; la consume el servicio ML).
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
