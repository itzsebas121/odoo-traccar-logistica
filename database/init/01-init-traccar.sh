#!/bin/bash
set -e

echo "Inicializando base de datos para Traccar..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO
    \$do\$
    BEGIN
       IF NOT EXISTS (
          SELECT FROM pg_catalog.pg_roles
          WHERE rolname = '${TRACCAR_DB_USER:-traccar}') THEN
          CREATE ROLE ${TRACCAR_DB_USER:-traccar} LOGIN PASSWORD '${TRACCAR_DB_PASSWORD}';
       END IF;
    END
    \$do\$;

    SELECT 'CREATE DATABASE ${TRACCAR_DB_NAME:-traccar} OWNER ${TRACCAR_DB_USER:-traccar}'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TRACCAR_DB_NAME:-traccar}')\gexec

    GRANT ALL PRIVILEGES ON DATABASE ${TRACCAR_DB_NAME:-traccar} TO ${TRACCAR_DB_USER:-traccar};
EOSQL
echo "Base de datos y usuario de Traccar configurados correctamente."

