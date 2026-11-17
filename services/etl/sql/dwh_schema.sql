-- Base logistica_dwh (propietario dwh_etl). Todo en el esquema public: sin esquemas propios.
-- Modelo dimensional en estrella. Dimensiones de tipo 1 (se sobrescriben). lote_id referencia el lote de la base
-- de staging (sin clave foranea: son bases distintas). Todas las fechas *_utc son timestamptz en UTC.

CREATE TABLE IF NOT EXISTS schema_version (
    version      int PRIMARY KEY,
    aplicado_utc timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- dimensiones
CREATE TABLE IF NOT EXISTS dim_tiempo (
    sk int PRIMARY KEY,  -- YYYYMMDDHH (UTC)
    fecha date NOT NULL, anio int NOT NULL, mes int NOT NULL, dia int NOT NULL,
    dia_semana int NOT NULL, hora int NOT NULL,
    -- misma hora vista en la zona horaria de la operacion (ETL_TZ)
    fecha_local date, hora_local int, dia_semana_local int, franja text, fin_de_semana boolean
);
-- Zonas: se cargan desde logistica.zona de Odoo (no hay valores fijos aqui).
CREATE TABLE IF NOT EXISTS dim_zona (
    sk serial PRIMARY KEY,
    codigo text NOT NULL UNIQUE,
    nombre text NOT NULL,
    latitud double precision,
    longitud double precision,
    zona_id_odoo int,
    activa boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS dim_vehiculo (
    sk serial PRIMARY KEY,
    vehiculo_id_odoo int NOT NULL UNIQUE,
    placa text,
    traccar_device_id int,  -- id interno del dispositivo en Traccar
    procedencia text NOT NULL DEFAULT 'REAL' CHECK (procedencia IN ('REAL','SIMULADO')),
    modelo text,
    capacidad int
);
CREATE TABLE IF NOT EXISTS dim_conductor (
    sk serial PRIMARY KEY,
    conductor_id_odoo int NOT NULL UNIQUE,
    nombre text
);
CREATE TABLE IF NOT EXISTS dim_cliente (
    sk serial PRIMARY KEY,
    cliente_id_odoo int NOT NULL UNIQUE,
    nombre text,
    zona_sk int REFERENCES dim_zona(sk),
    ciudad text
);
CREATE TABLE IF NOT EXISTS dim_producto (
    sk serial PRIMARY KEY,
    producto_id_odoo int NOT NULL UNIQUE,
    nombre text,
    referencia text,
    categoria text,
    precio_lista numeric(14,2)
);

-- ---------------------------------------------------------------- hechos
-- Viaje detectado por Traccar (o simulado).
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
    velocidad_media_kmh numeric(8,2),
    velocidad_max_kmh numeric(8,2),
    ruta_id_odoo int,              -- ruta de despacho durante la que ocurrio (NULL = fuera de ruta)
    lat_origen double precision, lon_origen double precision,
    lat_destino double precision, lon_destino double precision,
    UNIQUE (fuente_id, procedencia)
);
-- Columnas anadidas despues de la v2: llegan a una base existente con `bootstrap` (cambio aditivo, sin --reset).
ALTER TABLE fact_recorridos ADD COLUMN IF NOT EXISTS ruta_id_odoo int;
ALTER TABLE fact_recorridos ADD COLUMN IF NOT EXISTS lat_origen double precision;
ALTER TABLE fact_recorridos ADD COLUMN IF NOT EXISTS lon_origen double precision;
ALTER TABLE fact_recorridos ADD COLUMN IF NOT EXISTS lat_destino double precision;
ALTER TABLE fact_recorridos ADD COLUMN IF NOT EXISTS lon_destino double precision;
-- Posicion GPS historica (permite reconstruir el recorrido).
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
-- Ruta de despacho de Odoo: lo planificado frente a lo real (GPS dentro de la ventana inicio..fin).
CREATE TABLE IF NOT EXISTS fact_rutas (
    sk bigserial PRIMARY KEY,
    ruta_id_odoo int NOT NULL UNIQUE,
    codigo text,
    vehiculo_sk int REFERENCES dim_vehiculo(sk),
    conductor_sk int REFERENCES dim_conductor(sk),
    tiempo_sk int REFERENCES dim_tiempo(sk),
    fecha date,
    estado text,
    carga_confirmada_utc timestamptz,
    inicio_utc timestamptz,
    fin_utc timestamptz,
    km_planificado numeric(12,3),
    min_planificado numeric(12,2),
    fuente_distancia text,
    km_real numeric(12,3),
    min_real numeric(12,2),
    posiciones_gps int NOT NULL DEFAULT 0,
    paradas_total int NOT NULL DEFAULT 0,
    paradas_entregadas int NOT NULL DEFAULT 0,
    paradas_fallidas int NOT NULL DEFAULT 0,
    paradas_pendientes int NOT NULL DEFAULT 0,
    procedencia text NOT NULL DEFAULT 'REAL' CHECK (procedencia IN ('REAL','SIMULADO')),
    lote_id int
);
-- Parada de una ruta (una entrega dentro de una ruta).
CREATE TABLE IF NOT EXISTS fact_paradas (
    sk bigserial PRIMARY KEY,
    parada_id_odoo int NOT NULL UNIQUE,
    ruta_id_odoo int,
    entrega_id_odoo int,
    vehiculo_sk int REFERENCES dim_vehiculo(sk),
    conductor_sk int REFERENCES dim_conductor(sk),
    cliente_sk int REFERENCES dim_cliente(sk),
    zona_sk int REFERENCES dim_zona(sk),
    tiempo_sk int REFERENCES dim_tiempo(sk),
    orden int,
    estado text,
    posible_llegada_utc timestamptz,  -- llegada por proximidad GPS (no es entrega)
    llegada_utc timestamptz,
    cierre_utc timestamptz,
    min_en_parada numeric(12,2),
    min_desde_inicio_ruta numeric(12,2),
    motivo text,
    procedencia text NOT NULL DEFAULT 'REAL' CHECK (procedencia IN ('REAL','SIMULADO')),
    lote_id int
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
    lote_id int,
    pedido_id_odoo int,
    estado_odoo text,
    creado_utc timestamptz,
    limite_plan_utc timestamptz,  -- inicio de la ruta + duracion planificada
    a_tiempo boolean,             -- NULL si no se entrego o no hay limite planificado
    intentos int NOT NULL DEFAULT 0
);
-- Linea de pedido confirmado.
CREATE TABLE IF NOT EXISTS fact_ventas (
    sk bigserial PRIMARY KEY,
    linea_id_odoo int NOT NULL UNIQUE,
    pedido_id_odoo int NOT NULL,
    pedido_ref text,
    cliente_sk int REFERENCES dim_cliente(sk),
    producto_sk int REFERENCES dim_producto(sk),
    zona_sk int REFERENCES dim_zona(sk),
    tiempo_sk int REFERENCES dim_tiempo(sk),
    fecha_pedido_utc timestamptz,
    estado_pedido text,
    cantidad numeric(14,3),
    precio_unitario numeric(14,2),
    subtotal numeric(14,2),
    total numeric(14,2),
    entrega_id_odoo int,
    procedencia text NOT NULL DEFAULT 'REAL' CHECK (procedencia IN ('REAL','SIMULADO')),
    lote_id int
);

-- ---------------------------------------------------------------- control
-- Una fila por corrida del ETL (copia de la bitacora de staging, para que el BI la lea con dwh_ro).
CREATE TABLE IF NOT EXISTS etl_ejecucion (
    lote_id int PRIMARY KEY,
    modo text NOT NULL,
    inicio_utc timestamptz NOT NULL,
    fin_utc timestamptz,
    estado text NOT NULL,
    extraidos jsonb NOT NULL DEFAULT '{}'::jsonb,
    cargados jsonb NOT NULL DEFAULT '{}'::jsonb,
    rechazados jsonb NOT NULL DEFAULT '{}'::jsonb,
    omitidos jsonb NOT NULL DEFAULT '[]'::jsonb,
    error text
);

CREATE INDEX IF NOT EXISTS ix_fact_rec_veh_ini ON fact_recorridos (vehiculo_sk, inicio_utc, fin_utc);
CREATE INDEX IF NOT EXISTS ix_fact_pos_veh_t ON fact_posicion_gps (vehiculo_sk, gps_time_utc);
CREATE INDEX IF NOT EXISTS ix_fact_par_ruta ON fact_paradas (ruta_id_odoo);
CREATE INDEX IF NOT EXISTS ix_fact_ven_pedido ON fact_ventas (pedido_id_odoo);
CREATE INDEX IF NOT EXISTS ix_fact_rec_ruta ON fact_recorridos (ruta_id_odoo);
CREATE INDEX IF NOT EXISTS ix_fact_ent_recorrido ON fact_entregas (recorrido_sk);
