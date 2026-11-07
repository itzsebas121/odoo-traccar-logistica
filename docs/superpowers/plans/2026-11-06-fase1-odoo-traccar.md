# FASE 1 — Integración Odoo ↔ Traccar al 100% Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. **All subagents (implementers and reviewers) use the model `haiku` (claude-haiku-5-5), per the user's instruction.** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un solo comando levanta Odoo y Traccar sanos, siembra desde `seeds/` de forma idempotente, sincroniza posiciones, eventos y estado de dispositivos a Odoo sin pérdidas ni duplicados, y un simulador más pruebas E2E demuestran el flujo completo.

**Architecture:** El módulo `logistica_traccar` de Odoo ejecuta un cron que consulta la API REST de Traccar con un usuario de solo lectura, y guarda posiciones y eventos en tablas propias únicas por el id de Traccar; un watermark por dispositivo garantiza que nada se pierda y que reprocesar no duplique. `seeds/seed.py` aprovisiona ambos sistemas desde JSON en `seeds/data/` (solo stdlib). `seeds/simular.py` envía posiciones por el protocolo OsmAnd (puerto 5055). Las pruebas E2E corren desde el host contra el stack vivo.

**Tech Stack:** Odoo 16.0 (`odoo:16.0`, Python del contenedor, `requests`), Traccar (`traccar/traccar:latest`, API REST), PostgreSQL 15, Python 3 stdlib para seeds, simulador y E2E (`xmlrpc.client`, `urllib`), `unittest` para pruebas de Odoo (`TransactionCase`, `unittest.mock`).

**Spec:** `docs/flujo_funcional_odoo_traccar.md` (§5 M5, §6 completo, §12). El prompt de la Fase 1 del usuario es el diseño de esta fase.

## Decisiones de la fase (ver también docs/decisiones_fase1.md, Task 11)

| # | Decisión | Verificado en |
|---|---|---|
| F1-D1 | Llegada de datos: **polling por cron** (intervalo configurable, por defecto 1 min) con ventanas por dispositivo. Sin WebSocket ni webhook: §6.3 lo deja opcional y el polling se recupera solo de caídas. | — |
| F1-D2 | Odoo **no escribe** en Traccar durante la sincronización. Solo el seeder crea dispositivos, geocercas, permisos y el usuario de integración. | §2 principio de integración |
| F1-D3 | Eventos: `GET /api/reports/events` con `Accept: application/json`. Tipos: `deviceOverspeed`, `geofenceEnter`, `geofenceExit`, `deviceOnline`, `deviceOffline`. | Probado: 200 con JSON (lista vacía sin eventos) |
| F1-D4 | Reportes sin `Accept: application/json` devuelven XLSX binario. Todas las llamadas de reportes llevan ese encabezado. | Probado |
| F1-D5 | Odómetro = `attributes.totalDistance` de la posición, en metros, guardado en km. | Probado: el campo existe en posiciones OsmAnd |
| F1-D6 | Velocidad: Traccar entrega nudos; se convierte a km/h (1 nudo = 1,852 km/h), como ya hace el módulo. | Código existente |
| F1-D7 | Usuario de integración en Traccar: `readonly=true`, `administrator=false`. El admin solo se usa en el seeder. | Pendiente en Task 4 (ver bug de creación) |
| F1-D8 | Idempotencia: `unique` en `traccar_position_id` y `traccar_event_id`; watermark por dispositivo con solape de 60 s. | — |
| F1-D9 | Reintentos: 3 intentos por llamada HTTP con espera 1, 2 y 4 s. Si fallan, el watermark no avanza. Un dispositivo que falla no detiene a los demás. | — |
| F1-D10 | Ningún dato de negocio, credencial ni URL en el código. Datos en `seeds/data/*.json`; URLs y credenciales en `.env`. | Task 9 lo verifica |

## Global Constraints

