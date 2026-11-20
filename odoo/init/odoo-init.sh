#!/bin/bash
# Servicio odoo-init (una sola vez por arranque, antes de odoo):
#  1. Instala los modulos SOLO si la base es nueva. Reinstalar (-i) con Odoo ya en marcha choca con sus
#     crons ("could not serialize access due to concurrent update") y hacia fallar cada `docker compose up`.
#     Las actualizaciones de modulos se hacen con scripts/update_modules.sh.
#  2. En una base existente: instala los modulos propios nuevos de la lista y actualiza los que cambiaron de version.
#  3. Repara los Tableros de Odoo cuyo JSON falte en el filestore (reparar_tableros.py).
#  4. Aplica ODOO_ADMIN_PASSWORD al usuario administrador (Odoo lo crea con la clave "admin").
set -euo pipefail

ODOO_DB="${ODOO_DB:-logistica_dev}"
MODULOS="contacts,fleet,sale_management,website,website_sale,payment_custom,logistica_base,logistica_despacho,logistica_traccar,logistica_entregas,logistica_checkout,logistica_conductor,logistica_analitica_ia,logistica_tablero"
PGPASSWORD=$PASSWORD
export PGPASSWORD

# Antes de nada: ¿la clave de .env abre PostgreSQL? POSTGRES_PASSWORD solo se aplica cuando el volumen
# de datos se crea por primera vez; cambiar ODOO_DB_PASSWORD despues NO cambia la clave guardada.
if ! salida=$(psql -h db -U odoo -d postgres -tAc "SELECT 1" 2>&1); then
    echo "odoo-init: ERROR: no se pudo entrar a PostgreSQL como 'odoo'." >&2
    echo "  Detalle: $(echo "$salida" | tail -n 1)" >&2
    if echo "$salida" | grep -q "password authentication failed"; then
        echo "  Causa: ODOO_DB_PASSWORD no coincide con la clave con la que se creo el volumen de la base." >&2
        echo "  Solucion: vuelva a poner la clave anterior, o cambie la clave dentro de PostgreSQL:" >&2
        echo "    docker compose exec db psql -U odoo -d postgres -c \"ALTER USER odoo PASSWORD '<nueva>'\"" >&2
    fi
    exit 1
fi

instalada() {
    psql -h db -U odoo -d "$ODOO_DB" -tAc \
        "SELECT 1 FROM ir_module_module WHERE name='logistica_analitica_ia' AND state='installed'" 2>/dev/null | grep -q 1
}

# Corre odoo con -i/-u y reintenta: en un redespliegue el Odoo anterior puede seguir corriendo sus crons unos segundos.
con_reintentos() {
    local accion="$1" modulos="$2"
    for intento in 1 2 3; do
        if odoo --db_host=db --db_port=5432 --db_user=odoo --db_password "$PASSWORD" \
                -d "$ODOO_DB" "$accion" "$modulos" --stop-after-init --max-cron-threads=0; then
            return 0
        fi
        if [ "$intento" = 3 ]; then
            echo "odoo-init: ERROR: fallo $accion $modulos." >&2
            exit 1
        fi
        echo "odoo-init: $accion $modulos fallo (intento $intento); se reintenta en 20 s." >&2
        sleep 20
    done
}

if instalada; then
    echo "odoo-init: la base $ODOO_DB ya tiene los modulos instalados; no se reinstala."
    # Modulos propios nuevos de la lista (p. ej. logistica_tablero) que esta base aun no tiene.
    nuevos=$(python3 /opt/logistica-init/modulos_pendientes.py --faltantes "$MODULOS")
    if [ -n "$nuevos" ]; then
        echo "odoo-init: instalando modulos nuevos: $nuevos"
        con_reintentos -i "$nuevos"
    fi
    # Solo se actualizan (-u) los modulos propios cuya version de codigo cambio.
    pendientes=$(python3 /opt/logistica-init/modulos_pendientes.py)
    if [ -n "$pendientes" ]; then
        echo "odoo-init: actualizando modulos con version nueva: $pendientes"
        con_reintentos -u "$pendientes"
    fi
else
    echo "odoo-init: instalando modulos en $ODOO_DB"
    odoo --db_host=db --db_port=5432 --db_user=odoo --db_password "$PASSWORD" \
        -d "$ODOO_DB" -i "$MODULOS" \
        --load-language=es_EC --without-demo=all --stop-after-init
fi

# Tableros de Odoo sin su JSON en el filestore: se vuelven a cargar del modulo. Un fallo aqui no frena el arranque.
odoo shell --db_host=db --db_port=5432 --db_user=odoo --db_password "$PASSWORD" -d "$ODOO_DB" \
    --no-http --max-cron-threads=0 < /opt/logistica-init/reparar_tableros.py \
    || echo "odoo-init: AVISO: no se pudieron revisar los Tableros de Odoo." >&2

python3 /opt/logistica-init/admin_password.py
