# Pruebas

Desde la raíz del repositorio.

## Estáticas (sin Docker)

Recorren el código. No usan la red ni `.env`.

```powershell
python -m unittest tests.estatico.test_sin_datos_quemados -v
```

`scripts/verify_integration.py` es la única excepción conocida: tiene marca, modelo y una contraseña fija. Borrarlo sigue pendiente de aprobación. El resto del repo no debe repetir `uniqueId`, referencias de pedido, marca, modelo, clientes ni geocercas de `seeds/data/`, ni un literal `password = '...'`.

No se buscan placas ni nombres de persona. Esas cadenas ya están en las pruebas de ETL y BI, que son de otra fase. Un literal `password` dentro de una carpeta `tests/` tampoco cuenta: ahí la contraseña es un caso de prueba. Fuera de `tests/`, sí.

## Seeds (sin Docker)

```powershell
python -m unittest seeds.tests.test_simular seeds.tests.test_schema -v
```

## Odoo (contenedor)

Hace falta el stack y la base `logistica_dev`.

```powershell
docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_traccar --test-enable --test-tags /logistica_traccar --stop-after-init --log-level=test --http-port=8070
```

## Extremo a extremo (stack vivo)

Carga las variables de `.env` en el proceso y no imprime sus valores. Si falta alguna, las pruebas se omiten. Llaman a `action_sincronizar_ahora`, no a `sincronizar_todo`.

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim() }
}
python -m unittest tests.e2e.test_flujo -v
```

`test_reinicio_traccar_sin_perdidas` y `test_reinicio_odoo_sin_perdidas` reinician contenedores. Solo corren si además `E2E_REINICIO=1` (hace falta `docker` en el PATH de la consola):

```powershell
$env:E2E_REINICIO = "1"
python -m unittest tests.e2e.test_flujo -v
```

`seeds/simular.py` desplaza los timestamps de `simulacion.json` para que el último punto sea «ahora»: así cada corrida entra en la ventana de sincronización de Odoo.
