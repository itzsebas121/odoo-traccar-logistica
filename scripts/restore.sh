#!/bin/bash
set -e

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Uso: ./scripts/restore.sh <archivo_odoo.dump> <archivo_traccar.dump> [archivo_filestore.tar.gz]"
    exit 1
fi

ODOO_DUMP="$1"
TRACCAR_DUMP="$2"
FILESTORE_TAR="$3"

echo "=== Restaurando bases de datos ==="
docker compose cp "$ODOO_DUMP" db:/tmp/odoo_restore.dump
docker compose exec -T db pg_restore -U odoo -d logistica_dev --clean --if-exists /tmp/odoo_restore.dump || true
docker compose exec -T db rm -f /tmp/odoo_restore.dump

docker compose cp "$TRACCAR_DUMP" db:/tmp/traccar_restore.dump
docker compose exec -T db pg_restore -U traccar -d traccar --clean --if-exists /tmp/traccar_restore.dump || true
docker compose exec -T db rm -f /tmp/traccar_restore.dump

if [ -n "$FILESTORE_TAR" ]; then
    echo "=== Restaurando filestore ==="
    docker compose cp "$FILESTORE_TAR" odoo:/tmp/filestore_restore.tar.gz
    docker compose exec -T odoo tar -xzf /tmp/filestore_restore.tar.gz -C /var/lib/odoo/
    docker compose exec -T odoo rm -f /tmp/filestore_restore.tar.gz
fi

echo "=== Restauración finalizada ==="

