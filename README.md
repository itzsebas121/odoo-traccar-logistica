# Sistema Inteligente de Rastreo y Analítica de Rutas

Proyecto universitario integrador que combina **Odoo 16 Community**, **Traccar GPS Server**, motor de optimización de rutas, procesos ETL, PostgreSQL, almacén dimensional (DWH), analítica de datos e inteligencia artificial predictiva.

---

## 🚧 Estado del proyecto y pendientes (actualizado 2026-11-07)

Esta sección es el punto de partida para seguir implementando. Lo que aquí se lista es el estado real verificado con pruebas y revisiones; lo que no está listo se marca como pendiente.

### Qué está hecho

| Parte | Estado | Verificado con |
|---|---|---|
| Servicio de rutas (`services/routing`): matriz, ruta y optimización con capacidad | Hecho y revisado | 38 pruebas |
| Servicio de predicción (`services/ml`): entrenamiento temporal, métricas, `/predict` | Hecho y revisado | 9 pruebas |
| ETL y DWH (`services/etl`): staging, calidad, modelo dimensional, una base por componente | Hecho y revisado | 43 pruebas |
| Dashboard BI (`services/bi`): consultas OLAP sobre el DWH, filtro de fecha única corregido | Hecho y revisado | 5 pruebas (1 se omite fuera de la imagen) |
| Módulo `logistica_base`: bodega, configuración, zonas, capacidad, dispositivo GPS único | Hecho y revisado | 5 pruebas |
| Módulo `logistica_entregas`: entrega por pedido, máquina de estados, eventos, token de seguimiento | Hecho y revisado (4 rondas de correcciones) | 17 pruebas |
| Módulo `logistica_checkout`: checkout con mapa, pago de prueba, seguimiento público | Hecho y revisado | 9 pruebas |
| Fase 1 · Tarea 1: `dwh_ro` sin conexión a la base de staging | Hecho y revisado | 43 pruebas del ETL |
| Fase 1 · Tarea 2: arranque con un comando (`scripts/setup.ps1`, `scripts/setup.sh`), healthchecks, chequeo de placeholders | Hecho y revisado (Windows probado en vivo; Linux solo sintaxis) | Corridas en vivo |
| Fase 1 · Tarea 3: seeds en JSON (`seeds/data/`) y seeder idempotente (`seeds/seed.py`) | Hecho y revisado | 6 pruebas de esquema; idempotencia probada en vivo |
| Fase 1 · Tarea 4: usuario de integración en Traccar (solo lectura), sincronización de la secuencia de usuarios | Hecho y revisado | Verificado en vivo |
| Fase 1 · Tarea 5: modelos de posiciones y eventos en Odoo, con restricciones únicas | Hecho y revisado | 17 pruebas |
| Fase 1 · Tarea 6: conector de sincronización (posiciones, eventos, watermark, reintentos, aislamiento por dispositivo) | Hecho y revisado (4 rondas de correcciones y revisión de seguridad) | 53 pruebas |
| Fase 1 · Tarea 7: `ir.cron` cada minuto llama a `cron_sincronizar`; botón «Sincronizar ahora» llama a `action_sincronizar_ahora` | Implementada. La suite de Odoo no se ejecutó: Docker Desktop estaba apagado y no hay `.env` en esta máquina | `odoo/addons/logistica_traccar/tests/test_cron.py` (3 pruebas, sin correr) |
| Fase 1 · Tarea 8: `seeds/simular.py` envía la ruta OsmAnd de `simulacion.json` | Hecho y verificado en vivo (2026-11-07): genera `deviceOverspeed` y `geofenceEnter`; `speedLimit` va en nudos | `python -m unittest seeds.tests.test_simular seeds.tests.test_schema` → 13 OK; eventos consultados en la API de Traccar |
| Fase 1 · Tarea 9: escaneo estático y pruebas E2E | El escaneo pasa, con `scripts/verify_integration.py` como única excepción conocida. El E2E corrió contra el stack vivo (2026-11-07): 3 pruebas OK y 3 defectos corregidos (simulador como script, timestamps del simulador, permiso de geocerca del usuario de integración). Con `E2E_REINICIO=1` pasan también los 2 reinicios de contenedor | `python -m unittest tests.e2e.test_flujo -v` → 5 OK; `tests.estatico` + `seeds.tests` → 17 OK |
| Fase 1 · Tarea 10: verificación desde un entorno limpio | Hecho (2026-11-07): proyecto de compose aparte con puertos 18069/18082/15055 y volúmenes propios; `setup.ps1` termina con código 0 y `tests/` pasa 8 de 8 con reinicios. Encontró 3 defectos (administrador inicial de Traccar, variables de entorno en `setup.ps1`, carrera en el E2E de eventos), ya corregidos. `setup.sh` no recibió el ajuste de variables | Corrida completa desde cero; detalle en `docs/decisiones_fase1.md` |
| Fase 1 · Tarea 11: documentación | Hecho (2026-11-07): comandos, variables, mapeo Odoo ↔ Traccar, checklist con evidencia y preparación para la Fase 2; textos desactualizados de `docs/decisiones_fase1.md` corregidos | Revisión contra lo ejecutado en las Tareas 8 a 10 |

