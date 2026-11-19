-- Base logistica_staging (propietario etl_stg). Todo en el esquema public: sin esquemas propios.
-- Crudo de Odoo y Traccar, bitacora de lotes, marcas de agua incrementales y filas rechazadas por calidad.

CREATE TABLE IF NOT EXISTS schema_version (
    version      int PRIMARY KEY,
    aplicado_utc timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lote (
    id          serial PRIMARY KEY,
    modo        text NOT NULL,
    inicio_utc  timestamptz NOT NULL DEFAULT now(),
    fin_utc     timestamptz,
    estado      text NOT NULL DEFAULT 'en_curso',
    conteos     jsonb NOT NULL DEFAULT '{}'::jsonb,
    error       text
);

CREATE TABLE IF NOT EXISTS watermark (
    fuente          text PRIMARY KEY,
    valor_utc       timestamptz NOT NULL,
    actualizado_utc timestamptz NOT NULL DEFAULT now()
);

-- Valores de las fuentes que el ETL recuerda entre corridas (p. ej. logistica_demo.historial_hasta de Odoo: si
-- cambia, el demo reescribio fechas al pasado y la corrida siguiente debe ser completa).
CREATE TABLE IF NOT EXISTS etl_estado (
    clave           text PRIMARY KEY,
    valor           text,
    actualizado_utc timestamptz NOT NULL DEFAULT now()
);

-- Historial de versiones de cada registro de Odoo: una fila nueva solo cuando el contenido cambia (huella).
-- La transformacion lee la ultima version de cada (modelo, fuente_id). eliminado = ya no existe en Odoo.
CREATE TABLE IF NOT EXISTS odoo_raw (
    id           bigserial PRIMARY KEY,
    lote_id      int NOT NULL,
    modelo       text NOT NULL,
    fuente_id    text NOT NULL,
    write_date   timestamptz,
    huella       text NOT NULL,
    eliminado    boolean NOT NULL DEFAULT false,
    payload      jsonb NOT NULL,
    extraido_utc timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_odoo_raw_clave ON odoo_raw (modelo, fuente_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_odoo_raw_lote ON odoo_raw (lote_id);

-- Ultima lectura de cada registro de Traccar (una fila por endpoint y fuente_id); lote_id = ultimo lote que la trajo.
CREATE TABLE IF NOT EXISTS traccar_raw (
    id           bigserial PRIMARY KEY,
    lote_id      int NOT NULL,
    endpoint     text NOT NULL,
    fuente_id    text NOT NULL,
    payload      jsonb NOT NULL,
    extraido_utc timestamptz NOT NULL DEFAULT now(),
    UNIQUE (endpoint, fuente_id)
);
CREATE INDEX IF NOT EXISTS ix_traccar_raw_lote ON traccar_raw (lote_id);

-- Filas que no pasaron las reglas de calidad (no llegan al DWH). resuelto_utc: el registro ya paso en un lote posterior.
CREATE TABLE IF NOT EXISTS rechazados (
    id            bigserial PRIMARY KEY,
    entidad       text NOT NULL,
    fuente_id     text NOT NULL,
    motivo        text NOT NULL,
    payload       jsonb,
    lote_id       int,
    detectado_utc timestamptz NOT NULL DEFAULT now(),
    resuelto_utc  timestamptz,
    UNIQUE (entidad, fuente_id, motivo)
);
