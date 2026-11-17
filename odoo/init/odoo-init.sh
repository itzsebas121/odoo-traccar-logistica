#!/bin/bash
# Servicio odoo-init (una sola vez por arranque, antes de odoo):
#  1. Instala los modulos SOLO si la base es nueva. Reinstalar (-i) con Odoo ya en marcha choca con sus
#     crons ("could not serialize access due to concurrent update") y hacia fallar cada `docker compose up`.
#     Las actualizaciones de modulos se hacen con scripts/update_modules.sh.
#  2. Aplica ODOO_ADMIN_PASSWORD al usuario administrador (Odoo lo crea con la clave "admin").
set -euo pipefail

ODOO_DB="${ODOO_DB:-logistica_dev}"
MODULOS="contacts,fleet,sale_management,website,website_sale,payment_custom,logistica_base,logistica_despacho,logistica_traccar,logistica_entregas,logistica_checkout,logistica_conductor,logistica_analitica_ia"
PGPASSWORD=$PASSWORD
export PGPASSWORD

instalada() {
    psql -h db -U odoo -d "$ODOO_DB" -tAc \
        "SELECT 1 FROM ir_module_module WHERE name='logistica_analitica_ia' AND state='installed'" 2>/dev/null | grep -q 1
}

if instalada; then
    echo "odoo-init: la base $ODOO_DB ya tiene los modulos instalados; no se reinstala."
else
    echo "odoo-init: instalando modulos en $ODOO_DB"
    odoo --db_host=db --db_port=5432 --db_user=odoo --db_password "$PASSWORD" \
        -d "$ODOO_DB" -i "$MODULOS" \
        --load-language=es_EC --without-demo=all --stop-after-init
fi

python3 /opt/logistica-init/admin_password.py
