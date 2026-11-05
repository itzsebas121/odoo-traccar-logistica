# Setup automatizado en Windows PowerShell
$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Despliegue Automatizado: Odoo 16 + Traccar + PostgreSQL " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Archivo .env
if (!(Test-Path .env)) {
    Write-Host "[1/5] Creando archivo .env desde plantilla .env.example..."
    Copy-Item .env.example .env
} else {
    Write-Host "[1/5] Archivo .env detectado."
}

# 2. Levantar servicios
Write-Host "[2/5] Levantando servicios en Docker Compose..."
docker compose up -d

# 3. Esperar base de datos
Write-Host "[3/5] Esperando que PostgreSQL este saludable (healthy)..."
$isHealthy = $false
while (-not $isHealthy) {
    Start-Sleep -Seconds 2
    $containerId = docker compose ps -q db
    if ($containerId) {
        $status = docker inspect -f "{{.State.Health.Status}}" $containerId
        if ($status -eq "healthy") {
            $isHealthy = $true
        } else {
            Write-Host -NoNewline "."
        }
    }
}
Write-Host " PostgreSQL listo." -ForegroundColor Green

# 4. Verificar base de datos
$dbExists = docker compose exec -T db psql -U odoo -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='logistica_dev'"

if ($dbExists.Trim() -ne "1") {
    Write-Host "[4/5] Base de datos logistica_dev no encontrada. Inicializando modulos oficiales y personalizados..." -ForegroundColor Yellow
    docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -i contacts,fleet,sale_management,website,website_sale,payment_custom,logistica_base,logistica_despacho,logistica_traccar --stop-after-init --without-demo=all

    Write-Host "[4/5b] Configurando idioma espanol, moneda USD y metodo de pago..."
    docker compose exec -T odoo python3 -c "import os, odoo
from odoo import api, SUPERUSER_ID
pwd = os.environ.get('PASSWORD', '')
odoo.tools.config.parse_config(['--db_host=db', '--db_user=odoo', '--db_password=' + pwd, '-d', 'logistica_dev'])
registry = odoo.registry('logistica_dev')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.lang']._activate_lang('es_ES')
    admin_user = env['res.users'].browse(2)
    admin_user.write({'lang': 'es_ES'})
    admin_user.partner_id.write({'lang': 'es_ES'})
    usd = env['res.currency'].search([('name', '=', 'USD')], limit=1)
    if usd:
        usd.write({'active': True})
        env['res.company'].browse(1).write({'currency_id': usd.id})
        for pl in env['product.pricelist'].search([]):
            pl.write({'currency_id': usd.id})
    wire = env['payment.provider'].search([('code', '=', 'custom')], limit=1)
    if wire:
        wire.write({'state': 'enabled', 'is_published': True})
    cr.commit()
"

    Write-Host "[4/5c] Poblando datos iniciales de prueba (Seeds)..."
    Get-Content seeds/demo_data.py -Raw | docker compose exec -T odoo python3

    Write-Host "[4/5d] Reiniciando Odoo para aplicar cambios..."
    docker compose restart odoo
} else {
    Write-Host "[4/5] Base de datos logistica_dev ya existe. Actualizando modulos personalizados..." -ForegroundColor Green
    docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_base,logistica_despacho,logistica_traccar --stop-after-init
    docker compose restart odoo
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  DESPLIEGUE COMPLETADO CON EXITO " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  ERP Odoo:        http://localhost:8069/web/login"
Write-Host "                   (Usuario: admin / Clave: admin)"
Write-Host "  Tienda Web:      http://localhost:8069/shop"
Write-Host "  Traccar GPS:     http://localhost:8082"
Write-Host "                   (Usuario: admin@logistica.local)"
Write-Host "==========================================================" -ForegroundColor Cyan

