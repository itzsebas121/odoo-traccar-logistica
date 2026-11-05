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
    echo "[4/5] Base de datos logistica_dev no encontrada. Inicializando con módulos oficiales y personalizados..."
    docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -i contacts,fleet,sale_management,website,website_sale,payment_custom,logistica_base,logistica_despacho,logistica_traccar --stop-after-init --without-demo=all

    echo "[4/5b] Configurando idioma español, pasarela de pago y moneda USD..."
    docker compose exec -T odoo python3 -c "import os, odoo
from odoo import api, SUPERUSER_ID
pwd = os.environ.get('PASSWORD', '')
odoo.tools.config.parse_config(['--db_host=db', '--db_user=odoo', '--db_password=' + pwd, '-d', 'logistica_dev'])
registry = odoo.registry('logistica_dev')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Idioma español
    env['res.lang']._activate_lang('es_ES')
    admin_user = env['res.users'].browse(2)
    admin_user.write({'lang': 'es_ES'})
    admin_user.partner_id.write({'lang': 'es_ES'})
    # Moneda USD
    usd = env['res.currency'].search([('name', '=', 'USD')], limit=1)
    if usd:
        usd.write({'active': True})
        env['res.company'].browse(1).write({'currency_id': usd.id})
        for pl in env['product.pricelist'].search([]):
            pl.write({'currency_id': usd.id})
    # Pago Transferencia
    wire = env['payment.provider'].search([('code', '=', 'custom')], limit=1)
    if wire:
        wire.write({'state': 'enabled', 'is_published': True})
    cr.commit()
"

    echo "[4/5c] Poblando datos iniciales de prueba (Seeds)..."
    cat seeds/demo_data.py | docker compose exec -T odoo python3

    echo "[4/5d] Reiniciando Odoo para aplicar cambios..."
    docker compose restart odoo
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

