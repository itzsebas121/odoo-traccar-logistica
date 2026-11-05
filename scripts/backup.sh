#!/bin/bash
set -e

BACKUP_DIR="./backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

echo "=== Iniciando Respaldo de Odoo y Traccar ($TIMESTAMP) ==="

# 1. Respaldo de la base de datos Odoo (logistica_dev)
echo "[1/3] Respaldando base de datos Odoo (logistica_dev)..."
docker compose exec -T db pg_dump -U odoo -d logistica_dev -F c -b -v -f "/tmp/odoo_logistica_${TIMESTAMP}.dump"
docker compose cp "db:/tmp/odoo_logistica_${TIMESTAMP}.dump" "$BACKUP_DIR/odoo_logistica_${TIMESTAMP}.dump"
docker compose exec -T db rm -f "/tmp/odoo_logistica_${TIMESTAMP}.dump"

# 2. Respaldo de la base de datos Traccar
echo "[2/3] Respaldando base de datos Traccar (traccar)..."
docker compose exec -T db pg_dump -U traccar -d traccar -F c -b -v -f "/tmp/traccar_${TIMESTAMP}.dump"
docker compose cp "db:/tmp/traccar_${TIMESTAMP}.dump" "$BACKUP_DIR/traccar_${TIMESTAMP}.dump"
docker compose exec -T db rm -f "/tmp/traccar_${TIMESTAMP}.dump"

# 3. Respaldo del filestore de Odoo
echo "[3/3] Respaldando filestore de Odoo..."
docker compose exec -T odoo tar -czf "/tmp/filestore_${TIMESTAMP}.tar.gz" -C /var/lib/odoo filestore
docker compose cp "odoo:/tmp/filestore_${TIMESTAMP}.tar.gz" "$BACKUP_DIR/filestore_${TIMESTAMP}.tar.gz"
docker compose exec -T odoo rm -f "/tmp/filestore_${TIMESTAMP}.tar.gz"

echo "=== Respaldo completado exitosamente en $BACKUP_DIR ==="
ls -lh "$BACKUP_DIR"

