#!/usr/bin/env bash
# Compila el tablero del asistente (React + shadcn, services/agente/web) para Odoo, en
# odoo/addons/logistica_tablero/static/app. Usa node:22-alpine y `npm ci` desde package-lock.json, igual que la
# imagen del asistente: asi el resultado no depende del node_modules local (uno desalineado del lock mete dos copias
# de React y el tablero falla con "Cannot read properties of null (reading 'useMemo')").
# Correrlo despues de cambiar el tablero y subir static/app junto con el cambio. Requiere Docker.
set -euo pipefail
raiz="$(cd "$(dirname "$0")/.." && pwd)"
montaje="$raiz"
if command -v cygpath >/dev/null 2>&1; then montaje="$(cygpath -m "$raiz")"; fi   # Git Bash en Windows
MSYS_NO_PATHCONV=1 docker run --rm -v "$montaje:/repo" node:22-alpine sh -c '
set -e
mkdir -p /b/services/agente /b/odoo/addons/logistica_tablero/static
cd /repo/services/agente && tar --exclude=web/node_modules --exclude=web/dist -cf - web | tar -xf - -C /b/services/agente
cd /b/services/agente/web && npm ci --no-audit --no-fund >/dev/null && npm run build:odoo
rm -rf /repo/odoo/addons/logistica_tablero/static/app
cp -r /b/odoo/addons/logistica_tablero/static/app /repo/odoo/addons/logistica_tablero/static/app
'
echo "Tablero para Odoo compilado en odoo/addons/logistica_tablero/static/app"
