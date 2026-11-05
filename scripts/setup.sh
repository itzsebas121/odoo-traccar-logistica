#!/bin/bash
set -e

echo "=========================================================="
echo "  Despliegue Automatizado: Odoo 16 + Traccar + PostgreSQL "
echo "=========================================================="

# 1. Configurar archivo .env si no existe
if [ ! -f .env ]; then
    echo "[1/5] Creando archivo .env desde plantilla .env.example..."
    cp .env.example .env
else
    echo "[1/5] Archivo .env detectado."
fi

# 2. Levantar contenedores
echo "[2/5] Levantando servicios en Docker Compose..."
docker compose up -d

# 3. Esperar a que la base de datos esté lista
echo "[3/5] Esperando que PostgreSQL este saludable (healthy)..."
until [ "$(docker inspect -f '{{.State.Health.Status}}' $(docker compose ps -q db))" == "healthy" ]; do
    sleep 2
    printf "."
done
echo " PostgreSQL listo."

# 4. Comprobar si existe la base de datos logistica_dev
DB_EXISTS=$(docker compose exec -T db psql -U odoo -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='logistica_dev'")

if [ "$DB_EXISTS" != "1" ]; then
    SNAPSHOT_DUMP="database/snapshot/odoo_base.dump"
    SNAPSHOT_FILES="database/snapshot/filestore_base.tar.gz"

    if [ -f "$SNAPSHOT_DUMP" ] && [ -f "$SNAPSHOT_FILES" ]; then
        echo "[4/5] Restaurando Snapshot oficial con productos, clientes y configuraciones..."
        docker compose exec -T db createdb -U odoo -O odoo logistica_dev
        docker compose cp "$SNAPSHOT_DUMP" "db:/tmp/odoo_base.dump"
        docker compose exec -T db pg_restore -U odoo -d logistica_dev --no-owner --role=odoo /tmp/odoo_base.dump || true
        docker compose exec -T db rm -f /tmp/odoo_base.dump

        echo "[4/5b] Restaurando imagenes y filestore..."
        docker compose cp "$SNAPSHOT_FILES" "odoo:/tmp/filestore_base.tar.gz"
        docker compose exec -T odoo tar -xzf /tmp/filestore_base.tar.gz -C /var/lib/odoo/
        docker compose exec -T odoo rm -f /tmp/filestore_base.tar.gz

        echo "[4/5c] Actualizando modulos personalizados..."
        docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_base,logistica_despacho,logistica_traccar --stop-after-init
        docker compose restart odoo
    else
        echo "[4/5] Base de datos logistica_dev no encontrada. Inicializando desde cero..."
        docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -i contacts,fleet,sale_management,website,website_sale,payment_custom,logistica_base,logistica_despacho,logistica_traccar --stop-after-init --without-demo=all
        cat seeds/demo_data.py | docker compose exec -T odoo python3
        docker compose restart odoo
    fi
else
    echo "[4/5] Base de datos logistica_dev ya existe. Actualizando modulos personalizados..."
    docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_base,logistica_despacho,logistica_traccar --stop-after-init
    docker compose restart odoo
fi

echo "=========================================================="
echo "  DESPLIEGUE COMPLETADO CON EXITO "
echo "=========================================================="
echo "  ERP Odoo:        http://localhost:8069/web/login"
echo "                   (Usuario: admin / Clave: admin)"
echo "  Tienda Web:      http://localhost:8069/shop"
echo "  Traccar GPS:     http://localhost:8082"
echo "                   (Usuario: admin@logistica.local)"
echo "=========================================================="