### Qué falta

**Fase 1, tareas que no se han empezado:**

- **Tarea 9 — solo queda una decisión tuya.** El E2E completo (5 pruebas, con reinicios) ya pasa contra el stack vivo. `scripts/verify_integration.py` queda como excepción del escaneo hasta que se apruebe borrarlo.
- **Tarea 12 — cierre.** Evidencia final de todas las suites y revisión de credenciales fuera de `seeds/data/` y `.env`.

**Pendientes de seguridad (prioridad alta, ya en `main` o en esta misma subida):**

1. **«Probar Conexión» no tiene control de gestor** (`traccar.server.action_test_connection`). Cualquier usuario interno puede dispararlo y hacer que Odoo envíe la credencial de Traccar a la `base_url` configurada por un gestor. Corrección: llamar a `_exigir_gestor_flota()` al inicio del método.
2. **Mensajes de error con cabeceras.** `_request` guarda `str(exc)` en `last_error_message`, que los usuarios internos pueden leer. Redactar la cabecera de autorización antes de guardar.
3. **Migración de la contraseña.** Si hay conflicto o tras la copia, puede quedar texto plano en la columna vieja o en tuplas muertas. Considerar `DROP COLUMN` solo después de una copia exitosa.
4. **`scripts/verify_integration.py` contiene la contraseña de admin de Traccar en código.** Su borrado fue denegado por el clasificador de permisos y **requiere tu aprobación**.
5. **Credenciales expuestas en un transcript de sesión.** Se imprimieron las líneas de `TRACCAR_ADMIN_PASSWORD` e `INTEGRATION_TRACCAR_PASSWORD` en un subagente. **Decisión tuya:** rotar la contraseña del usuario de integración (el seeder actualiza el usuario cuando la contraseña se rechaza). La de admin es tu login: no se rota sin tu decisión.
6. **Historial de git.** La contraseña fija de `seeds/demo_data.py` (ya borrado en esta subida) sigue en el historial de los commits anteriores. Rotar esa contraseña de desarrollo.

**Pendientes de decisión tuya:**

- Aprobar el borrado de `scripts/verify_integration.py`.
- Confirmar que se quitó la restauración desde `database/snapshot/` en `setup.ps1` y `setup.sh` (ruling F1-R10: `seeds/data/` es la única fuente de datos de ejemplo). El snapshot sigue en el repositorio.
- Validar las coordenadas, el emparejamiento conductor–vehículo y las marcas de `seeds/data/`: son ilustrativas, no reales.

**Menores diferidos (no bloquean; revisar antes de cerrar la entrega):**

- Seeder: sin timeout en XML-RPC; el informe se pierde si hay error; `active_test=False` trata archivados como presentes; `traccar.server` se identifica por `base_url`; errores de JSON y de respuestas vacías producen trazas en lugar de mensajes.
- Conector: reintento también en respuestas 4xx (debe ser solo en errores de conexión y 5xx); un dispositivo sin posición válida vuelve a pedir todo su historial en cada corrida; falta prueba de «posiciones correctas, eventos fallan»; `traccar.device.vehicle_id` es un campo inerte que hay que quitar de las vistas.
- ETL: limpieza de roles de prueba sin guardas; helper de prueba repetido.
- BI: selección de fecha única (corregido); SIMULADO solo marcado con un aviso.

