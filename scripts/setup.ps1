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
    $snapshotDump = "database\snapshot\odoo_base.dump"
    $snapshotFiles = "database\snapshot\filestore_base.tar.gz"

    if ((Test-Path $snapshotDump) -and (Test-Path $snapshotFiles)) {
        Write-Host "[4/5] Restaurando Snapshot oficial con productos, clientes y configuraciones..." -ForegroundColor Yellow
        docker compose exec -T db createdb -U odoo -O odoo logistica_dev
        docker compose cp $snapshotDump "db:/tmp/odoo_base.dump"
        docker compose exec -T db pg_restore -U odoo -d logistica_dev --no-owner --role=odoo /tmp/odoo_base.dump 2>$null
        docker compose exec -T db rm -f /tmp/odoo_base.dump

        Write-Host "[4/5b] Restaurando imagenes y filestore..."
        docker compose cp $snapshotFiles "odoo:/tmp/filestore_base.tar.gz"
        docker compose exec -T odoo tar -xzf /tmp/filestore_base.tar.gz -C /var/lib/odoo/
        docker compose exec -T odoo rm -f /tmp/filestore_base.tar.gz

        Write-Host "[4/5c] Actualizando modulos personalizados..."
        docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_base,logistica_despacho,logistica_traccar --stop-after-init
        docker compose restart odoo
    } else {
        Write-Host "[4/5] Inicializando base de datos limpia..." -ForegroundColor Yellow
        docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -i contacts,fleet,sale_management,website,website_sale,payment_custom,logistica_base,logistica_despacho,logistica_traccar --stop-after-init --without-demo=all
        Get-Content seeds/demo_data.py -Raw | docker compose exec -T odoo python3
        docker compose restart odoo
    }
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
