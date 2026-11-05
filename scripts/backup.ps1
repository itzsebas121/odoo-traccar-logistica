# Respaldo en Windows PowerShell
$ErrorActionPreference = "Stop"
$backupDir = ".\backups"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

Write-Host "=== Iniciando Respaldo de Odoo y Traccar ($timestamp) ===" -ForegroundColor Cyan

# 1. Base de datos Odoo
Write-Host "[1/3] Respaldando base de datos Odoo (logistica_dev)..."
docker compose exec -T db pg_dump -U odoo -d logistica_dev -F c -f "/tmp/odoo_logistica_$timestamp.dump"
docker compose cp "db:/tmp/odoo_logistica_$timestamp.dump" "$backupDir\odoo_logistica_$timestamp.dump"
docker compose exec -T db rm -f "/tmp/odoo_logistica_$timestamp.dump"

# 2. Base de datos Traccar
Write-Host "[2/3] Respaldando base de datos Traccar (traccar)..."
docker compose exec -T db pg_dump -U traccar -d traccar -F c -f "/tmp/traccar_$timestamp.dump"
docker compose cp "db:/tmp/traccar_$timestamp.dump" "$backupDir\traccar_$timestamp.dump"
docker compose exec -T db rm -f "/tmp/traccar_$timestamp.dump"

# 3. Filestore Odoo
Write-Host "[3/3] Respaldando filestore de Odoo..."
docker compose exec -T odoo tar -czf "/tmp/filestore_$timestamp.tar.gz" -C /var/lib/odoo filestore
docker compose cp "odoo:/tmp/filestore_$timestamp.tar.gz" "$backupDir\filestore_$timestamp.tar.gz"
docker compose exec -T odoo rm -f "/tmp/filestore_$timestamp.tar.gz"

Write-Host "=== Respaldo completado en $backupDir ===" -ForegroundColor Green
Get-ChildItem $backupDir | Select-Object Name, Length, LastWriteTime

