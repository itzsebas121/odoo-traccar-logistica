#!/bin/bash
set -e

MODULES="${1:-logistica_traccar}"
DB_NAME="${2:-logistica_dev}"

echo "=== Actualizando módulos: $MODULES en base de datos $DB_NAME ==="
# Con Odoo detenido para no chocar con sus crons (SerializationFailure); se vuelve a levantar al final.
docker compose stop odoo
docker compose run --rm --no-deps -T odoo odoo -d "$DB_NAME" -u "$MODULES" --stop-after-init
docker compose up -d --wait odoo
echo "=== Actualización completada ==="

