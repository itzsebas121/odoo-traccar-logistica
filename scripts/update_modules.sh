#!/bin/bash
set -e

MODULES="${1:-logistica_traccar}"
DB_NAME="${2:-logistica_dev}"

echo "=== Actualizando módulos: $MODULES en base de datos $DB_NAME ==="
docker compose exec -T odoo /entrypoint.sh odoo -d "$DB_NAME" -u "$MODULES" --stop-after-init
echo "=== Actualización completada ==="

