#!/usr/bin/env bash
# Arranque de un solo comando (Linux / bash).
# Pasos: .env -> comprobacion de marcadores -> servicios sanos -> base logistica_dev -> modulos (-i o -u) -> seeds (en el host).
# Uso desde la raiz del repo: ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1  # Git Bash en Windows: evita reescribir /entrypoint.sh como ruta

# --con-analitica: ademas arranca routing, ml y bi (perfil analitica) y prepara el ETL (bootstrap).
CON_ANALITICA=0
[ "${1:-}" = "--con-analitica" ] && CON_ANALITICA=1

BASE=logistica_dev
MODULOS=(contacts fleet sale_management website website_sale payment_custom
         logistica_base logistica_despacho logistica_traccar logistica_entregas logistica_checkout
         logistica_conductor logistica_analitica_ia)
CLAVES_SECRETAS=(ODOO_DB_PASSWORD ODOO_ADMIN_PASSWORD TRACCAR_DB_PASSWORD TRACCAR_ADMIN_PASSWORD)

echo "[1/5] Archivo .env"
if [ -f .env ]; then
  echo "      .env ya existe; no se modifica."
else
  cp .env.example .env
  echo "      .env creado desde .env.example."
fi

# Quita \r, espacios externos y un par de comillas externas de un valor de .env (como docker compose).
limpia_valor() {
  local v=${1%$'\r'}
  v=${v#"${v%%[![:space:]]*}"}
  v=${v%"${v##*[![:space:]]}"}
  if [[ "$v" =~ ^\"(.*)\"$ || "$v" =~ ^\'(.*)\'$ ]]; then
    v=${BASH_REMATCH[1]}
    v=${v#"${v%%[![:space:]]*}"}
    v=${v%"${v##*[![:space:]]}"}
  fi
  printf '%s' "$v"
}

# Valor limpio de la clave $1 en .env (vacio si no existe).
valor_env() {
  local raw
  raw=$(grep -m1 "^$1=" .env || true)
  limpia_valor "${raw#*=}"
}

# Antes de tocar Docker: no arrancar con contrasenas de marcador.
marcadores=()
for clave in "${CLAVES_SECRETAS[@]}"; do
  if [[ "$(valor_env "$clave")" == CAMBIAR_* ]]; then marcadores+=("$clave"); fi
done
if [ ${#marcadores[@]} -gt 0 ]; then
  echo "Error: .env aun tiene marcadores CAMBIAR_ en: ${marcadores[*]}." >&2
  echo "Edite .env, ponga contrasenas reales en esas claves y vuelva a ejecutar el script." >&2
  exit 1
fi

echo "[2/5] Levantando servicios y esperando healthchecks (db, odoo, traccar)"
docker compose up -d --wait

echo "[3/5] Base de datos $BASE"
if [ "$(docker compose exec -T db psql -U odoo -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$BASE'")" = "1" ]; then
  echo "      La base ya existe."
else
  docker compose exec -T db createdb -U odoo -O odoo "$BASE"
  echo "      Base creada."
fi

echo "[4/5] Modulos Odoo"
psql_base() { docker compose exec -T db psql -U odoo -d "$BASE" -tAc "$1"; }
instalados=""
if [ "$(psql_base "SELECT to_regclass('ir_module_module') IS NOT NULL")" = "t" ]; then
  instalados=$(psql_base "SELECT name FROM ir_module_module WHERE state='installed'")
fi
nuevos=(); ya=()
for m in "${MODULOS[@]}"; do
  if grep -qx "$m" <<< "$instalados"; then ya+=("$m"); else nuevos+=("$m"); fi
done
join() { local IFS=,; echo "$*"; }
if [ ${#nuevos[@]} -gt 0 ]; then
  echo "      Instalando (-i): ${nuevos[*]}"
  docker compose exec -T odoo /entrypoint.sh odoo -d "$BASE" -i "$(join "${nuevos[@]}")" --without-demo=all --stop-after-init
fi
if [ ${#ya[@]} -gt 0 ]; then
  echo "      Actualizando (-u): ${ya[*]}"
  docker compose exec -T odoo /entrypoint.sh odoo -d "$BASE" -u "$(join "${ya[@]}")" --stop-after-init
fi
docker compose restart odoo
docker compose up -d --wait

# Sincroniza la secuencia de tc_users (Traccar) con las filas existentes: evita el duplicate key de POST /api/users
# (causa en docs/decisiones_fase1.md, Tarea 4). Idempotente: solo avanza la secuencia, nunca la retrocede.
SQL_SECUENCIA_TRACCAR="SELECT setval('tc_users_id_seq', GREATEST((SELECT COALESCE(MAX(id), 1) FROM tc_users), (SELECT last_value FROM tc_users_id_seq)), true)"
if ! docker compose exec -T db psql -U odoo -d traccar -tAc "$SQL_SECUENCIA_TRACCAR" >/dev/null; then
  echo "Error: no se pudo sincronizar la secuencia tc_users_id_seq de la base traccar." >&2
  exit 1
fi
echo "      Secuencia tc_users_id_seq sincronizada (base traccar)."

echo "[5/5] Datos de prueba (seeds/seed.py) en el host"
if [ -f seeds/seed.py ]; then
  # Carga las claves de .env en el proceso; los valores no se imprimen.
  while IFS='=' read -r clave valor || [ -n "$clave" ]; do
    [[ "$clave" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    # Una variable ya definida en el entorno manda sobre .env.
    [ -z "${!clave+x}" ] && export "$clave=$(limpia_valor "$valor")"
  done < .env
  python3 seeds/seed.py
else
  echo "      AVISO: seeds/seed.py no existe todavia (pendiente: Tarea 3 del plan). Se omite el sembrado."
fi

if [ "$CON_ANALITICA" = "1" ]; then
  echo "[extra] Analitica (routing, ml, bi) y bootstrap del ETL"
  docker compose --profile analitica up -d --wait routing ml bi
  docker compose --profile etl run --rm etl bootstrap
fi

echo "Listo. ERP Odoo: http://localhost:8069/web/login | Traccar: http://localhost:8082"
echo "Credenciales: las de .env (no se muestran aqui)."
