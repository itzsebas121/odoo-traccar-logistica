-- Base logistica_dwh (propietario dwh_etl). Todo en el esquema public: sin esquemas propios.
-- Modelo dimensional del contrato C5. lote_id referencia el lote de la base de staging (sin clave foranea:
-- son bases distintas).

CREATE TABLE IF NOT EXISTS dim_vehiculo (
    sk serial PRIMARY KEY,
    vehiculo_id_odoo int NOT NULL UNIQUE,
    placa text,
    traccar_device_id int,
    procedencia text NOT NULL DEFAULT 'REAL' CHECK (procedencia IN ('REAL','SIMULADO'))
);
CREATE TABLE IF NOT EXISTS dim_conductor (
    sk serial PRIMARY KEY,
    conductor_id_odoo int NOT NULL UNIQUE,
    nombre text
);
CREATE TABLE IF NOT EXISTS dim_tiempo (
    sk int PRIMARY KEY,  -- YYYYMMDDHH (UTC)
    fecha date NOT NULL, anio int NOT NULL, mes int NOT NULL, dia int NOT NULL,
    dia_semana int NOT NULL, hora int NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_zona (
    sk serial PRIMARY KEY,
    codigo text NOT NULL UNIQUE,
    nombre text NOT NULL,
    latitud double precision,
    longitud double precision
);
CREATE TABLE IF NOT EXISTS dim_cliente (
    sk serial PRIMARY KEY,
    cliente_id_odoo int NOT NULL UNIQUE,
    nombre text,
    zona_sk int REFERENCES dim_zona(sk)
);

CREATE TABLE IF NOT EXISTS fact_recorridos (
    sk bigserial PRIMARY KEY,
    vehiculo_sk int REFERENCES dim_vehiculo(sk),
    conductor_sk int REFERENCES dim_conductor(sk),
    tiempo_inicio_sk int REFERENCES dim_tiempo(sk),
    zona_origen_sk int REFERENCES dim_zona(sk),
    zona_destino_sk int REFERENCES dim_zona(sk),
    inicio_utc timestamptz NOT NULL,
    fin_utc timestamptz NOT NULL,
    distancia_km numeric(12,3),
    duracion_min numeric(12,2),
    num_paradas int NOT NULL DEFAULT 0,
    fuente_id text NOT NULL,
    procedencia text NOT NULL CHECK (procedencia IN ('REAL','SIMULADO')),
    lote_id int,
    UNIQUE (fuente_id, procedencia)
);
CREATE TABLE IF NOT EXISTS fact_entregas (
    sk bigserial PRIMARY KEY,
    cliente_sk int REFERENCES dim_cliente(sk),
    vehiculo_sk int REFERENCES dim_vehiculo(sk),
    conductor_sk int REFERENCES dim_conductor(sk),
    tiempo_sk int REFERENCES dim_tiempo(sk),
    zona_sk int REFERENCES dim_zona(sk),
    entrega_id_odoo int NOT NULL UNIQUE,
    ruta_id_odoo int,
    recorrido_sk bigint REFERENCES fact_recorridos(sk),
    resultado text NOT NULL CHECK (resultado IN ('entregado','no_entregado','pendiente')),
    motivo text,
    planificado_utc timestamptz,
    completado_utc timestamptz,
    procedencia text NOT NULL DEFAULT 'REAL' CHECK (procedencia IN ('REAL','SIMULADO')),
    lote_id int
);
CREATE TABLE IF NOT EXISTS fact_posicion_gps (
    sk bigserial PRIMARY KEY,
    vehiculo_sk int REFERENCES dim_vehiculo(sk),
    tiempo_sk int REFERENCES dim_tiempo(sk),
    gps_time_utc timestamptz NOT NULL,
    latitud double precision NOT NULL,
    longitud double precision NOT NULL,
    velocidad_kmh numeric(8,2),
    fuente_id text NOT NULL UNIQUE,
    lote_id int
);

-- Ventana temporal de cada ruta de Odoo (started_at..finished_at). Se refresca completa en cada corrida y la usa
-- la regla de vinculo entrega-recorrido (fin_utc NULL = ruta abierta: se usa 'ahora').
CREATE TABLE IF NOT EXISTS ruta_ventana (
    ruta_id_odoo int PRIMARY KEY,
    vehiculo_sk int REFERENCES dim_vehiculo(sk),
    inicio_utc timestamptz,
    fin_utc timestamptz,
    lote_id int
);

CREATE INDEX IF NOT EXISTS ix_fact_rec_veh_ini ON fact_recorridos (vehiculo_sk, inicio_utc, fin_utc);
CREATE INDEX IF NOT EXISTS ix_fact_pos_veh_t ON fact_posicion_gps (vehiculo_sk, gps_time_utc);

-- Zonas (C3). Centroides aproximados de Ambato (D10); 'otra' no tiene coordenadas.
INSERT INTO dim_zona (codigo, nombre, latitud, longitud) VALUES
 ('centro','Centro',-1.2417,-78.6197),
 ('ficoa','Ficoa',-1.2230,-78.6330),
 ('huachi','Huachi',-1.2750,-78.6300),
 ('izamba','Izamba',-1.2050,-78.5900),
 ('atocha','Atocha',-1.2700,-78.6450),
 ('ingahurco','Ingahurco',-1.2350,-78.6250),
 ('otra','Otra',NULL,NULL)
ON CONFLICT (codigo) DO NOTHING;