- Sin credenciales, URLs, ids, placas, coordenadas ni nombres de negocio en código fuente. Origen: `seeds/data/*.json` y `.env`.
- Traccar: solo los endpoints probados (ver decisiones). Reportes siempre con `Accept: application/json`.
- Odoo: ninguna escritura sobre tablas de Traccar; `sudo()` solo en el cron y en la lectura de configuración del servidor.
- Usuario de integración con `readonly=true` y `administrator=false`.
- Fase 1 no implementa ETL, ML ni BI; solo deja consumibles las tablas de posiciones y eventos.
- Sin commits hasta que el usuario lo pida.
- Todos los subagentes usan `model: haiku`.

## Review Focus

1. **Traccar caído o lento:** no se pierden datos (el watermark no avanza) y no se bloquea a los demás dispositivos. → Task 6 `test_fallo_red_no_avanza_watermark`, `test_aislamiento_por_dispositivo`.
2. **Reprocesar la misma ventana:** no duplica posiciones ni eventos. → Task 6 `test_reprocesar_ventana_no_duplica`.
3. **Dispositivo sin vehículo vinculado:** se ignora sin error y sin registro. → Task 6 `test_dispositivo_sin_vehiculo_ignorado`.
4. **Posición inválida (latitud fuera de rango, o 0,0):** se descarta y se cuenta, no rompe la sincronización. → Task 6 `test_posicion_invalida_se_descarta`.
5. **Reinicio de Traccar u Odoo durante la sincronización:** sin pérdidas ni duplicados. → Task 9 `test_reinicio_traccar_sin_perdidas`, `test_reinicio_odoo_sin_perdidas`.

---

### Task 1: Cierre del pendiente de ETL (`dwh_ro` sin conexión a staging)

**Files:**
- Modify: `services/etl/etl/__main__.py` (función `bootstrap`, bloque de roles y permisos de conexión)
- Test: `services/etl/tests/test_roles.py` (nuevo)

**Interfaces:**
- Consumes: `bootstrap(admin_dsn, ..., ro_role)` existente; variables `ETL_STG_PASSWORD`, `DWH_ETL_PASSWORD`, `DWH_DB_PASSWORD`.
- Produces: bootstrap idempotente que deja `has_database_privilege('dwh_ro','logistica_staging','CONNECT') = false` y `...'logistica_dwh','CONNECT') = true`.

- [ ] **Step 1: Escribir la prueba que falla** (`test_roles.py`): con un rol temporal `dwh_ro_t_<hex>` creado con contraseña, intentar `psycopg2.connect` a `logistica_staging` debe lanzar `InsufficientPrivilege`; a `logistica_dwh` debe conectar. La prueba borra el rol al final.
- [ ] **Step 2: Ejecutar y verificar que falla.** `docker compose run --rm --entrypoint pytest etl -q services/etl/tests/test_roles.py` → FAIL (la conexión a staging sí abre sesión).
- [ ] **Step 3: Implementar.** En `bootstrap`: `REVOKE CONNECT ON DATABASE logistica_staging FROM PUBLIC`, `GRANT CONNECT ON DATABASE logistica_staging TO etl_stg`; lo mismo para `logistica_dwh` con `dwh_etl` y `dwh_ro`. Son idempotentes.
- [ ] **Step 4: Ejecutar pruebas** → `pytest etl -q` completo en verde.
- [ ] **Step 5: Aplicar en vivo.** `docker compose --profile etl run --rm etl bootstrap`; luego `docker compose exec -T db psql -U odoo -d postgres -tAc "select has_database_privilege('dwh_ro','logistica_staging','CONNECT'), has_database_privilege('dwh_ro','logistica_dwh','CONNECT')"` → esperado `f|t`.

---

### Task 2: Healthchecks y arranque de un solo comando

**Files:**
- Modify: `compose.yaml` (healthchecks de `odoo` y `traccar`)
- Rewrite: `scripts/setup.ps1` y `scripts/setup.sh`
- Delete: `scripts/verify_integration.py` (contiene una contraseña fija; lo reemplaza el E2E de Task 9)