### Cómo levantar el entorno

```powershell
# Núcleo: Odoo, Traccar y PostgreSQL (healthchecks incluidos)
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

# Analítica bajo demanda (routing, ml, bi)
docker compose --profile analitica up -d

# ETL bajo demanda (requiere ODOO_PASSWORD, ETL_STG_PASSWORD y DWH_ETL_PASSWORD en .env)
docker compose --profile etl run --rm etl bootstrap
docker compose --profile etl run --rm etl run --mode full
```

Variables nuevas en `.env` (no se suben al repositorio; ver `.env.example`): `ETL_STG_PASSWORD`, `DWH_ETL_PASSWORD`, `DWH_DB_PASSWORD` (rol `dwh_ro`), `ODOO_PASSWORD`, `INTEGRATION_TRACCAR_EMAIL` e `INTEGRATION_TRACCAR_PASSWORD`, `TRACCAR_ADMIN_EMAIL`, `TRACCAR_INTERNAL_URL`.

### Decisiones tomadas sin consultar

Las decisiones están en `docs/decisiones_fase1.md` y en el plan `docs/superpowers/plans/2026-11-06-fase1-odoo-traccar.md`. Las más importantes:

- Las bases son una por componente, sin esquemas: `logistica_dev` (Odoo), `traccar`, `logistica_staging` (ETL) y `logistica_dwh` (DWH). Todas en el mismo contenedor `db`.
- La sincronización es por sondeo (cron), no por WebSocket ni webhook. Odoo no escribe en Traccar durante la sincronización.
- La vinculación vehículo–dispositivo vive solo en `fleet.vehicle.traccar_device_id`.
- Las escrituras de sincronización van con `sudo()`; los usuarios normales solo leen posiciones y eventos.
- El secreto de Traccar vive en un modelo que los usuarios normales no pueden leer; el campo visible es no almacenado.
- Distancias por carretera: OSRM si hay URL; si no, estimación haversine × 1,3, etiquetada como tal.
- Pago de prueba: la confirmación automática solo aplica al proveedor de pago de prueba.

### Fase 1: comandos, mapeo y checklist (2026-11-07)

**Comandos** (desde la raíz del repositorio; en PowerShell, `.env` se carga con el bloque de `tests/README.md`):

| Qué | Comando |
|---|---|
| Levantar todo desde cero | `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1` |
| Sembrar datos de prueba (idempotente) | `python seeds/seed.py` |
| Simular posiciones GPS (OsmAnd) | `python seeds/simular.py` |
| Pruebas sin Docker | `python -m unittest tests.estatico.test_sin_datos_quemados seeds.tests.test_simular seeds.tests.test_schema -v` |
| E2E contra el stack vivo | `python -m unittest tests.e2e.test_flujo -v` (con `E2E_REINICIO=1` también reinicia Traccar y Odoo) |
| Odoo de `logistica_traccar` | ver `tests/README.md` |

**Variables de Fase 1 en `.env`** (los valores no se versionan): `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`, `TRACCAR_URL`, `TRACCAR_INTERNAL_URL` (cómo llega Odoo a Traccar dentro de Docker), `TRACCAR_ADMIN_EMAIL`, `TRACCAR_ADMIN_PASSWORD`, `INTEGRATION_TRACCAR_EMAIL`, `INTEGRATION_TRACCAR_PASSWORD`, `TRACCAR_OSMAND_URL` (obligatoria al simular) y `SIM_INTERVALO_S` (vacía = 0). Una variable ya definida en el entorno manda sobre `.env`.

**Mapeo Odoo ↔ Traccar:**

| Odoo | Traccar | Vínculo |
|---|---|---|
| `fleet.vehicle` | dispositivo | `fleet.vehicle.traccar_device_id` → `traccar.device` (`traccar_id`, `unique_id`) |
| `traccar.server` | servidor y usuario de integración (solo lectura) | `base_url` + `username`; la clave vive en `traccar.server.clave`, que los usuarios normales no leen |
| `logistica.traccar.posicion` | posición | `traccar_position_id`, único |
| `logistica.traccar.evento` | evento (`deviceOverspeed`, `geofenceEnter`, `geofenceExit`, `deviceOnline`, `deviceOffline`) | `traccar_event_id`, único; guarda `geofence_traccar_id` |
| `res.partner` «Bodega central» | geocerca «Bodega central» | solo por nombre: Odoo no tiene modelo de geocerca |

