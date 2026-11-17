#!/bin/bash
# Arranque del servicio odoo: genera la configuracion a partir del entorno y llama al entrypoint oficial.
# La imagen oficial no trae configuracion de produccion (gestor de bases abierto, sin contrasena maestra,
# workers=0, sin proxy_mode). Aqui se corrige sin guardar secretos en el repositorio.
set -euo pipefail

: "${ODOO_MASTER_PASSWORD:?Configura ODOO_MASTER_PASSWORD (contrasena maestra del gestor de bases)}"
ODOO_DB="${ODOO_DB:-logistica_dev}"
CONF="${ODOO_RC:-/tmp/odoo.conf}"

# La contrasena maestra se guarda con hash (pbkdf2), nunca en claro dentro del contenedor.
MAESTRA_HASH="$(python3 - <<'PY'
import os
from passlib.context import CryptContext
print(CryptContext(['pbkdf2_sha512']).hash(os.environ['ODOO_MASTER_PASSWORD']))
PY
)"

cat > "$CONF" <<EOF
[options]
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
admin_passwd = ${MAESTRA_HASH}
; Una sola base: sin lista ni selector de bases publicos.
db_name = ${ODOO_DB}
dbfilter = ^${ODOO_DB}\$
list_db = False
; True solo detras de un proxy inverso (Traefik/Dokploy, nginx) que fije X-Forwarded-*.
proxy_mode = ${ODOO_PROXY_MODE:-False}
workers = ${ODOO_WORKERS:-2}
gevent_port = 8072
max_cron_threads = ${ODOO_CRON_THREADS:-1}
limit_time_cpu = ${ODOO_LIMIT_TIME_CPU:-120}
limit_time_real = ${ODOO_LIMIT_TIME_REAL:-300}
limit_memory_soft = ${ODOO_LIMIT_MEMORY_SOFT:-1073741824}
limit_memory_hard = ${ODOO_LIMIT_MEMORY_HARD:-1342177280}
limit_request = 8192
db_maxconn = ${ODOO_DB_MAXCONN:-32}
log_level = info
EOF

export ODOO_RC="$CONF"

# Reinicio automático tras una actualización de módulos: Odoo no recarga el código Python en caliente, y en un
# redespliegue este contenedor puede seguir vivo con el código anterior. Cuando odoo-init termina de actualizar
# (cambian las versiones instaladas de logistica_*), se detiene Odoo y Docker lo levanta con el código nuevo.
if [ "${1:-}" = "odoo" ] && [ "$#" -eq 1 ]; then
    (
        PGPASSWORD=$PASSWORD
        export PGPASSWORD
        consulta="SELECT string_agg(name || '=' || COALESCE(latest_version, ''), ',' ORDER BY name)
                  FROM ir_module_module WHERE name LIKE 'logistica%' AND state = 'installed'"
        version() { psql -h "${HOST:-db}" -U "${USER:-odoo}" -d "$ODOO_DB" -tAc "$consulta" 2>/dev/null; }
        sleep 60
        inicial=$(version)
        while sleep 30; do
            actual=$(version)
            if [ -n "$inicial" ] && [ -n "$actual" ] && [ "$actual" != "$inicial" ]; then
                echo "odoo: modulos actualizados ($actual); reiniciando para cargar el codigo nuevo." >&2
                kill -TERM 1
                exit 0
            fi
            [ -z "$inicial" ] && inicial="$actual"
        done
    ) &
fi

exec /entrypoint.sh "$@"
