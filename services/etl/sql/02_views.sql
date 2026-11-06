CREATE OR REPLACE VIEW dwh.v_viajes_entrenamiento AS
SELECT v.placa AS vehiculo_codigo,
       to_char(r.inicio_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS fecha_hora,
       zo.codigo AS zona_origen,
       zd.codigo AS zona_destino,
       r.procedencia
FROM dwh.fact_recorridos r
JOIN dwh.dim_vehiculo v ON v.sk = r.vehiculo_sk
JOIN dwh.dim_zona zo ON zo.sk = r.zona_origen_sk
JOIN dwh.dim_zona zd ON zd.sk = r.zona_destino_sk;