**Checklist de Fase 1** (cada casilla tiene su evidencia):

- [x] Un comando levanta un entorno sano desde cero: `setup.ps1` con código 0 en un proyecto limpio (Tarea 10).
- [x] El sembrado es idempotente: la segunda corrida no crea nada (`test_seed_idempotente`).
- [x] Las posiciones llegan a Odoo con su vehículo y sin duplicados (`test_posicion_en_odoo_vehiculo_correcto`).
- [x] Los eventos de exceso de velocidad y de entrada a geocerca llegan a Odoo (`test_evento_overspeed_y_geocerca_en_odoo`).
- [x] Reiniciar Traccar u Odoo no pierde datos (`test_reinicio_*`, con `E2E_REINICIO=1`).
- [x] El usuario de integración es de solo lectura y no administrador.
- [x] Sin datos de negocio ni credenciales en el código, salvo `scripts/verify_integration.py` (excepción conocida).
- [ ] Suite de Odoo de `logistica_traccar` (`--test-enable`): no se ha corrido en esta máquina.
- [ ] `scripts/setup.sh` en Linux: solo sintaxis revisada.
- [ ] Pendientes de seguridad de la lista de arriba (control de gestor en «Probar Conexión», cabeceras en errores, rotación de credenciales).

### Preparación para la Fase 2 (ETL / ML / BI), sin implementar

Puntos de enganche que deja la Fase 1: las tablas `logistica.traccar.posicion` y `logistica.traccar.evento` de Odoo, y la sincronización de `traccar.server` (puntos de entrada públicos: `cron_sincronizar` y `action_sincronizar_ahora`; el trabajo vive en métodos privados `_sincronizar_*`). Hoy el ETL de `services/etl` extrae de Traccar por su API, no de estas tablas.

---

## 🏛️ Arquitectura de la Solución (Etapa 1 + 2)

```
                       ┌────────────────────────────────────────────────────────┐
                       │                     DOCKER NETWORK                     │
                       │             (odoo-traccar-logistica_default)           │
                       │                                                        │
┌────────────────┐     │  ┌───────────────┐     API REST      ┌──────────────┐  │     ┌─────────────────┐
│ Cliente Web /  │────┼─▶│     Odoo      │◀────────────────▶│   Traccar    │◀─┼─────│ Traccar Client  │
│ Admin Logística│8069 │  │  (16.0 ERP)   │    (HTTP :8082)   │ (6.17 GPS)   │  │5055 │ (App Móvil GPS) │
└────────────────┘     │  └───────┬───────┘                   └──────┬───────┘  │     └─────────────────┘
                       │          │                                  │          │
                       │          │ odoo@db:5432/logistica_dev       │          │
                       │          │                                  │ traccar@db:5432/traccar
                       │          ▼                                  ▼          │
                       │  ┌──────────────────────────────────────────────────┐  │
                       │  │                  PostgreSQL 15                   │  │
                       │  │       (Bases separadas lógicamente:              │  │
                       │  │        - logistica_dev                           │  │
                       │  │        - traccar)                                │  │
                       │  └──────────────────────────────────────────────────┘  │
                       └────────────────────────────────────────────────────────┘
```

### Servicios en Docker Compose

1. **`db` (`postgres:15`)**:
   - Motor de base de datos relacional para Odoo y Traccar.
   - Separación lógica con usuarios y bases independientes:
     - `odoo` -> `logistica_dev`
     - `traccar` -> `traccar`
   - Puerto 5432 no expuesto al host público (máxima seguridad en desarrollo y producción).
   - Healthcheck nativo mediante `pg_isready`.
2. **`odoo` (`odoo:16.0`)**:
   - ERP Odoo 16 Community con módulos oficiales instalados: `contacts`, `fleet`, `sale_management`, `website`, `website_sale`.
   - Módulo personalizado `logistica_traccar` montado desde `./odoo/addons` en `/mnt/extra-addons`.
   - Puerto `8069` accesible en `127.0.0.1:8069`.
