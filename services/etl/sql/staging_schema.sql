-- Base logistica_staging (propietario etl_stg). Todo en el esquema public: sin esquemas propios.
-- Crudo de Odoo y Traccar, bitacora de lotes, marcas de agua incrementales y filas rechazadas por calidad.

CREATE TABLE IF NOT EXISTS lote (
    id          serial PRIMARY KEY,
    modo        text NOT NULL,
    inicio_utc  timestamptz NOT NULL DEFAULT now(),
    fin_utc     timestamptz,
    estado      text NOT NULL DEFAULT 'en_curso',
    conteos     jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS watermark (
    fuente      text PRIMARY KEY,
    valor_utc   timestamptz NOT NULL,
    actualizado_utc timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS odoo_raw (
    id serial PRIMARY KEY,
    lote_id int NOT NULL,
    modelo text NOT NULL,
    fuente_id text,
    payload jsonb NOT NULL,
    extraido_utc timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS traccar_raw (
    id serial PRIMARY KEY,
    lote_id int NOT NULL,
    endpoint text NOT NULL,
    fuente_id text,
    payload jsonb NOT NULL,
    extraido_utc timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_odoo_raw_lote ON odoo_raw (lote_id);
CREATE INDEX IF NOT EXISTS ix_traccar_raw_lote ON traccar_raw (lote_id);

CREATE TABLE IF NOT EXISTS rechazados (
    id bigserial PRIMARY KEY,
    entidad text NOT NULL,
    fuente_id text NOT NULL,
    motivo text NOT NULL,
    payload jsonb,
    lote_id int,
    UNIQUE (entidad, fuente_id, motivo)
);
