#!/bin/bash
set -e

echo "Inicializando base de datos para Traccar..."
# Usuario y contrasena se pasan como variables de psql y se citan con format(%I, %L): una comilla u otro
# caracter especial en la contrasena ya no rompe (ni inyecta) el SQL.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v usuario="${TRACCAR_DB_USER:-traccar}" -v clave="${TRACCAR_DB_PASSWORD}" \
     -v base="${TRACCAR_DB_NAME:-traccar}" <<-'EOSQL'
    SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'usuario', :'clave')
    WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = :'usuario')\gexec

    SELECT format('CREATE DATABASE %I OWNER %I', :'base', :'usuario')
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'base')\gexec

    SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'base', :'usuario')\gexec
EOSQL
echo "Base de datos y usuario de Traccar configurados correctamente."
