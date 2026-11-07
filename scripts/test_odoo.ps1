# Instala o actualiza los módulos de logística y corre sus pruebas en la base de desarrollo.
# Uso desde la raíz del repo:  powershell -ExecutionPolicy Bypass -File scripts\test_odoo.ps1
# Salida completa en %TEMP%\odoo-tests.txt; en pantalla solo el resumen y los fallos.
# Ejecuta Odoo en un proceso aparte (puerto 8070): el servidor en marcha no se detiene hasta el final,
# cuando se reinicia para cargar el código nuevo.
param(
    [string]$Base = "logistica_dev",
    [string[]]$Actualizar = @("logistica_base", "logistica_entregas", "logistica_checkout",
                              "logistica_despacho", "logistica_traccar"),
    [string[]]$Instalar = @("logistica_conductor", "logistica_analitica_ia")
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Si la sesión quedó apuntando a otro proyecto de compose, docker compose actuaría sobre el equivocado.
foreach ($v in "COMPOSE_PROJECT_NAME", "COMPOSE_FILE") {
    if (Test-Path "env:$v") { throw "La variable $v está definida en esta sesión; bórrela (Remove-Item Env:$v) y repita." }
}

$todos = $Actualizar + $Instalar
$etiquetas = ($todos | ForEach-Object { "/$_" }) -join ","
$salida = Join-Path $env:TEMP "odoo-tests.txt"

# Instalar solo lo que aún no está instalado; el resto se actualiza.
$yaInstalados = (& docker compose exec -T db psql -U odoo -d $Base -tAc "SELECT name FROM ir_module_module WHERE state='installed'") -split "\r?\n"
$nuevos = @($Instalar | Where-Object { $yaInstalados -notcontains $_ })
$paraActualizar = @($todos | Where-Object { $nuevos -notcontains $_ })

$opciones = "-d $Base -u $($paraActualizar -join ',')"
if ($nuevos.Count -gt 0) { $opciones += " -i $($nuevos -join ',')" }
$opciones += " --test-enable --test-tags $etiquetas --stop-after-init --log-level=test --http-port=8070"

Write-Host "Instalando: $($nuevos -join ', ')  |  Actualizando: $($paraActualizar -join ', ')"
Write-Host "Pruebas: $etiquetas"
Write-Host "Esto tarda varios minutos..."
cmd /c "docker compose exec -T odoo /entrypoint.sh odoo $opciones > `"$salida`" 2>&1"
$codigo = $LASTEXITCODE

Write-Host "`n=== Resumen ===" -ForegroundColor Cyan
Select-String -Path $salida -Pattern "tests when loading", " ERROR ", " FAIL" | Select-Object -First 40 | ForEach-Object { $_.Line }

Write-Host "`n=== Detalle de fallos (primeros) ===" -ForegroundColor Yellow
$detalle = Select-String -Path $salida -Pattern "Traceback|^FAIL:|^ERROR:| ERROR | FAIL" -Context 0,14 | Select-Object -First 12
if ($detalle) { $detalle | ForEach-Object { $_.Line; $_.Context.PostContext } } else { Write-Host "(sin fallos registrados)" }

Write-Host "`nReiniciando Odoo para cargar el código nuevo..."
docker compose restart odoo | Out-Null
docker compose up -d --wait | Out-Null
Write-Host "Salida completa: $salida  (código del proceso de pruebas: $codigo)" -ForegroundColor Green