**Interfaces:**
- Consumes: servicios `db`, `odoo`, `traccar` de `compose.yaml`; `seeds/seed.py` (Task 3, se invoca al final del script; mientras no exista, el paso se omite con aviso).
- Produces: `setup.ps1` / `setup.sh` que hacen: (1) crear `.env` desde `.env.example` solo si no existe; (2) `docker compose up -d --wait`; (3) crear la base `logistica_dev` si falta (`createdb -O odoo` dentro de `db`); (4) instalar los módulos con `-i` si no están instalados, o `-u` si ya lo están; (5) ejecutar `seeds/seed.py`.

- [ ] **Step 1: Averiguar qué herramientas de healthcheck existen** en las imágenes: `docker compose exec traccar sh -c "command -v wget; command -v curl"` y `docker compose exec odoo python3 -c "import urllib.request"`. Registrar el resultado en `docs/decisiones_fase1.md`.
- [ ] **Step 2: Escribir los healthchecks** en `compose.yaml`: `odoo` con `python3 -c` sobre `http://127.0.0.1:8069/web/login`; `traccar` con `http://127.0.0.1:8082/api/server` usando la herramienta confirmada en el paso 1. Verificar que `/api/server` responde 200 sin autenticación; si no, usar la ruta que sí responda sin credenciales y anotarlo.
- [ ] **Step 3: Verificar** `docker compose up -d --wait` → `db`, `odoo` y `traccar` en `healthy`. Salida esperada: los tres servicios con `(healthy)` en `docker compose ps`.
- [ ] **Step 4: Escribir `setup.ps1` y `setup.sh`** con los 5 pasos de arriba. Ninguno escribe credenciales en el código; toman todo de `.env`.
- [ ] **Step 5: Ejecutar el script dos veces** (`powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`). La segunda ejecución no debe fallar ni recrear datos. Salida esperada: segunda vez con los módulos en `-u` y sin errores.

---

### Task 3: Seeds en JSON y seeder idempotente

**Files:**
- Create: `seeds/data/odoo.json`, `seeds/data/traccar.json`, `seeds/data/simulacion.json`
- Create: `seeds/schema.py` (validación de cada JSON: campos obligatorios y tipos), `seeds/seed.py` (CLI), `seeds/tests/test_schema.py`
- Delete: `seeds/demo_data.py`
- Modify: `.env.example` (nuevas variables: `INTEGRATION_TRACCAR_EMAIL`, `INTEGRATION_TRACCAR_PASSWORD`, `TRACCAR_ADMIN_EMAIL`)

**Interfaces:**
- Consumes: Odoo XML-RPC (`/xmlrpc/2/common`, `/xmlrpc/2/object`, modelos `res.partner`, `fleet.vehicle`, `traccar.server`, `traccar.device`); Traccar REST con admin (`/api/devices`, `/api/geofences`, `/api/permissions`, `/api/users`).
- Produces: CLI `python seeds/seed.py` con variables de entorno `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`, `TRACCAR_URL`, `TRACCAR_ADMIN_EMAIL`, `TRACCAR_ADMIN_PASSWORD`, `INTEGRATION_TRACCAR_EMAIL`, `INTEGRATION_TRACCAR_PASSWORD`. Imprime un JSON `{"creados": [...], "actualizados": [...], "omitidos": [...]}`.

**Contenido de `seeds/data/`** (los valores los define el implementador a partir de la especificación §11: bodega, tres vehículos y conductores, cinco pedidos). Cada dispositivo de `traccar.json` tiene `uniqueId`, `name`, `attributes.speedLimit` (en nudos, verificado en Task 8), y cada vehículo de `odoo.json` referencia el `uniqueId` de su dispositivo. Geocerca: `{"name", "area": "CIRCLE (lat lon, radio_m)"}`.