3. **`traccar` (`traccar/traccar:latest` v6.17.0)**:
   - Servidor GPS con esquema gestionado por Liquibase en PostgreSQL.
   - Puerto web y API REST en `127.0.0.1:8082`.
   - Puerto receptor GPS OsmAnd en `5055` (compatible con la app Traccar Client).

---

## 🚀 Requisitos Previos

- **Windows**: Docker Desktop 4.x+ con WSL2 activado.
- **Ubuntu**: Docker Engine 24.x+ y Docker Compose v2+.
- **Git**: Normalización de finales de línea configurada vía `.gitattributes` (integrada en el repositorio).

---

## 🛠️ Guía Rápida de Despliegue (1 Solo Comando)

### 1. Clonar el Repositorio

```bash
git clone https://github.com/sebas/odoo-traccar-logistica.git
cd odoo-traccar-logistica
```

### 2. Ejecutar el Asistente de Despliegue Automático

El proyecto incluye un script de inicialización completa que configura `.env`, levanta Docker, crea las bases de datos de Odoo y Traccar, instala los módulos en español y siembra los datos base:

**En Linux / Ubuntu / macOS:**
```bash
chmod +x ./scripts/setup.sh
./scripts/setup.sh
```

**En Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

> **Nota:** `docker compose up -d` por sí solo **no** crea la base `logistica_dev` ni instala los módulos de Odoo: hasta que eso se haga, Odoo responde HTTP 500. Usa el script, que lo hace todo en orden. Si prefieres los pasos a mano, son los del script `scripts/setup.ps1`: `.env` con contraseñas reales → `docker compose up -d --wait` → `createdb logistica_dev` → instalar los módulos con `odoo -i` → reiniciar Odoo → `python seeds/seed.py`.

---

## 🌐 Accesos a las Plataformas

### 📌 ¿Cómo ingresar a Odoo 16?

> Al tener instalado el módulo de **eCommerce**, si navegas a `http://localhost:8069/` verás directamente la tienda pública. Para entrar al panel de administración del ERP debes usar la URL de login.

