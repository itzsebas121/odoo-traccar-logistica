# Arranque de un solo comando (Windows PowerShell 5.1).
# Pasos: .env -> comprobacion de marcadores -> servicios sanos -> base logistica_dev -> modulos (-i o -u) -> seeds (en el host).
# Uso desde la raiz del repo: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$Base = "logistica_dev"
$Modulos = @("contacts", "fleet", "sale_management", "website", "website_sale", "payment_custom",
             "logistica_base", "logistica_despacho", "logistica_traccar", "logistica_entregas", "logistica_checkout")
$ClavesSecretas = @("ODOO_DB_PASSWORD", "ODOO_ADMIN_PASSWORD", "TRACCAR_DB_PASSWORD", "TRACCAR_ADMIN_PASSWORD")

# Ejecuta docker compose; si el comando falla, detiene el script. Devuelve su salida.
function Invoke-Compose([string[]]$Argumentos) {
    $salida = & docker compose @Argumentos
    if ($LASTEXITCODE -ne 0) { throw "Fallo: docker compose $($Argumentos -join ' ') (codigo $LASTEXITCODE)" }
    return $salida
}

# Consulta SQL en el contenedor db y devuelve el texto sin espacios sobrantes.
function Invoke-Sql([string]$Db, [string]$Sql) {
    $salida = Invoke-Compose @('exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', $Db, '-tAc', $Sql)
    return ($salida | Out-String).Trim()
}

# Lee un archivo clave=valor y devuelve una tabla hash. Quita espacios y un par de comillas externas
# (como hace docker compose). Los valores no se imprimen.
function Read-EnvFile([string]$Ruta) {
    $vars = @{}
    foreach ($linea in Get-Content $Ruta) {
        if ($linea -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $clave = $matches[1]
            $valor = $matches[2].Trim()
            if ($valor -match '^(["''])(.*)\1$') { $valor = $matches[2].Trim() }
            $vars[$clave] = $valor
        }
    }
    return $vars
}

Write-Host "[1/5] Archivo .env"
if (Test-Path .env) {
    Write-Host "      .env ya existe; no se modifica."
} else {
    Copy-Item .env.example .env
    Write-Host "      .env creado desde .env.example."
}

# Antes de tocar Docker: no arrancar con contrasenas de marcador.
$vars = Read-EnvFile ".env"
$marcadores = @($ClavesSecretas | Where-Object { $vars[$_] -like 'CAMBIAR_*' })
if ($marcadores.Count -gt 0) {
    Write-Host "Error: .env aun tiene marcadores CAMBIAR_ en: $($marcadores -join ', ')." -ForegroundColor Red
    Write-Host "Edite .env, ponga contrasenas reales en esas claves y vuelva a ejecutar el script." -ForegroundColor Red
    exit 1
}

Write-Host "[2/5] Levantando servicios y esperando healthchecks (db, odoo, traccar)"
Invoke-Compose @('up', '-d', '--wait')

Write-Host "[3/5] Base de datos $Base"
if ((Invoke-Sql "postgres" "SELECT 1 FROM pg_database WHERE datname='$Base'") -eq "1") {
    Write-Host "      La base ya existe."
} else {
    Invoke-Compose @('exec', '-T', 'db', 'createdb', '-U', 'odoo', '-O', 'odoo', $Base)
    Write-Host "      Base creada."
}

Write-Host "[4/5] Modulos Odoo"
$instalados = @()
if ((Invoke-Sql $Base "SELECT to_regclass('ir_module_module') IS NOT NULL") -eq "t") {
    $instalados = @((Invoke-Sql $Base "SELECT name FROM ir_module_module WHERE state='installed'") -split '\r?\n' | Where-Object { $_ })
}
$nuevos = @($Modulos | Where-Object { $instalados -notcontains $_ })
$ya = @($Modulos | Where-Object { $instalados -contains $_ })

if ($nuevos.Count -gt 0) {
    Write-Host "      Instalando (-i): $($nuevos -join ', ')"
    Invoke-Compose @('exec', '-T', 'odoo', '/entrypoint.sh', 'odoo', '-d', $Base, '-i', ($nuevos -join ','), '--without-demo=all', '--stop-after-init')
}
if ($ya.Count -gt 0) {
    Write-Host "      Actualizando (-u): $($ya -join ', ')"
    Invoke-Compose @('exec', '-T', 'odoo', '/entrypoint.sh', 'odoo', '-d', $Base, '-u', ($ya -join ','), '--stop-after-init')
}
Invoke-Compose @('restart', 'odoo')
Invoke-Compose @('up', '-d', '--wait')

# Sincroniza la secuencia de tc_users (Traccar) con las filas existentes: evita el duplicate key de POST /api/users
# (causa en docs/decisiones_fase1.md, Tarea 4). Idempotente: solo avanza la secuencia, nunca la retrocede.
$SqlSecuenciaTraccar = "SELECT setval('tc_users_id_seq', GREATEST((SELECT COALESCE(MAX(id), 1) FROM tc_users), (SELECT last_value FROM tc_users_id_seq)), true)"
try {
    Invoke-Sql "traccar" $SqlSecuenciaTraccar | Out-Null
} catch {
    throw "No se pudo sincronizar la secuencia tc_users_id_seq de la base traccar: $($_.Exception.Message)"
}
Write-Host "      Secuencia tc_users_id_seq sincronizada (base traccar)."

Write-Host "[5/5] Datos de prueba (seeds/seed.py) en el host"
if (Test-Path seeds\seed.py) {
    # Carga las claves de .env en el proceso; los valores no se imprimen.
    foreach ($clave in $vars.Keys) { Set-Item -Path "env:$clave" -Value $vars[$clave] }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python seeds\seed.py
    } else {
        & py -3 seeds\seed.py
    }
    if ($LASTEXITCODE -ne 0) { throw "El sembrado fallo (codigo $LASTEXITCODE)." }
} else {
    Write-Host "      AVISO: seeds\seed.py no existe todavia (pendiente: Tarea 3 del plan). Se omite el sembrado." -ForegroundColor Yellow
}

Write-Host "Listo. ERP Odoo: http://localhost:8069/web/login | Traccar: http://localhost:8082" -ForegroundColor Green
Write-Host "Credenciales: las de .env (no se muestran aqui)."