- [ ] **Step 1: Escribir las pruebas de esquema que fallan** (`test_schema.py`): un JSON sin `uniqueId` falla con mensaje que nombra el campo; un vehículo que referencia un `uniqueId` inexistente falla; un JSON válido pasa.
- [ ] **Step 2: Ejecutar** `python -m unittest seeds.tests.test_schema -v` → FAIL.
- [ ] **Step 3: Implementar `schema.py`** y los JSON. Ningún valor de negocio aparece en `seed.py`.
- [ ] **Step 4: Implementar `seed.py`** con claves naturales: `fleet.vehicle` por `license_plate`; `res.partner` por `name`; `traccar.device` por `uniqueId`; geocerca por `name`; usuario por `email`; permiso por par (dispositivo, geocerca). Crea solo lo que falta y reporta. Después llama a `traccar.server.action_sync_devices` y vincula cada `fleet.vehicle.traccar_device_id` por `uniqueId`.
- [ ] **Step 5: Ejecutar dos veces** `python seeds/seed.py`. Verificar con XML-RPC que la segunda ejecución reporta `creados: []`.

---

### Task 4: Usuario de integración en Traccar con mínimos permisos

**Files:**
- Modify: `seeds/seed.py` (sección Traccar)
- Modify: `seeds/data/traccar.json` (sección `usuarios`)
- Document: `docs/decisiones_fase1.md` (causa del fallo y workaround)

**Interfaces:**
- Consumes: `POST /api/users` con admin.
- Produces: usuario `INTEGRATION_TRACCAR_EMAIL` con `readonly=true`, `administrator=false`; `traccar.server` de Odoo configurado con esas credenciales (no con admin).

- [ ] **Step 1: Reproducir el fallo conocido.** `POST /api/users` con admin devolvió `duplicate key value violates unique constraint "tc_users_pkey"`, `Key (id)=(1)`, aunque la secuencia `tc_users_id_seq` está en `last_value=1, is_called=true`. Probar en orden: (a) body mínimo sin `readonly` ni `administrator`; (b) con `readonly=true`; (c) con `administrator=false`. Registrar cuál falla.
- [ ] **Step 2: Identificar la causa** con los logs del contenedor (`docker compose logs traccar --tail 200`) y, si hace falta, la tabla `tc_users` (`select id, email, readonly, administrator from tc_users`). Anotar la causa en `docs/decisiones_fase1.md`.
- [ ] **Step 3: Aplicar el workaround documentado** si la causa es de la base de datos (por ejemplo, sincronizar la secuencia con `select setval('tc_users_id_seq', (select max(id) from tc_users), true)` en el setup). Si es un problema de la API, documentar la alternativa usada.
- [ ] **Step 4: Verificar mínimos permisos** con el usuario creado: `GET /api/devices` → 200; `GET /api/positions?deviceId=X` → 200; `GET /api/reports/route` con `Accept: application/json` → 200; `POST /api/devices` → 401 o 403. Los resultados se anotan en `docs/decisiones_fase1.md`.
- [ ] **Step 5: Configurar `traccar.server` de Odoo** con las credenciales del usuario de integración desde `seed.py`. Verificar con `action_test_connection` por XML-RPC.

---

### Task 5: Odoo — modelos de posiciones y eventos (`logistica_traccar`)

**Files:**
- Create: `odoo/addons/logistica_traccar/models/logistica_traccar_posicion.py`, `models/logistica_traccar_evento.py`, `models/logistica_traccar_util.py` (conversiones puras: `knots_to_kmh`, `valid_latlon`, `meters_to_km`)
- Modify: `odoo/addons/logistica_traccar/models/traccar_device.py` (campos `position_watermark` Datetime, `is_active` Boolean)
- Modify: `odoo/addons/logistica_traccar/models/__init__.py`, `security/ir.model.access.csv` (lectura para `base.group_user`; sin escritura desde UI)
- Create: `odoo/addons/logistica_traccar/tests/test_modelos.py`