| Módulo / Interfaz | URL | Credenciales de Acceso | Descripción |
|---|---|---|---|
| **Odoo - Login Administrativo** | [http://localhost:8069/web/login](http://localhost:8069/web/login) | **Base de Datos:** `logistica_dev`<br>**Email:** `admin`<br>**Contraseña:** `admin` | Formulario para ingresar al backend del ERP. |
| **Odoo - Panel Backend ERP** | [http://localhost:8069/web](http://localhost:8069/web) | *(Requiere sesión iniciada)* | Acceso a Flota, Contactos, Ventas y Rastreo GPS. |
| **Odoo - Tienda eCommerce** | [http://localhost:8069/shop](http://localhost:8069/shop) | *Público (sin login)* | Catálogo de productos para compras sin registro obligatorio. |
| **Traccar - Consola Web y API** | [http://localhost:8082](http://localhost:8082) | **Usuario:** el correo de `TRACCAR_ADMIN_EMAIL`<br>**Contraseña:** la de `TRACCAR_ADMIN_PASSWORD`. En una instalación nueva, `seeds/seed.py` registra ese usuario como administrador inicial | Panel de monitoreo de dispositivos y gestión GPS. |
| **Receptor GPS OsmAnd** | `http://localhost:5055` | *Protocolo OsmAnd* | Puerto para envío de coordenadas desde Traccar Client. |

---

## 🧭 Navegación en Odoo y Uso del Módulo de Rastreo

Una vez autenticado en [http://localhost:8069/web/login](http://localhost:8069/web/login):

1. **Acceder a Flota**: En el menú principal de aplicaciones (icono de 9 puntos arriba a la izquierda), selecciona **Flota** (Fleet).
2. **Servidores Traccar**: En la barra superior de Flota, abre el menú **Rastreo Traccar > Servidores Traccar**:
   - Verás el servidor configurado (`http://traccar:8082`).
   - Puedes usar el botón **"Probar Conexión"** para verificar la comunicación en tiempo real.
   - El botón **"Sincronizar Dispositivos"** consulta la API de Traccar e importa automáticamente los dispositivos GPS registrados.
   - El botón **"Sincronizar ahora"** (solo gestores de flota) trae posiciones y eventos. Lo mismo hace el cron cada minuto, con el usuario del sistema.
3. **Dispositivos GPS**: En **Rastreo Traccar > Dispositivos GPS** se listan los identificadores IMEI / Client ID con su estado (`online` / `offline`) y última telemetría.
4. **Vehículos con GPS**: En **Flota > Vehículos**:
   - Abre cualquier vehículo (ej. `LOG-001`).
   - Revisa la pestaña **"Rastreo GPS Traccar"** para ver el dispositivo asociado, coordenadas (latitud/longitud) y velocidad.
   - Presiona el botón de cabecera **"Actualizar GPS Traccar"** para refrescar la última ubicación registrada.

---

## 🧩 Módulo Personalizado: `logistica_traccar`

Ubicado en `odoo/addons/logistica_traccar/`, permite la integración nativa entre Odoo y Traccar sin alterar tablas internas de ninguno de los sistemas:

### Características Implementadas

- **Gestión de Servidores Traccar (`traccar.server`)**:
  - Configuración de URL base (`http://traccar:8082`) y credenciales (Basic Auth o Bearer Token).
  - Botón **"Probar Conexión"**: Realiza test HTTP con diagnóstico de errores.
  - Botón **"Sincronizar Dispositivos"**: Consulta `/api/devices` e importa los dispositivos GPS a Odoo.
- **Dispositivos GPS Traccar (`traccar.device`)**:
  - Almacena ID interno, Identificador Único (IMEI/Client ID), estado en línea y telemetría.
  - Botón **"Actualizar Posición GPS"**: Consulta `/api/positions` en tiempo real.
- **Extensión de Flota (`fleet.vehicle`)**:
  - Pestaña **"Rastreo GPS Traccar"** en el formulario del vehículo.
  - Vinculación directa `Vehículo Odoo` ↔ `Dispositivo GPS Traccar`.
  - Botón **"Actualizar GPS Traccar"** para traer la última posición y velocidad del vehículo.

### Verificación Automatizada de la Integración

Para validar la comunicación interna Odoo ↔ Traccar en un solo comando:

**En Linux / macOS:**
```bash
cat scripts/verify_integration.py | docker compose exec -T odoo python3
```

**En Windows PowerShell:**
```powershell
Get-Content scripts/verify_integration.py -Raw | docker compose exec -T odoo python3
```

---

## 📱 Vinculación con Traccar Client (Teléfono Móvil)

1. Instale la aplicación **Traccar Client** (Android / iOS).
2. En la configuración de la app:
   - **URL del Servidor**: `http://<IP_DE_TU_PC>:5055`
   - **Identificador del Dispositivo**: El valor `uniqueId` asignado en Traccar (ej. `GPS-CAMION-01`).
3. Active el servicio en la app móvil.
4. En Odoo, ingrese a **Flota > Rastreo Traccar > Dispositivos GPS** y presione **Actualizar Posición GPS**.

---

## 💾 Scripts de Mantenimiento y DevOps

| Tarea | Script Linux/Ubuntu | Script Windows PowerShell |
|---|---|---|
| **Respaldar bases y filestore** | `./scripts/backup.sh` | `.\scripts\backup.ps1` |
| **Restaurar respaldo** | `./scripts/restore.sh <odoo.dump> <traccar.dump> [filestore.tar.gz]` | Ver comandos en `scripts/restore.sh` |
| **Actualizar módulos Odoo** | `./scripts/update_modules.sh logistica_traccar logistica_dev` | `docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_traccar --stop-after-init` |
| **Poblar datos de prueba (Seeds)** | `python3 seeds/seed.py` (en el host; `scripts/setup.sh` carga `.env` antes) | `python seeds/seed.py` (en el host; `scripts/setup.ps1` carga `.env` antes) |
| **Simular posiciones OsmAnd** | `python3 seeds/simular.py` (exige `TRACCAR_OSMAND_URL` en el entorno) | `python seeds/simular.py` (exige `TRACCAR_OSMAND_URL` en el entorno) |