**Interfaces:**
- Produces:
  - `logistica.traccar.posicion`: `device_id` (Many2one `traccar.device`, ondelete cascade), `vehicle_id` (Many2one `fleet.vehicle`), `traccar_position_id` (Integer, required), `fix_time` (Datetime, required), `latitude`, `longitude` (Float), `speed_kmh` (Float), `odometer_km` (Float), `valid` (Boolean). `_sql_constraints = [('traccar_position_uniq', 'unique(traccar_position_id)', ...)]`.
  - `logistica.traccar.evento`: `device_id`, `vehicle_id`, `traccar_event_id` (Integer, unique), `event_type` (Char), `event_time` (Datetime), `geofence_traccar_id` (Integer), `position_traccar_id` (Integer), `attributes` (Text).
  - `logistica_traccar_util`: `knots_to_kmh(knots: float) -> float` (×1,852, redondeo 2 decimales); `valid_latlon(lat, lon) -> bool` (−90≤lat≤90, −180≤lon≤180, y no ambos cero); `meters_to_km(m) -> float`.

- [ ] **Step 1: Escribir pruebas que fallan:** `knots_to_kmh(10) == 18.52`; `valid_latlon(0, 0) is False`; `valid_latlon(95, 0) is False`; crear dos posiciones con el mismo `traccar_position_id` lanza `IntegrityError` (o `ValidationError`).
- [ ] **Step 2: Ejecutar** la prueba de Odoo: `MSYS_NO_PATHCONV=1 docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_traccar --test-enable --test-tags /logistica_traccar --stop-after-init --log-level=test --http-port=8070` → FAIL.
- [ ] **Step 3: Implementar** los modelos, la util y los accesos.
- [ ] **Step 4: Ejecutar** el mismo comando → `0 failed, 0 error(s)`.

---

### Task 6: Odoo — conector de sincronización (`traccar.server`)

**Files:**
- Modify: `odoo/addons/logistica_traccar/models/traccar_server.py`
- Modify: `odoo/addons/logistica_traccar/models/traccar_device.py` (método `_registrar_posicion`)
- Modify: `odoo/addons/logistica_traccar/models/fleet_vehicle.py` (actualizar última posición del vehículo desde la posición más reciente)
- Create: `odoo/addons/logistica_traccar/tests/test_conector.py` (con `unittest.mock.patch` sobre `requests`)

**Interfaces:**
- `traccar.server._request(self, path: str, params: dict | None = None) -> list | dict`: `GET {base_url}{path}` con `Accept: application/json` y autenticación del servidor; 3 intentos con esperas 1, 2 y 4 s; al agotar, lanza `UserError` y registra `last_error_message`.
- `traccar.server.sincronizar_posiciones(self, desde: datetime, hasta: datetime) -> int`: por dispositivo vinculado a un vehículo, `GET /api/positions?deviceId=<id>&from=<iso>&to=<iso>`; devuelve el número de posiciones nuevas.
- `traccar.server.sincronizar_eventos(self, desde, hasta) -> int`: `GET /api/reports/events?deviceId=<id>&from=..&to=..&type=deviceOverspeed&type=geofenceEnter&type=geofenceExit&type=deviceOnline&type=deviceOffline`.
- `traccar.server.cron_sincronizar(self) -> None`: por cada servidor activo, por dispositivo, ventana `[position_watermark − 60 s, ahora]`; cada dispositivo en `try/except` aislado; el watermark solo avanza al máximo `fix_time` procesado y solo si no hubo error. Registra `key=value` con `_logger.info`.
- `traccar.server.sincronizar_todo(self) -> dict`: llama a dispositivos, posiciones y eventos; lo usan el cron y el botón manual.

- [ ] **Step 1: Escribir pruebas que fallan** (con `requests` parcheado):
  - `test_mapeo_nudos_y_odometro`: una posición con `speed=10`, `attributes.totalDistance=5000` → `speed_kmh=18.52`, `odometer_km=5.0`.
  - `test_idempotencia`: dos llamadas con la misma respuesta → una sola posición.
  - `test_reprocesar_ventana_no_duplica`: dos sincronizaciones sobre la misma ventana → mismo número de registros.
  - `test_fallo_red_no_avanza_watermark`: `requests.ConnectionError` en las tres intentos → `UserError`, watermark sin cambios.
  - `test_reintentos_backoff`: 3 llamadas y esperas `[1, 2]` (la tercera falla y no espera).
  - `test_aislamiento_por_dispositivo`: el primer dispositivo falla y el segundo se sincroniza.
  - `test_dispositivo_sin_vehiculo_ignorado`: dispositivo sin `vehicle_id` → cero posiciones y sin error.
  - `test_posicion_invalida_se_descarta`: latitud 95 o 0,0 → se omite y el conteo de descartadas sube.
- [ ] **Step 2: Ejecutar** y verificar FAIL.
- [ ] **Step 3: Implementar** según la interfaz. `sudo()` solo en `cron_sincronizar` para leer los servidores y dispositivos.
- [ ] **Step 4: Ejecutar** las pruebas → `0 failed, 0 error(s)`.
- [ ] **Step 5: Verificar la forma real de la respuesta de eventos** contra Traccar en vivo (se hace con datos en Task 8); si el parámetro `type` repetido no funciona, documentar la forma correcta en `docs/decisiones_fase1.md` y ajustar.

---

### Task 7: Cron, botón manual y configuración

**Files:**
- Create: `odoo/addons/logistica_traccar/data/traccar_cron.xml` (`ir.cron` que llama a `traccar.server` método `cron_sincronizar`, `interval_number` leído de `logistica.traccar_poll_minutes`)
- Create: `odoo/addons/logistica_traccar/data/traccar_config.xml` (parámetro `logistica.traccar_poll_minutes` = 1)
- Modify: `odoo/addons/logistica_traccar/views/traccar_server_views.xml` (botón «Sincronizar ahora» → `sincronizar_todo`)
- Modify: `odoo/addons/logistica_traccar/__manifest__.py` (data)
- Create: `odoo/addons/logistica_traccar/tests/test_cron.py`

**Interfaces:**
- Consumes: Task 6.

- [x] **Step 1: Pruebas que fallan:** existe un `ir.cron` activo cuyo `code` contiene `cron_sincronizar`; el botón está en la vista; el parámetro vale `1` por defecto. Quedaron en `tests/test_cron.py`.
- [ ] **Step 2: Ejecutar** y verificar FAIL. No se corrió el rojo: las pruebas se escribieron en el mismo cambio que el XML.
- [x] **Step 3: Implementar** los XML.
- [ ] **Step 4: Ejecutar** `-u logistica_traccar --test-tags /logistica_traccar` → `0 failed, 0 error(s)`. Pendiente de la corrida en el contenedor.

**Hecho el 2026-11-07, con dos desviaciones respecto al texto de arriba:**

- El botón llama a `action_sincronizar_ahora`, no a `sincronizar_todo`. Ese método quedó privado en la tarea 6; el README de estado ya lo pedía así.
- No se creó `data/traccar_config.xml`. El parámetro `logistica.traccar_poll_minutes = 1` ya está en `logistica_base/data/logistica_config_data.xml`. Un segundo registro sería otro dueño de la misma clave. El `interval_number` del cron es 1, el mismo valor. Odoo no relee el parámetro al disparar el cron.

---

### Task 8: Simulador OsmAnd y verificación de eventos en Traccar

**Files:**
- Create: `seeds/simular.py` (stdlib; lee `seeds/data/simulacion.json`; envía `GET {osmand_url}/?id=<uniqueId>&lat=<lat>&lon=<lon>&speed=<nudos>&timestamp=<unix_s>`)
- Modify: `seeds/data/simulacion.json` (rutas por dispositivo con velocidad sobre el `speedLimit` en un tramo y un cruce de geocerca)
- Create: `seeds/tests/test_simular.py` (construcción de URLs y validación; sin red)

**Interfaces:**
- Produces: CLI `python seeds/simular.py` con variables `TRACCAR_OSMAND_URL` (por defecto no; obligatoria desde `.env`, ej. `http://127.0.0.1:5055`) y `SIM_INTERVALO_S` (opcional, 0 por defecto). Retorna el número de posiciones enviadas y falla si el servidor responde distinto de 200.

- [ ] **Step 1: Verificar en vivo** el umbral de velocidad: crear un dispositivo de prueba con `attributes.speedLimit`, enviar una posición por encima del límite, consultar `/api/reports/events?deviceId=...&type=deviceOverspeed` (con Accept JSON). Anotar en `docs/decisiones_fase1.md` si `speedLimit` está en nudos o km/h. Borrar el dispositivo de prueba al final. Sigue pendiente: en esta máquina no había stack sembrado.
- [x] **Step 2: Escribir pruebas que fallan** (`test_simular.py`): la URL contiene `id`, `lat`, `lon`, `speed` y `timestamp` en segundos; un JSON sin `uniqueId` falla. No se corrió el rojo: las pruebas se escribieron en el mismo cambio que el simulador.
- [x] **Step 3: Implementar** `simular.py` y `simulacion.json`.
- [x] **Step 4: Ejecutar** `python -m unittest seeds.tests.test_simular seeds.tests.test_schema -v` → 13 OK (2026-11-07).
- [ ] **Step 5: Ejecutar** el simulador contra Traccar en vivo y comprobar que `/api/positions` y `/api/reports/events` muestran `deviceOverspeed` y `geofenceEnter` para el dispositivo de prueba de la simulación.

---

### Task 9: Pruebas E2E y pruebas estáticas

**Files:**
- Create: `tests/e2e/test_flujo.py` (stdlib + `unittest`; sincroniza con Odoo por XML-RPC llamando a `sincronizar_todo`; lee Traccar por REST; ejecuta `seeds/seed.py` y `seeds/simular.py` con `subprocess`)
- Create: `tests/estatico/test_sin_datos_quemados.py` (recorre el repo excluyendo `seeds/data/`, `.env*`, `docs/`, `backups/`; falla si encuentra cualquier valor no vacío de las variables de `.env` o los identificadores de negocio de `seeds/data/`)
- Create: `tests/README.md` (cómo correr cada suite)

**Interfaces:**
- Consumes: Tasks 2–8.

**Hecho el 2026-11-07, con desviaciones:** el E2E llama a `action_sincronizar_ahora`, no a `sincronizar_todo`. El escaneo no busca placas ni nombres de persona (ya viven en las pruebas de ETL/BI). Un literal `password` dentro de `tests/` no cuenta. `scripts/verify_integration.py` es la única excepción, a la espera de que se apruebe borrarlo. Los reinicios solo corren con `E2E_REINICIO=1`.

- [x] **Step 1: Escribir las pruebas E2E que fallan:**
  - `test_seed_idempotente`: dos ejecuciones de `seed.py` → la segunda reporta `creados: []`.
  - `test_posicion_en_odoo_vehiculo_correcto`: tras simular y sincronizar, la última posición del dispositivo de un vehículo aparece en `logistica.traccar.posicion` con su `vehicle_id` correcto.
  - `test_evento_overspeed_y_geocerca_en_odoo`: existen `logistica.traccar.evento` de tipo `deviceOverspeed` y `geofenceEnter`.
  - `test_reinicio_traccar_sin_perdidas`: contar posiciones, `docker compose restart traccar`, esperar healthy, simular un lote nuevo, sincronizar; el conteo sube exactamente por el lote nuevo y no hay duplicados.
  - `test_reinicio_odoo_sin_perdidas`: igual, con `docker compose restart odoo`.
  - `test_sin_datos_quemados`: pasa el escaneo estático.
- [ ] **Step 2: Ejecutar** `python -m unittest discover -s tests -v` → FAIL donde aún no esté implementado. No se corrió el rojo: las pruebas se escribieron junto con el escáner.
- [x] **Step 3: Implementar** los helpers y completar hasta que pasen.
- [ ] **Step 4: Ejecutar** la suite completa desde el host, con las variables de `.env` cargadas. Pendiente: aquí no hay `.env`. Lo estático sí corrió: `python -m unittest tests.estatico.test_sin_datos_quemados tests.e2e.test_flujo seeds.tests.test_simular seeds.tests.test_schema -v` → 16 OK, 5 omitidas (2026-11-07).

---

### Task 10: Verificación desde un entorno limpio

**Files:** ninguno del repositorio. Un override de puertos en `$SCRATCHPAD` (fuera del repo).

**Interfaces:**
- Consumes: `scripts/setup.ps1`, `seeds/seed.py`, `tests/`.

- [ ] **Step 1: Crear el override** `$SCRATCHPAD/puertos-limpio.yaml` que cambia `odoo` a `127.0.0.1:18069:8069`, `traccar` a `127.0.0.1:18082:8082` y `5055` a `15055:5055`.
- [ ] **Step 2: Levantar un proyecto aparte** `docker compose -p fase1limpia -f compose.yaml -f <override> up -d --wait`. El stack de desarrollo no se toca.
- [ ] **Step 3: Sembrar y probar** con las URLs del proyecto limpio (`ODOO_URL=http://127.0.0.1:18069`, `TRACCAR_URL=http://127.0.0.1:18082`, `TRACCAR_OSMAND_URL=http://127.0.0.1:15055`). Ejecutar `scripts/setup` (instala módulos desde cero) y luego `python -m unittest discover -s tests -v`.
- [ ] **Step 4: Limpiar** `docker compose -p fase1limpia -f compose.yaml -f <override> down -v` (solo borra volúmenes de ese proyecto).

---

### Task 11: Documentación y checklist de la Fase 1

**Files:**
- Modify: `README.md` (cómo levantar con un comando, variables de entorno, seeds, simulación, pruebas, mapeo de entidades, checklist de Fase 1 con estado real)
- Create: `docs/decisiones_fase1.md` (todas las decisiones F1-D1…F1-D10 y los hallazgos de Tasks 2, 4 y 8)
- Modify: `docs/estado_implementacion.md` (estado de Fase 1 con enlace)

**Interfaces:**
- Consumes: resultados reales de Tasks 1–10. Cada casilla del checklist se marca solo con evidencia del paso de verificación correspondiente.
- Produce: sección «Preparación para Fase 2 (ETL/ML/BI)» que lista, sin implementar, las tablas `logistica.traccar.posicion` y `logistica.traccar.evento` y el servicio `traccar.server.sincronizar_*` como puntos de enganche.

- [ ] **Step 1: Escribir README y decisiones** con los comandos reales ejecutados.
- [ ] **Step 2: Verificar** que cada comando del README se ejecutó tal cual en Task 10.

---

### Task 12: Cierre y evidencia

- [ ] **Step 1:** Detener los contenedores de analítica que no se usan en esta fase: `docker compose stop bi ml`.
- [ ] **Step 2:** Ejecutar la suite completa en el stack de desarrollo y guardar la salida en `$SCRATCHPAD`.
- [ ] **Step 3:** Ejecutar `grep` de credenciales y valores de negocio fuera de `seeds/data/` y `.env`; el resultado debe ser vacío.
- [ ] **Step 4:** Reportar al usuario con los comandos y su salida. No se hace commit hasta que lo pida.
