# Sistema Inteligente de Rastreo y Analítica de Rutas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar de forma funcional todo lo descrito en `docs/flujo_funcional_odoo_traccar.md`: eCommerce público con checkout geográfico, despacho con optimización, vista móvil del conductor, monitoreo GPS, ETL, Data Warehouse, BI y modelo predictivo de destinos.

**Architecture:** Odoo 16 es el sistema administrativo (pedidos, flota, entregas, rutas y portal del conductor). Traccar 6.x es la fuente GPS; Odoo lo consulta solo desde el backend. Tres servicios Python en `services/` (routing, ml, etl+bi) se comunican por HTTP con Odoo o leen el DWH. El DWH es un esquema PostgreSQL separado (`logistica_dwh`) en el mismo servidor `db`.

**Tech Stack:** Odoo 16.0 (`odoo:16.0`), Traccar (`traccar/traccar:latest`), PostgreSQL 15, FastAPI + uvicorn, OR-Tools (solver de rutas), scikit-learn, psycopg2, Streamlit (BI), pytest, Leaflet con tiles de OpenStreetMap (vistas Odoo y checkout). Los servicios corren como contenedores en `compose.yaml`.

**Spec:** `docs/flujo_funcional_odoo_traccar.md` (las referencias «§» apuntan a sus secciones).

## Decisiones tomadas por el equipo de implementación

La especificación deja abiertas las preguntas de su §14 y algunos valores. Estas son las decisiones tomadas; cada una es fácil de cambiar.

| # | Decisión | Motivo |
|---|---|---|
| D1 | El DWH usa **PostgreSQL 15** (base `logistica_dwh`), no SQL Server. | SQL Server aparece solo en el resumen (§15). Evita un contenedor adicional pesado. |
| D2 | Distancias por carretera: **OSRM** si `ROUTING_OSRM_URL` está definido; si no, estimación haversine × 1,3 a 30 km/h, marcada como `estimado_haversine` en cada respuesta. | No hay mapa OSM garantizado en el entorno. Ninguna respuesta presenta una estimación como ruta real. |
| D3 | Capacidad en **bultos**: 1 entrega = 1 bulto; `logistica_capacidad` del vehículo, por defecto `10`. | §14.3 pendiente; es el criterio más simple y verificable. |
| D4 | Preparación: botón manual **«Marcar preparado»** (simulación explícita). | §14.1 pendiente; no hay inventario en la prueba. |
| D5 | Cobro de prueba: pedido confirmado automáticamente al completar el checkout con el método de pago de prueba (`payment_custom`), sin cobro real. | §14.2 pendiente; el requisito de §3.1 es confirmar sin aprobación manual. |
| D6 | Radio de llegada **50 m**; GPS desactualizado tras **300 s**. Ambos configurables en `logistica.configuracion`. | Valores no fijados por la especificación. |
| D7 | Entrega fallida → `pendiente_reprogramacion`; el administrador decide reprogramar (vuelve a `preparado`) o `devuelto_bodega`. | §14.6 pendiente; §8.2 lo permite. |
| D8 | Seguimiento público: solo estado simplificado; **sin** coordenadas del vehículo. | §14.5 pendiente; minimiza datos (§12). |
| D9 | El histórico de demostración se marca `procedencia = SIMULADO` (§10.4). Los datos GPS de prueba se envían a Traccar por el protocolo OsmAnd (puerto 5055), como lo haría la app Traccar Client. | Separa datos reales de simulados y ejercita el flujo GPS real sin teléfono. |
| D10 | Zonas: centroides **aproximados** de los sectores de Ambato, editables en `logistica.zona`. | La especificación no da coordenadas; se marcan como aproximados. |
| D11 | **No se hacen commits.** Los pasos de commit de la plantilla se sustituyen por verificación. | El usuario pidió implementación, no commits. |

## Global Constraints

- Odoo 16.0 (`odoo:16.0`); módulos en `odoo/addons/`; etiquetas y mensajes de usuario en español.
- PostgreSQL 15. Esquema DWH `dwh` en la base `logistica_dwh`; base de Odoo `logistica_dev`.
- Traccar: la API se consulta solo desde el backend. Credenciales nunca al navegador (§12). Puertos de servicios solo en `127.0.0.1`.
- Estados de **entrega** (§8.2), valores exactos: `pendiente_preparacion`, `en_preparacion`, `preparado`, `asignado`, `en_recorrido`, `entregado`, `no_entregado`, `pendiente_reprogramacion`, `devuelto_bodega`.
- Estados de **ruta** (§8.3), valores exactos: `borrador`, `planificada`, `carga_confirmada`, `en_recorrido`, `cerrada`, `cancelada`, `interrumpida`.
- Motivos de no entrega (§3.3), claves y etiquetas exactas: `absent` «Cliente ausente», `wrong_address` «Dirección incorrecta», `refused` «Cliente rechaza», `access` «Acceso impedido», `damaged` «Problema con el producto», `other` «Otro».
- Una llegada GPS **nunca** cambia una entrega a `entregado` (§1.1 regla 9, §6.4).
- Una entrega por pedido en v1: `sale_order_id` único en `logistica.entrega`.
- Tablas DWH con nombres de §10.2: `DIM_VEHICULO`, `DIM_CONDUCTOR`, `DIM_TIEMPO`, `DIM_ZONA`, `DIM_CLIENTE`, `FACT_RECORRIDOS`, `FACT_ENTREGAS` (en PostgreSQL: `dwh.dim_vehiculo`, etc.).
- ML: reportar accuracy, precision, recall, F1, matriz de confusión y comparación con predictor base (§10.4).
- Los pedidos no se asignan automáticamente desde la IA (§5 M7).
- Sin commits (D11).

## Review Focus

Cinco entradas o fallos que la especificación implica y que más probablemente afectarían a una persona que usa el software. Cada una tiene su prueba en la tarea indicada.

1. **GPS sin señal o Traccar caído** → la interfaz muestra «Última ubicación conocida» con su antigüedad; no se simula movimiento y no se pierden pedidos. *Prueba: Tarea 9 `test_traccar_caido_no_rompe`, `test_posicion_desactualizada_marca_stale`.*
2. **Doble clic o reintento** en «Entregado», «Confirmar carga» o «Iniciar recorrido» → un solo evento; la segunda llamada se rechaza sin duplicar registros. *Prueba: Tareas 6, 8 y 10 `test_doble_entregado_un_evento`, `test_doble_inicio_rechazado`, `test_entregado_idempotente`.*
3. **Pedido nuevo creado después de iniciar una ruta** → no entra en esa ruta; queda para la siguiente. *Prueba: Tarea 8 `test_nuevo_pedido_no_entra_a_ruta_iniciada`.*
4. **Coordenadas vacías, `0,0`, texto, latitud fuera de rango o fuera de cobertura** en el checkout → el pedido no se confirma en silencio; se muestra el error. *Prueba: Tarea 7 `test_checkout_rechaza_coords_invalidas`.*
5. **Conductor que pide una ruta ajena o un token adivinado** → 403/404 sin revelar datos. *Prueba: Tarea 10 `test_conductor_solo_ve_sus_rutas`; Tarea 7 `test_seguimiento_token_invalido_404`.*

---

## Contracts shared between tasks

### C1. Servicio de rutas (`routing`, puerto interno 8000; host `127.0.0.1:8001`)

- `GET /health` → `{"status": "ok"}`
- `POST /matrix` — body `{"points": [{"lat": float, "lon": float}]}` → `{"distance_m": [[int]], "duration_s": [[int]], "source": "osrm" | "estimado_haversine"}`
- `GET /route?origin_lat&origin_lon&dest_lat&dest_lon` → `{"geometry": [[lat, lon], ...], "distance_km": float, "duration_min": float, "source": str}`
- `POST /optimize` — body:
  ```json
  {"depot": {"lat": -1.24, "lon": -78.61},
   "stops": [{"id": 101, "lat": -1.25, "lon": -78.62, "demand": 1}],
   "vehicles": [{"id": 7, "capacity": 10}],
   "time_limit_s": 5}
  ```
  → `{"routes": [{"vehicle_id": 7, "stops": [{"id": 101, "sequence": 1}], "distance_km": float, "duration_min": float, "load": int}], "unassigned": [{"id": int, "reason": "sin_capacidad" | "sin_ruta"}], "source": str, "optimization_version": str}`
  - `sequence` empieza en 1. El depósito no aparece en `stops`.
  - `422` si `vehicles` está vacío, una coordenada está fuera de rango o un `demand` es negativo.
  - Los vehículos sin paradas no aparecen en `routes`.

### C2. Servicio ML (`ml`, puerto interno 8000; host `127.0.0.1:8002`)

- `GET /health` → `{"status": "ok", "model_loaded": bool}`
- `POST /predict` — body `{"vehicle_code": str, "reference_datetime": "ISO-8601", "origin_zone": str}` → `{"predicted_zone": str, "probabilities": {zona: float}, "alternatives": [{"zone": str, "probability": float}], "model_version": str}`
  - `alternatives` son las 3 siguientes más probables, sin incluir la predicha.
  - `503` si no hay modelo entrenado; `422` si `origin_zone` no es un código de zona válido.
- `GET /metrics` → JSON con `accuracy`, `precision_macro`, `recall_macro`, `f1_macro`, `confusion_matrix`, `labels`, `baseline_accuracy`, `baseline_f1`, `n_train`, `n_test`, `split_date`, `procedencia_counts`, `model_version`.
- Entrenamiento: `python -m mlsvc.train --source csv:<ruta> | dwh`.

### C3. Conjunto de viajes para entrenamiento

Vista `dwh.v_viajes_entrenamiento` (o CSV con las mismas columnas): `vehiculo_codigo` (texto), `fecha_hora` (ISO-8601 UTC), `zona_origen`, `zona_destino` (códigos de zona), `procedencia` (`REAL` | `SIMULADO`).

Códigos de zona (fijados en `logistica_base`, §5 M1): `centro`, `ficoa`, `huachi`, `izamba`, `atocha`, `ingahurco`, `otra`.

### C4. Parámetros de configuración (`ir.config_parameter`, Odoo)

| Clave | Valor por defecto |
|---|---|
| `logistica.routing_url` | `http://routing:8000` |
| `logistica.ml_url` | `http://ml:8000` |
| `logistica.traccar_poll_minutes` | `1` |

### C5. Esquema DWH (Tarea 3 lo crea; Tarea 4 lo consume)

Base `logistica_dwh`, esquema `dwh`, claves sustitutas `sk`:

- `dim_vehiculo(sk, vehiculo_id_odoo, placa, traccar_device_id, procedencia)`
- `dim_conductor(sk, conductor_id_odoo, nombre)`
- `dim_tiempo(sk, fecha, anio, mes, dia, dia_semana, hora)` — `sk = YYYYMMDDHH` (UTC)
- `dim_zona(sk, codigo, nombre, latitud, longitud)`
- `dim_cliente(sk, cliente_id_odoo, nombre, zona_sk)`
- `fact_recorridos(sk, vehiculo_sk, conductor_sk, tiempo_inicio_sk, zona_origen_sk, zona_destino_sk, inicio_utc, fin_utc, distancia_km, duracion_min, num_paradas, fuente_id, procedencia, lote_id)` — único `(fuente_id, procedencia)`
- `fact_entregas(sk, cliente_sk, vehiculo_sk, conductor_sk, tiempo_sk, zona_sk, entrega_id_odoo, ruta_id_odoo, recorrido_sk NULL, resultado, motivo, planificado_utc, completado_utc, procedencia, lote_id)` — `resultado` ∈ {`entregado`, `no_entregado`, `pendiente`}; `recorrido_sk` solo si hay coincidencia verificable (§10.2)
- `fact_posicion_gps(sk, vehiculo_sk, tiempo_sk, gps_time_utc, latitud, longitud, velocidad_kmh, fuente_id, lote_id)`
- `rechazados(id, entidad, fuente_id, motivo, payload jsonb, lote_id)`
- `stg.*` (crudo, JSONB), `etl_control.watermark`, `etl_control.lote`
- vista `dwh.v_viajes_entrenamiento` (C3)

### C6. Contratos Odoo que otras tareas usan

Cada modelo indica la tarea que lo produce.

- **`sale.order`** (T6): `_logistica_destino_valido() -> bool`; `action_confirm()` extendido: si el pedido es web (`website_id`) sin destino válido, lanza `UserError`; al confirmar crea `logistica.entrega` (estado `en_preparacion`).
- **`logistica.bodega`** (T5): `name, address, latitude, longitude, active`; restricción: una sola activa. Método `get_bodega_activa() -> record`.
- **`logistica.configuracion`** (T5): singleton; `arrival_radius_m` (50), `gps_stale_after_seconds` (300), `dispatch_cutoff` (Float, hora 0–24), `route_recalculation_policy` (`solo_pendientes`). Método `get_config() -> record`.
- **`logistica.zona`** (T5): `code` (Selection de C3), `name`, `latitude`, `longitude`, `active`. Método `centroide(code) -> (lat, lon)`.
- **`fleet.vehicle`** (T5): `logistica_capacidad` (Integer, 10); `traccar_device_id` único (restricción SQL); `driver_id` (de Fleet) como conductor.
- **`logistica.entrega`** (T6): `name`, `sale_order_id` (único), `partner_id`, `latitude`, `longitude`, `destination_address`, `delivery_reference`, `recipient_name`, `phone`, `state` (valores de C6-estados), `tracking_token` (Char, único), `tracking_token_expires` (Datetime), `tracking_token_revoked` (Boolean), `route_stop_ids` (One2many a `logistica.ruta.parada`), `route_id` (computed). Métodos: `action_marcar_preparado()`, `action_marcar_en_recorrido()` (uso del despacho), `action_marcar_llegada(gps=None)`, `action_marcar_entregado()`, `action_marcar_no_entregado(motivo, notas=None)`, `action_reprogramar()`, `action_devolver_bodega()`, `_registrar_evento(tipo, **vals) -> logistica.entrega.evento`, `_gps_snapshot() -> dict`, `get_by_tracking_token(token) -> record | empty`.
- **`logistica.entrega.evento`** (T6): append-only; `entrega_id`, `event_type` (`creado`, `preparado`, `asignado`, `carga_confirmada`, `inicio_recorrido`, `posible_llegada`, `llegada_registrada`, `entregado`, `no_entregado`, `reprogramado`, `devuelto_bodega`, `gps_no_disponible`), `event_time`, `user_id`, `route_id`, `gps_latitude`, `gps_longitude`, `gps_time`, `gps_age_seconds`, `gps_available`, `failure_reason`, `notes`. `write`/`unlink` lanzan `UserError`.
- **`logistica.ruta`** (T8): `name`, `date`, `bodega_id`, `vehicle_id`, `driver_id` (`res.partner`, `is_driver`), `state` (valores de C6-estados ruta), `planned_distance_km`, `planned_duration_min`, `optimization_version`, `confirmed_load_at`, `started_at`, `finished_at`, `interrupt_reason`, `stop_ids`. Métodos: `action_aprobar_plan()`, `action_confirmar_carga()`, `action_iniciar_recorrido()`, `action_cerrar()`, `action_cancelar(motivo=None)`, `action_interrumpir(motivo)`, `assert_driver(user)`.
- **`logistica.ruta.parada`** (T8): `route_id`, `sequence`, `entrega_id`, `state` (`pendiente`, `entregado`, `no_entregado`), `arrival_candidate_at`, `actual_arrival_at`, `completed_at`, `failed_reason`, `notes`. Métodos: `action_marcar_llegada()`, `action_marcar_entregado()`, `action_marcar_no_entregado(motivo, notas=None)`.
- **`logistica.planificador`** (TransientModel, T8): `action_proponer()` (llama C1 `/optimize`); crea rutas en `borrador`.
- **`logistica.traccar.posicion`** (T9): `device_id`, `vehicle_id`, `traccar_position_id` (único), `gps_time`, `latitude`, `longitude`, `speed_kmh`, `received_at`, `is_stale`.
- **`traccar.device`** (T9): `_registrar_posicion(payload: dict) -> logistica.traccar.posicion`, `is_stale`, `last_latitude`, `last_longitude`, `last_speed`, `last_position_time`.
- **`traccar.server`** (T9): `get_route_report(device_id, from_dt, to_dt)`, `get_trips(device_id, from_dt, to_dt)`, `get_stops(device_id, from_dt, to_dt)`, `cron_poll_positions()`.
- **`logistica.prediccion.consulta`** (T11): `vehicle_id`, `reference_datetime`, `origin_zone`, `predicted_zone`, `class_probabilities` (Text JSON), `alternatives` (Text JSON), `model_version`, `route_geometry` (Text JSON), `user_id`, `created_at`.

---

## Phase A — Servicios Python (paralelo entre sí; no tocan la base de Odoo)

### Task 1: Servicio de rutas y optimización (`services/routing`)

Implementa §9 y §10.4 (mapa). Contrato C1.

**Files:**
- Create: `services/routing/Dockerfile`, `services/routing/requirements.txt`, `services/routing/requirements-dev.txt`
- Create: `services/routing/app/main.py`, `services/routing/app/distance.py` (proveedor OSRM + haversine), `services/routing/app/optimizer.py` (OR-Tools)
- Create: `services/routing/tests/test_api.py`, `services/routing/tests/test_optimizer.py`
- Modify: `compose.yaml` (servicio `routing`, healthcheck `GET /health`, red por defecto, `127.0.0.1:8001:8000`, variable `ROUTING_OSRM_URL` opcional, `ROUTING_TIME_LIMIT_S=5`)

**Interfaces:**
- Consumes: nada (servicio independiente).
- Produces: C1 (`/matrix`, `/route`, `/optimize`, `/health`).

- [ ] **Step 1: Escribir pruebas que fallan** (`tests/test_api.py`, `tests/test_optimizer.py`, con `TestClient` de FastAPI)
  - `test_matrix_estimado_sin_osrm`: dos puntos → `distance_m[0][1]` ≈ haversine × 1,3 (±1 %), `source == "estimado_haversine"`.
  - `test_optimize_respeta_capacidad`: 6 paradas `demand=1`, 2 vehículos `capacity=3` → todas asignadas, `load ≤ 3` por ruta.
  - `test_optimize_sobre_capacidad`: 7 paradas, capacidad total 6 → exactamente 1 en `unassigned` con `reason == "sin_capacidad"`.
  - `test_optimize_sin_vehiculos_422`: `vehicles: []` → `422`.
  - `test_secuencia_base_1_sin_deposito`: las secuencias empiezan en 1 y el id del depósito no aparece.
  - `test_coordenadas_invalidas_422`: `lat=95` → `422`.
  - `test_route_fallback_linea_recta`: `GET /route` → `geometry` con 2 puntos y `source == "estimado_haversine"`.
  - `test_osrm_caido_cae_a_estimacion`: con `ROUTING_OSRM_URL` apuntando a un puerto cerrado, la respuesta es `estimado_haversine` (no error 500).

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Run: `docker compose run --rm --entrypoint pytest routing -q` (tras crear el Dockerfile) o `cd services/routing && python -m pytest -q`.
  Expected: FAIL por import/módulo inexistente.

- [ ] **Step 3: Implementar**
  - `distance.py`: `class DistanceProvider` con `matrix(points) -> (dist_m, dur_s, source)` y `route(a, b) -> (geometry, km, min, source)`. `OsrmProvider` usa `/table/v1/driving/` y `/route/v1/driving/`; si falla (timeout/conexión), `HaversineProvider` (factor 1,3; 30 km/h) con `source="estimado_haversine"`.
  - `optimizer.py`: OR-Tools `RoutingModel` de un depósito; dimensión de capacidad con `demand`; penalización por parada no asignada (`AddDisjunction`) con etiqueta de motivo: `sin_capacidad` si la demanda total supera la capacidad, `sin_ruta` en otro caso; objetivo: distancia; `time_limit_s` desde el cuerpo (máximo 30). Devuelve la secuencia 1-based.
  - `main.py`: rutas de C1; validación con Pydantic; `GET /health`.
  - `Dockerfile`: `python:3.12-slim`, `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `8 passed`.

- [ ] **Step 5: Verificar en contenedor**
  Run: `docker compose up -d --build routing && curl -s http://127.0.0.1:8001/health`
  Expected: `{"status":"ok"}`.

---

### Task 2: Servicio de predicción de destinos (`services/ml`)

Implementa §10.4 y contrato C2 y C3. Entrena con el conjunto de viajes (C3); la fuente por defecto es un CSV generado en `services/ml/data/` hasta que el DWH tenga datos.

**Files:**
- Create: `services/ml/Dockerfile`, `services/ml/requirements.txt`, `services/ml/requirements-dev.txt`
- Create: `services/ml/mlsvc/__init__.py`, `services/ml/mlsvc/features.py`, `services/ml/mlsvc/train.py` (CLI `python -m mlsvc.train`), `services/ml/mlsvc/serve.py` (FastAPI)
- Create: `services/ml/mlsvc/simulate.py` (genera viajes con patrón conocido, procedencia `SIMULADO`)
- Create: `services/ml/tests/test_train.py`, `services/ml/tests/test_api.py`
- Modify: `compose.yaml` (servicio `ml`, `127.0.0.1:8002:8000`, volumen `./services/ml/models:/app/models`)

**Interfaces:**
- Consumes: C3 (CSV o `dwh.v_viajes_entrenamiento`).
- Produces: C2 (`/predict`, `/metrics`, `/health`); artefactos `models/model.joblib` y `models/metrics.json`.

- [ ] **Step 1: Escribir pruebas que fallan**
  - `test_split_temporal`: el último `fecha_hora` de entrenamiento es anterior al primero de prueba (no aleatorio).
  - `test_metricas_completas`: `metrics.json` contiene todas las claves de C2; `confusion_matrix` es cuadrada con tamaño `len(labels)`.
  - `test_supera_baseline_en_patron`: con datos sintéticos donde la hora determina la zona, `accuracy > baseline_accuracy`.
  - `test_predict_probabilidades`: las probabilidades suman 1 ± 1e-6, `predicted_zone` es el argmax, `alternatives` tiene 3 elementos y no incluye la predicha.
  - `test_predict_sin_modelo_503`: sin `model.joblib`, `503`.
  - `test_zona_invalida_422`: `origin_zone="marte"` → `422`.
  - `test_procedencia_reportada`: `procedencia_counts` distingue `REAL` y `SIMULADO`.

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL por módulo inexistente.

- [ ] **Step 3: Implementar**
  - `features.py`: codificación de `vehiculo_codigo` y `zona_origen` (one-hot), `dia_semana` y `hora` (seno/coseno o one-hot). Objetivo: `zona_destino`.
  - `train.py`: orden cronológico, corte 80/20 por tiempo; `RandomForestClassifier` (semilla fija); `DummyClassifier(strategy="most_frequent")` como base; métricas con `sklearn.metrics` (macro); guarda `model.joblib` y `metrics.json` con `model_version` = fecha UTC + hash del conjunto.
  - `simulate.py`: genera viajes por vehículo, día y hora con probabilidades por zona (p. ej. la hora de la mañana favorece `centro`); etiqueta `procedencia="SIMULADO"`.
  - `serve.py`: carga el modelo al arrancar si existe; rutas de C2.

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Run: `docker compose run --rm --entrypoint pytest ml -q`. Expected: `7 passed`.

- [ ] **Step 5: Entrenar y servir**
  Run: `docker compose run --rm ml python -m mlsvc.train --source simulate && docker compose up -d --build ml && curl -s http://127.0.0.1:8002/metrics`
  Expected: JSON con `accuracy` > `baseline_accuracy`.

---

### Task 3: ETL, staging y Data Warehouse (`services/etl`)

Implementa §10.1, §10.2, §6.3 (consultas de Traccar), §6.5 y la regla de vinculación de §10.2. Contrato C5.

**Files:**
- Create: `services/etl/Dockerfile`, `services/etl/requirements.txt`, `services/etl/requirements-dev.txt`
- Create: `services/etl/etl/__main__.py` (CLI: `bootstrap`, `run --mode full|incremental`, `simulate`)
- Create: `services/etl/etl/config.py`, `services/etl/etl/odoo_extract.py` (XML-RPC), `services/etl/etl/traccar_extract.py` (HTTP Basic), `services/etl/etl/staging.py`, `services/etl/etl/quality.py`, `services/etl/etl/load.py`, `services/etl/etl/watermark.py`, `services/etl/etl/simulado.py`
- Create: `services/etl/sql/01_schema.sql` (C5 completo), `services/etl/sql/02_views.sql` (`v_viajes_entrenamiento`)
- Create: `services/etl/tests/fixtures/odoo_*.json`, `services/etl/tests/fixtures/traccar_*.json`, `services/etl/tests/test_quality.py`, `services/etl/tests/test_load.py`, `services/etl/tests/test_incremental.py`
- Modify: `compose.yaml` (servicio `etl` con `profiles: ["etl"]`; variables ODOO_*, TRACCAR_*, DWH_DSN; `depends_on: db`)
- Modify: `.env.example` (`DWH_DB_PASSWORD`, `ROUTING_OSRM_URL` opcional)

**Interfaces:**
- Consumes: Odoo (XML-RPC, modelos `res.partner`, `fleet.vehicle`, `sale.order`, `logistica.ruta`, `logistica.ruta.parada`, `logistica.entrega`, `logistica.entrega.evento`); Traccar (`/api/devices`, `/api/positions`, `/api/reports/route`, `/api/reports/trips`, `/api/reports/stops`).
- Produces: C5 (esquema y tablas), vista C3.

- [ ] **Step 1: Escribir pruebas que fallan** (con fixtures JSON; las de base de datos usan `DWH_DSN` de prueba)
  - `test_normaliza_velocidad_nudos`: 10 nudos → `18.52` km/h.
  - `test_rechaza_coordenadas_invalidas`: `lat=91` → fila en `rechazados` con `motivo="coordenadas_invalidas"`.
  - `test_rechaza_fechas_incoherentes`: `fin < inicio` → `rechazados` con `motivo="fechas_incoherentes"`.
  - `test_rechaza_velocidad_anomala`: `> 150 km/h` → `rechazados` con `motivo="velocidad_anomala"`.
  - `test_duplicados_por_fuente`: el mismo `fuente_id` dos veces → una fila.
  - `test_carga_incremental_idempotente`: ejecutar dos veces → mismos conteos y watermark avanzado.
  - `test_vinculo_solo_con_coincidencia`: entrega dentro de la ventana de un recorrido del mismo vehículo → `recorrido_sk` no nulo; vehículo distinto → `NULL`.
  - `test_simulado_marcado`: filas de `simulate` tienen `procedencia = 'SIMULADO'`.
  - `test_fechas_utc`: `planificado_utc` y `completado_utc` son UTC (se convierte el naive de Odoo).

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Run: `docker compose run --rm --entrypoint pytest etl -q`. Expected: FAIL.

- [ ] **Step 3: Implementar**
  - `bootstrap`: crea la base `logistica_dwh` si falta (conexión a `postgres`), aplica `sql/01_schema.sql` y `sql/02_views.sql`.
  - `odoo_extract.py`: `xmlrpc.client` contra `ODOO_URL` / `ODOO_DB` con `search_read` y filtro por `write_date` (watermark).
  - `traccar_extract.py`: Basic Auth; `/api/reports/route` por dispositivo y ventana de fechas; `/api/positions` para la última posición.
  - `staging.py`: inserta crudo en `stg.*` con `lote_id`, `extraido_utc`.
  - `quality.py`: reglas de §10.2 (duplicados, coordenadas, fechas, velocidad anómala, nulos obligatorios, unidades: nudos→km/h, metros→km). Las filas rechazadas van a `dwh.rechazados`.
  - `load.py`: upserts `ON CONFLICT` en dimensiones y hechos; `FACT_ENTREGAS.recorrido_sk` solo con coincidencia de vehículo + ventana temporal (regla §10.2).
  - `simulado.py`: genera viajes (mismo generador de Tarea 2) con `procedencia='SIMULADO'`.
  - `run --mode incremental` usa `etl_control.watermark`.

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `9 passed` (y las pruebas de base de datos pasan contra el contenedor `db`).

- [ ] **Step 5: Verificar contra los servicios reales**
  Run: `docker compose run --rm etl python -m etl bootstrap && docker compose run --rm etl python -m etl simulate --dias 30 && docker compose run --rm etl python -m etl run --mode full`
  Expected: `docker compose exec -T db psql -U odoo -d logistica_dwh -tAc "select count(*) from dwh.fact_recorridos where procedencia='SIMULADO'"` > 0.

---

### Task 4: Dashboard BI sobre el DWH (`services/bi`)

Implementa §10.3. Depende de Task 3 (C5).

**Files:**
- Create: `services/bi/Dockerfile`, `services/bi/requirements.txt`
- Create: `services/bi/app.py` (Streamlit), `services/bi/olap.py` (consultas), `services/bi/sql/olap_queries.sql` (con `GROUP BY ROLLUP`)
- Create: `services/bi/tests/test_olap.py`, `services/bi/tests/test_no_odoo.py`
- Modify: `compose.yaml` (servicio `bi`, `127.0.0.1:8501:8501`, usuario de solo lectura `dwh_ro`)

**Interfaces:**
- Consumes: C5 (`dwh.*`, `dwh.v_viajes_entrenamiento`).
- Produces: panel en `http://127.0.0.1:8501`.

- [ ] **Step 1: Escribir pruebas que fallan**
  - `test_no_odoo`: ningún archivo de `services/bi` importa `xmlrpc`, `odoo` o `requests` hacia Odoo (§10.3: el BI consulta solo el DWH).
  - `test_olap_ejecuta`: cada consulta de `olap_queries.sql` se ejecuta en el DWH con datos de Task 3 y devuelve filas; las consultas con `ROLLUP` incluyen una fila de total.
  - `test_filtro_procedencia`: el filtro `REAL` / `SIMULADO` restringe los resultados.
  - `test_indicadores`: aparecen distancia por vehículo, recorridos por día/hora, duración promedio, zonas visitadas, paradas, entregas por cliente, estado y cumplimiento (§10.3).

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [ ] **Step 3: Implementar**
  - `olap.py`: funciones que devuelven DataFrames; solo SQL contra `dwh`.
  - `app.py`: filtros de fecha y procedencia; secciones de indicadores; etiqueta visible «Datos SIMULADOS» cuando el filtro los incluye (§12, «indicar cuándo un resultado es simulado»).

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Run: `docker compose run --rm --entrypoint pytest bi -q`. Expected: `4 passed`.

- [ ] **Step 5: Verificar en contenedor**
  Run: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501/_stcore/health`. Expected: `200`.

---

## Phase B — Módulos de Odoo (en serie; todos comparten la base `logistica_dev`)

Ejecutar siempre así (pruebas de un módulo):

```
docker compose exec -T odoo odoo -d logistica_dev -u <modulo> --test-enable --stop-after-init --test-tags /<modulo> --log-level=test 2>&1 | grep -E "ERROR|FAIL|Ran |tests"
```

Expected: `0 failed, 0 error(s)`. Los módulos nuevos se instalan con `-i` en lugar de `-u`. Actualizar `depends` del manifest al crear cada módulo nuevo.

### Task 5: `logistica_base` — configuración, bodega, zonas y restricciones

Implementa §5 M1, §2 (bodega común, §1.1 regla 4) y §6.2 (vinculación única).

**Files:**
- Create: `odoo/addons/logistica_base/models/logistica_bodega.py`, `logistica_configuracion.py`, `logistica_zona.py`, `fleet_vehicle.py`
- Modify: `odoo/addons/logistica_base/models/__init__.py`, `odoo/addons/logistica_base/__manifest__.py`
- Create: `odoo/addons/logistica_base/data/logistica_zona_data.xml`, `odoo/addons/logistica_base/data/logistica_config_data.xml`, `odoo/addons/logistica_base/views/logistica_config_views.xml`
- Modify: `odoo/addons/logistica_base/models/sale_order.py` (quitar `delivery_status`; se reemplaza por `logistica.entrega` en Task 6)
- Modify: `odoo/addons/logistica_base/security/ir.model.access.csv` (acceso de lectura a `base.group_user`; escritura a `fleet.group_fleet_manager`)
- Create: `odoo/addons/logistica_base/tests/__init__.py`, `odoo/addons/logistica_base/tests/test_base.py`
- Modify: `odoo/addons/logistica_traccar/models/fleet_vehicle.py` (quitar la restricción que solo esté en `traccar`; la unicidad vive en `logistica_base`)

**Interfaces:**
- Consumes: nada.
- Produces: C6 (`logistica.bodega`, `logistica.configuracion`, `logistica.zona`, `fleet.vehicle.logistica_capacidad`, restricción de dispositivo único).

- [ ] **Step 1: Escribir pruebas que fallan** (`tests/test_base.py`, `TransactionCase`)
  - `test_bodega_unica_activa`: crear una segunda `logistica.bodega` activa → `ValidationError`.
  - `test_dispositivo_no_compartido`: dos `fleet.vehicle` con el mismo `traccar_device_id` → error de integridad (`IntegrityError`) o `ValidationError`.
  - `test_configuracion_por_defecto`: `arrival_radius_m == 50`, `gps_stale_after_seconds == 300`; `fleet.vehicle.logistica_capacidad == 10`.
  - `test_zonas_con_centroide`: las 7 zonas de C3 existen con latitud y longitud distintas de 0 (`centroide('centro')`).
  - `test_capacidad_no_negativa`: `logistica_capacidad = -1` → `ValidationError`.

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL (modelos inexistentes).

- [ ] **Step 3: Implementar**
  - `logistica.bodega`: campos de C6; `_check_bodega_unica` con `@api.constrains('active')`; `get_bodega_activa()`.
  - `logistica.configuracion`: singleton (`create` si no existe; `get_config()`); D6.
  - `logistica.zona`: datos de Ambato (D10) en XML de datos; `_sql_constraints` por `code`.
  - `fleet.vehicle`: `logistica_capacidad`, `_sql_constraints` con `unique(traccar_device_id)`; `_check_capacidad`.
  - `sale.order`: quitar `delivery_status` y sus vistas (`sale_order_views.xml`, `logistica_despacho`); ajustar el dominio de `logistica.ruta.parada` en Task 8.
  - Vistas: formulario de configuración y de bodega en menú «Logística».

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Run: el comando de Phase B con `--test-tags /logistica_base`. Expected: `0 failed, 0 error(s)`, 5 pruebas.

- [ ] **Step 5: Verificar actualización en la base existente**
  Run: `docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_base --stop-after-init`. Expected: sin errores en el log.

---

### Task 6: `logistica_entregas` — entrega logística, estados, eventos y seguimiento

Implementa §5 M3, §8.2, §8.4, §4.1 (puntos 5 y 6), §3.3 (auditoría). Nuevo módulo.

**Files:**
- Create: `odoo/addons/logistica_entregas/__init__.py`, `__manifest__.py` (depends: `base`, `sale_management`, `logistica_base`)
- Create: `odoo/addons/logistica_entregas/models/logistica_entrega.py`, `logistica_entrega_evento.py`, `sale_order.py`
- Create: `odoo/addons/logistica_entregas/security/ir.model.access.csv`, `security/security.xml` (grupo `logistica.group_conductor` se define en Task 10)
- Create: `odoo/addons/logistica_entregas/views/logistica_entrega_views.xml`, `views/menu_views.xml`
- Create: `odoo/addons/logistica_entregas/tests/test_entregas.py`

**Interfaces:**
- Consumes: C6 de Task 5 (`logistica.zona`, `logistica.configuracion.get_config`).
- Produces: C6 (`logistica.entrega` y `logistica.entrega.evento`, `sale.order` hook).

- [ ] **Step 1: Escribir pruebas que fallan**
  - `test_entrega_al_confirmar_con_destino`: confirmar pedido con coordenadas → una `logistica.entrega` en `en_preparacion`.
  - `test_pedido_web_sin_destino_no_confirma`: pedido con `website_id` y sin coordenadas → `UserError` al confirmar.
  - `test_transicion_invalida`: `action_marcar_entregado` desde `pendiente_preparacion` → `UserError`.
  - `test_evento_append_only`: `write` y `unlink` sobre `logistica.entrega.evento` → `UserError`.
  - `test_doble_entregado_un_evento`: llamar dos veces `action_marcar_entregado` → segunda `UserError` («ya registrado»), un solo evento `entregado`.
  - `test_no_entregado_requiere_motivo`: sin motivo → `ValidationError`; con `absent` → estado `no_entregado`.
  - `test_llegada_gps_no_entrega`: `action_marcar_llegada` con GPS dentro de 50 m → estado sin cambio; evento `posible_llegada`; nunca `entregado`.
  - `test_token_seguro_y_expira`: `tracking_token` tiene al menos 43 caracteres (`secrets.token_urlsafe(32)`); `get_by_tracking_token` devuelve vacío para token vencido o revocado.
  - `test_reprogramar_o_devolver`: `no_entregado` → `action_reprogramar` → `preparado`; `action_devolver_bodega` → `devuelto_bodega`.

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [ ] **Step 3: Implementar**
  - `logistica.entrega`: campos de C6; `_sql_constraints` `unique(sale_order_id)`; máquina de estados como un diccionario de transiciones permitidas, validado en un único método `_transicionar(desde, hacia)`.
  - `_gps_snapshot()`: lee la última posición del vehículo asignado (`traccar.device`, Task 9) si el módulo está instalado; si no hay posición, `gps_available=False` y evento `gps_no_disponible`.
  - `action_marcar_llegada(gps=None)`: registra `posible_llegada`; no cambia estado a `entregado`.
  - `action_marcar_entregado()`: transición desde `en_recorrido`; evento `entregado` con conductor, hora y GPS complementario (§3.3).
  - `sale.order.action_confirm`: si `website_id` y sin destino válido → `UserError`; crea la entrega y la pasa a `en_preparacion`.
  - `tracking_token`: generado al crear la entrega; `tracking_token_expires` = fecha de creación + 90 días.
  - `logistica.entrega.evento`: `write`/`unlink` → `UserError`.

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Run: instalar con `-i logistica_entregas --test-enable --test-tags /logistica_entregas`. Expected: `0 failed, 0 error(s)`, 9 pruebas.

- [ ] **Step 5: Verificar actualización**
  Run: `docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -i logistica_entregas --stop-after-init`. Expected: sin errores.

---

### Task 7: `logistica_checkout` — checkout con mapa, confirmación automática y seguimiento público

Implementa §3.1, §4.1, §5 M2, §12 (token), D5, D8. Nuevo módulo que extiende `website_sale`.

**Files:**
- Create: `odoo/addons/logistica_checkout/__init__.py`, `__manifest__.py` (depends: `website_sale`, `payment_custom`, `logistica_entregas`)
- Create: `odoo/addons/logistica_checkout/controllers/main.py` (sobrescribe `/shop/address`; ruta `/logistica/seguimiento/<token>`; límite de peticiones en memoria por IP)
- Create: `odoo/addons/logistica_checkout/models/sale_order.py`, `models/res_config.py`
- Create: `odoo/addons/logistica_checkout/views/checkout_templates.xml` (hereda `website_sale.address`; mapa Leaflet con pin y campos ocultos `delivery_latitude`, `delivery_longitude`), `views/tracking_templates.xml`, `views/confirmation_templates.xml` (enlace de seguimiento)
- Create: `odoo/addons/logistica_checkout/static/src/js/map_picker.js`
- Create: `odoo/addons/logistica_checkout/tests/test_checkout.py` (`HttpCase`)

**Interfaces:**
- Consumes: C6 de Task 6 (`logistica.entrega`, `get_by_tracking_token`, `sale.order` hook); `logistica.zona`, `logistica.configuracion` (Task 5).
- Produces: rutas `GET /shop/address`, `POST /shop/address` (extendidas); `GET /logistica/seguimiento/<token>`.

- [ ] **Step 1: Escribir pruebas que fallan**
  - `test_checkout_guarda_pin_en_pedido`: `POST /shop/address` con `delivery_latitude`/`delivery_longitude` válidos → `sale.order.delivery_latitude` fijado; el `res.partner` no cambia.
  - `test_checkout_rechaza_coords_invalidas`: valores `''`, `'abc'`, `0`/`0`, `95`, y punto fuera del rectángulo de cobertura (`logistica.zona` / configuración) → el pedido no se confirma; respuesta con error visible.
  - `test_checkout_sin_datos_no_confirma`: falta teléfono → no hay confirmación.
  - `test_pago_prueba_confirma_pedido`: completar el pago de prueba → `sale.order.state == 'sale'` y una `logistica.entrega` en `en_preparacion`.
  - `test_seguimiento_token_invalido_404`: token inventado → `404`, sin datos del pedido en el cuerpo.
  - `test_seguimiento_no_expone_coordenadas`: la página de un token válido no contiene `latitude`/`longitude`/`lat`/`lon` (D8).
  - `test_seguimiento_estados_simplificados`: `pendiente_preparacion`/`en_preparacion` → «En preparación»; `preparado` → «Preparado»; `en_recorrido` → «En ruta»; `entregado` → «Entregado»; `no_entregado`/`pendiente_reprogramacion` → «No entregado»; `devuelto_bodega` → «En retorno a bodega».
  - `test_rate_limit`: más de 30 peticiones por minuto a `/logistica/seguimiento/*` desde la misma IP → `429`.
  - `test_confirmacion_muestra_enlace`: la página de confirmación incluye `/logistica/seguimiento/`.

- [ ] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [ ] **Step 3: Implementar**
  - Investigar el flujo de `website_sale` 16.0 en el contenedor (`/usr/lib/python3/dist-packages/odoo/addons/website_sale`) antes de sobrescribir: el controlador `WebsiteSale.address` y `_checkout_form_save`; el flujo de pago de prueba (`payment_custom`).
  - El pin se guarda en el **pedido** (no en el contacto), cumpliendo §3.1.
  - Validación de coordenadas: numérico, `-90 ≤ lat ≤ 90`, `-180 ≤ lon ≤ 180`, no `(0,0)`, dentro del rectángulo de cobertura de la configuración si está definido.
  - Confirmación automática (D5): al completar el pago de prueba se llama `order.action_confirm()`; si la validación falla, no se confirma y se informa al cliente (§3.1).
  - Seguimiento: `GET /logistica/seguimiento/<token>` (`auth='public'`) devuelve una página con número de pedido, estado simplificado y fecha; límite de peticiones por IP en memoria (`collections.deque`).

- [ ] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `0 failed, 0 error(s)`, 9 pruebas.

- [ ] **Step 5: Verificar en el navegador (prueba manual)**
  Run: abrir `http://localhost:8069/shop`, agregar un producto, completar el checkout y colocar el pin. Expected: pedido en Odoo con coordenadas y entrega en `en_preparacion`.

---

### Task 8: `logistica_despacho` — planificación, rutas, carga y ejecución

> **Hecho el 2026-11-08** (19 pruebas de despacho, 0 fallos). Desviaciones y decisiones: `docs/decisiones_tareas_8_13.md`.

Implementa §3.2 (planificación, rutas, monitoreo de incidencias), §5 M4, §7 etapas 3–4, §8.3, §8.4, §9, §1.1 reglas 5–7. Reemplaza `logistica.ruta` y `logistica.ruta.parada` de la versión actual.

**Files:**
- Modify: `odoo/addons/logistica_despacho/__manifest__.py` (depends: `fleet`, `logistica_entregas`, `logistica_base`)
- Replace: `odoo/addons/logistica_despacho/models/logistica_ruta.py`, `logistica_ruta_parada.py`
- Create: `odoo/addons/logistica_despacho/models/logistica_planificador.py` (TransientModel; cliente de C1 `/optimize`)
- Create: `odoo/addons/logistica_despacho/services/routing_client.py` (`requests`, timeout 15 s; lee `logistica.routing_url`)
- Modify: `odoo/addons/logistica_despacho/views/logistica_ruta_views.xml`, `views/menu_views.xml` (acción «Planificar despacho»; estados de C6)
- Modify: `odoo/addons/logistica_despacho/security/ir.model.access.csv`
- Create: `odoo/addons/logistica_despacho/tests/test_despacho.py`

**Interfaces:**
- Consumes: C1 (`/optimize`), C6 de Tasks 5 y 6 (`logistica.bodega`, `logistica.entrega`, `action_marcar_*`, `_registrar_evento`), `fleet.vehicle.logistica_capacidad`, `fleet.vehicle.driver_id`.
- Produces: C6 (`logistica.ruta`, `logistica.ruta.parada`, `logistica.planificador`).

- [x] **Step 1: Escribir pruebas que fallan** (con `routing_client` parcheado con `unittest.mock`)
  - `test_planificador_rutas_desde_bodega`: el origen enviado a `/optimize` es la bodega activa; el resultado crea rutas `borrador` con paradas en el orden devuelto.
  - `test_planificador_solo_preparados`: una entrega en `en_preparacion` no entra en la propuesta.
  - `test_no_asignados_quedan_preparados`: una parada en `unassigned` deja la entrega en `preparado` y registra el motivo.
  - `test_aprobar_plan`: `borrador` → `planificada`; las entregas pasan a `asignado`.
  - `test_confirmar_carga_requiere_paradas`: ruta sin paradas → `UserError`; con paradas → `carga_confirmada` y `confirmed_load_at` fijado.
  - `test_iniciar_solo_desde_carga_confirmada`: desde `planificada` → `UserError`.
  - `test_doble_inicio_rechazado`: segunda llamada a `action_iniciar_recorrido` → `UserError`; un solo evento `inicio_recorrido`.
  - `test_nuevo_pedido_no_entra_a_ruta_iniciada`: con la ruta en `en_recorrido`, el planificador excluye la entrega nueva; añadir una parada con `write` → `UserError`.
  - `test_cerrar_diferencia_fallidos`: cerrar con paradas `no_entregado` no las cuenta como `entregado`; con pendientes → `UserError`.
  - `test_cancelar_antes_de_iniciar`: `planificada` → `cancelada`; las entregas vuelven a `preparado`.
  - `test_interrumpir_durante_ejecucion`: `en_recorrido` → `interrumpida` con motivo; entregas no entregadas → `pendiente_reprogramacion`.
  - `test_capacidad_del_vehiculo`: el payload a `/optimize` lleva `capacity` de `logistica_capacidad`.

- [x] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [x] **Step 3: Implementar**
  - `logistica.ruta`: campos de C6; `_order` por fecha; `name` con secuencia `logistica.ruta` (`RUTA/%(year)s/`).
  - Máquina de estados: `borrador → planificada` (aprobación); `planificada → carga_confirmada` (conductor); `carga_confirmada → en_recorrido`; `en_recorrido → cerrada`; `borrador|planificada → cancelada`; `en_recorrido → interrumpida`.
  - `write` de `stop_ids` en estados `carga_confirmada`, `en_recorrido`, `cerrada`, `cancelada`, `interrumpida` → `UserError` (regla §1.1 #7 y §8.4).
  - `logistica.planificador.action_proponer()`: envía bodega + entregas `preparado` (sin ruta activa) + vehículos con conductor y capacidad; crea rutas `borrador` con `optimization_version` devuelto. Entregas no asignadas quedan `preparado` con motivo en el chatter.
  - `action_marcar_en_recorrido`: usado por `action_iniciar_recorrido`; cada parada llama `entrega.action_marcar_en_recorrido()`.
  - `assert_driver(user)`: el usuario debe tener `partner_id == driver_id` de la ruta (usado en Task 10).
  - `logistica.ruta.parada`: `action_marcar_llegada` (evento, sin cambio de estado de entrega), `action_marcar_entregado`, `action_marcar_no_entregado(motivo, notas)`: delegan en la entrega (Task 6).

- [x] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `0 failed, 0 error(s)`, 12 pruebas.

- [x] **Step 5: Verificar actualización**
  Run: `docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_despacho --stop-after-init`. Expected: sin errores.

---

### Task 9: `logistica_traccar` — monitoreo, posiciones, llegada por proximidad e informes

> **Hecho el 2026-11-08** (88 pruebas del módulo). `cron_poll_positions` no se crea: lo cubre `cron_sincronizar` de la Fase 1. Mapa solo para gestores de flota.

Implementa §5 M5, §6 (flujo, consultas, llegada vs. entrega, fallos), §3.2 (monitoreo GPS). Extiende el módulo existente.

**Files:**
- Modify: `odoo/addons/logistica_traccar/__manifest__.py` (depends: `fleet`, `logistica_despacho`, `logistica_entregas`)
- Modify: `odoo/addons/logistica_traccar/models/traccar_server.py` (informes, cron de sondeo, errores sin excepción)
- Modify: `odoo/addons/logistica_traccar/models/traccar_device.py` (`_registrar_posicion`, `is_stale`, conversión de nudos)
- Create: `odoo/addons/logistica_traccar/models/logistica_traccar_posicion.py`
- Create: `odoo/addons/logistica_traccar/models/logistica_ruta_parada_gps.py` (`_check_proximidad`, herencia de `logistica.ruta.parada`)
- Create: `odoo/addons/logistica_traccar/controllers/monitoreo.py` (`/logistica/monitoreo` HTML y `/logistica/monitoreo/data` JSON; `auth='user'`, grupo de flota)
- Create: `odoo/addons/logistica_traccar/views/traccar_cron.xml` (`ir.cron` cada `logistica.traccar_poll_minutes`), `views/monitoreo_templates.xml` (Leaflet)
- Create: `odoo/addons/logistica_traccar/tests/test_traccar.py` (con `requests` parcheado)

**Interfaces:**
- Consumes: Traccar (`/api/positions`, `/api/reports/route|trips|stops`); C6 de Tasks 5, 6 y 8 (`logistica.configuracion`, `logistica.ruta.parada`, `action_marcar_llegada`).
- Produces: C6 (`logistica.traccar.posicion`, `traccar.device._registrar_posicion`, `traccar.server.get_*`, `cron_poll_positions`).

- [x] **Step 1: Escribir pruebas que fallan**
  - `test_cron_crea_posicion_por_vehiculo`: `/api/positions` mock con una posición del dispositivo vinculado → una `logistica.traccar.posicion` con el `vehicle_id` correcto.
  - `test_sin_duplicados_al_repetir`: el mismo `id` de posición en dos sondeos → un solo registro.
  - `test_posicion_desactualizada_marca_stale`: `gps_time` hace 301 s → `is_stale=True`; el JSON de monitoreo incluye `ultima_ubicacion_conocida` y `antiguedad_s`, nunca un valor simulado.
  - `test_traccar_caido_no_rompe`: `requests.ConnectionError` → el cron no lanza excepción, `last_error_message` queda registrado y los pedidos no cambian.
  - `test_nudos_a_kmh`: `speed=10` → `speed_kmh=18.52`.
  - `test_dispositivo_sin_vehiculo_ignorado`: posición de un dispositivo sin vehículo → no crea registro.
  - `test_llegada_por_proximidad_no_entrega`: posición a 30 m de una parada `en_recorrido` → evento `posible_llegada`, `arrival_candidate_at` fijado, la entrega sigue en `en_recorrido`.
  - `test_informes_parametros`: `get_route_report` construye `deviceId`, `from` y `to` en ISO-8601 UTC.
  - `test_monitoreo_sin_credenciales`: el JSON de `/logistica/monitoreo/data` no contiene `password`, `Authorization` ni `base_url`.

- [x] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [x] **Step 3: Implementar**
  - `cron_poll_positions()`: una sola llamada a `/api/positions` (sin `deviceId`); por cada posición con dispositivo vinculado a un vehículo: `_registrar_posicion`. Errores de red → `state='error'`, `last_error_message`; no se relanzan.
  - `_check_proximidad(lat, lon)` en `logistica.ruta.parada`: distancia haversine a la entrega; dentro de `arrival_radius_m` y en `en_recorrido` → `action_marcar_llegada` con el GPS.
  - Monitoreo: mapa Leaflet con la última posición por vehículo, hora, antigüedad, marca de desactualizado y recorrido de la ruta activa (`get_route_report`).
  - Llamadas a Traccar solo desde el servidor; `auth='user'`.

- [x] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `0 failed, 0 error(s)`, 9 pruebas.

- [x] **Step 5: Verificar actualización**
  Run: `docker compose exec -T odoo /entrypoint.sh odoo -d logistica_dev -u logistica_traccar --stop-after-init`. Expected: sin errores.

---

### Task 10: `logistica_conductor` — portal móvil restringido

> **Hecho el 2026-11-08** (13 pruebas HTTP). El grupo es `logistica_conductor.group_conductor`. El paso 5 (prueba manual en el navegador) queda para ti: ver el checklist del README.

Implementa §3.3, §5 M6, §7 etapas 4–5, §8.2 y la sección «Seguridad» del Módulo 6. Nuevo módulo.

**Files:**
- Create: `odoo/addons/logistica_conductor/__init__.py`, `__manifest__.py` (depends: `website`, `logistica_despacho`)
- Create: `odoo/addons/logistica_conductor/security/security.xml` (grupo `logistica.group_conductor`; reglas de registro: `driver_id = user.partner_id`), `security/ir.model.access.csv`
- Create: `odoo/addons/logistica_conductor/controllers/conductor.py` (`/logistica/conductor`, `/logistica/conductor/ruta/<int:route_id>`, POST `confirmar-carga`, `iniciar`, `parada/<int:stop_id>/llegada|entregado|no-entregado`, `cerrar`)
- Create: `odoo/addons/logistica_conductor/views/conductor_templates.xml` (diseño móvil: lista de rutas, detalle con siguiente parada, botones grandes, `Navegar` con enlace a Google Maps)
- Create: `odoo/addons/logistica_conductor/tests/test_conductor.py` (`HttpCase`)

**Interfaces:**
- Consumes: C6 de Tasks 6 y 8 (`logistica.ruta` métodos y `assert_driver`, `logistica.ruta.parada.action_marcar_*`).
- Produces: rutas HTTP descritas arriba.

- [x] **Step 1: Escribir pruebas que fallan**
  - `test_conductor_solo_ve_sus_rutas`: conductor A ve solo su ruta en `/logistica/conductor`; `GET /logistica/conductor/ruta/<id de B>` → `403` o `404`.
  - `test_regla_registro_por_conductor`: búsqueda ORM como conductor A → solo rutas con `driver_id == A.partner_id`.
  - `test_usuario_sin_grupo_403`: usuario sin grupo conductor → `403`.
  - `test_confirmar_e_iniciar`: `POST confirmar-carga` → `carga_confirmada`; `POST iniciar` → `en_recorrido`.
  - `test_entregado_idempotente`: dos `POST entregado` → un solo evento; la segunda respuesta es `409` con mensaje «ya registrado».
  - `test_no_entregado_requiere_motivo`: `POST no-entregado` sin motivo → `400`; con `absent` → estado `no_entregado` y motivo guardado.
  - `test_orden_de_paradas`: la página muestra las paradas ordenadas por `sequence` y marca la siguiente pendiente.
  - `test_conductor_no_entrega_ajena`: conductor A no puede marcar una parada de la ruta de B → `403`.

- [x] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [x] **Step 3: Implementar**
  - Controladores con `auth='user'`; cada ruta/parada se resuelve con `request.env` (reglas de registro activas) y se verifica con `assert_driver`; no se usa `sudo()` para datos del conductor.
  - Idempotencia: el estado de la parada decide; si ya está registrada → `409`.
  - Snapshot GPS: al registrar, se adjunta el último GPS del vehículo (Task 6 `_gps_snapshot`).
  - Mensajes de error en español; el cuerpo de error no revela datos de otras rutas.

- [x] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `0 failed, 0 error(s)`, 8 pruebas.

- [ ] **Step 5: Verificar en el navegador (prueba manual)**
  Run: abrir `http://localhost:8069/logistica/conductor` con un usuario conductor. Expected: solo sus rutas; flujo completo sin ver la vista de backend.

---

### Task 11: `logistica_analitica_ia` — consulta de destinos probables en Odoo

> **Hecho el 2026-11-08** (14 pruebas).

Implementa §5 M7, §10.4 (mapa y ruta vial), §5 «Distinción» (no asigna pedidos). Nuevo módulo.

**Files:**
- Create: `odoo/addons/logistica_analitica_ia/__init__.py`, `__manifest__.py` (depends: `logistica_traccar`, `logistica_despacho`)
- Create: `odoo/addons/logistica_analitica_ia/models/logistica_prediccion_consulta.py`, `models/logistica_prediccion_wizard.py`, `services/ml_client.py`, `services/routing_geometry.py`
- Create: `odoo/addons/logistica_analitica_ia/views/prediccion_views.xml`, `views/menu_views.xml`
- Create: `odoo/addons/logistica_analitica_ia/security/ir.model.access.csv`
- Create: `odoo/addons/logistica_analitica_ia/tests/test_prediccion.py` (con `requests` parcheado)

**Interfaces:**
- Consumes: C2 (`/predict`, `/metrics`), C1 (`/route`), `logistica.zona.centroide` (Task 5), `fleet.vehicle`.
- Produces: C6 (`logistica.prediccion.consulta`); acción «Predecir destino».

- [x] **Step 1: Escribir pruebas que fallan**
  - `test_consulta_guarda_auditoria`: `ml_client` mock → consulta con `predicted_zone`, `class_probabilities` JSON, `model_version`, `alternatives` (3).
  - `test_no_asigna_pedidos`: ejecutar una predicción no cambia estados de `logistica.entrega`, `logistica.ruta` ni `sale.order`.
  - `test_ml_caido_mensaje_claro`: ML devuelve `503` o no responde → `UserError` con el mensaje «El modelo predictivo no está disponible»; no se crea consulta.
  - `test_ruta_sugerida`: `routing_geometry` mock → `route_geometry` guardada con puntos `[lat, lon]`; la vista muestra la distancia y la fuente (`estimado_haversine` o `osrm`).
  - `test_zona_origen_obligatoria`: sin `origin_zone` → `ValidationError`.
  - `test_probabilidades_suman_uno`: las probabilidades guardadas suman 1 ± 1e-6.

- [x] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [x] **Step 3: Implementar**
  - Wizard: vehículo, fecha, hora, zona de origen → `action_predecir()`: llama a C2 `/predict` con `vehicle_code` = placa, `reference_datetime` en UTC; guarda la consulta; llama a C1 `/route` desde el centroide de origen al centroide del destino predicho.
  - Vista de resultado: destino probable, alternativas con probabilidades, mapa Leaflet con la ruta, enlace a `/metrics` (accuracy, F1, matriz de confusión, baseline).
  - Ninguna escritura sobre pedidos, entregas o rutas (§5 M7).

- [x] **Step 4: Ejecutar pruebas y verificar que pasan**
  Expected: `0 failed, 0 error(s)`, 6 pruebas.

- [x] **Step 5: Verificar actualización**
  Run: instalar con `-i logistica_analitica_ia`. Expected: sin errores.

---

### Task 12: Datos de demostración y dispositivos GPS

> **Hecho el 2026-11-08** con desviaciones: la demostración está en `seeds/data/*.json` y `seeds/seed.py` (no `seeds/demo_data.py` ni `gps_demo.py`); los pasos se verificaron con `tests/e2e/test_flujo.py` y `verify_flujo.py`.

Implementa los datos de §11 (bodega, 3 vehículos y conductores, 5 pedidos web) y deja listas las condiciones de §13 (≥3 vehículos/conductores con dispositivo verificable).

**Files:**
- Modify: `seeds/demo_data.py` (idempotente; usa XML-RPC contra Odoo o el ORM como hoy)
- Create: `seeds/gps_demo.py` (crea dispositivos en Traccar por `POST /api/devices` y envía posiciones por OsmAnd `http://traccar:5055/?id=<uniqueId>&lat=&lon=&speed=&timestamp=`)
- Create: `seeds/productos_demo.xml` o carga por ORM: 5 productos publicados en la tienda

**Interfaces:**
- Consumes: C6 de Tasks 5–10; Traccar REST y OsmAnd.
- Produces: datos que consume Task 13.

- [x] **Step 1: Escribir pruebas que fallan** (`seeds/tests/test_seeds.py`, ejecutadas contra el stack)
  - `test_seed_idempotente`: dos ejecuciones → 1 bodega activa, 3 `fleet.vehicle` con conductor, 3 `traccar.device`, 5 `product.template` publicados, 5 `sale.order` confirmados con destino y 5 `logistica.entrega` en `en_preparacion`.
  - `test_vehiculos_con_dispositivo_unico`: cada vehículo tiene un dispositivo distinto (`uniqueId` `LOG-001`…`LOG-003`).
  - `test_posiciones_en_traccar`: tras `gps_demo.py`, `/api/positions` devuelve posiciones para los 3 dispositivos con `fixTime` reciente.

- [x] **Step 2: Ejecutar y verificar que fallan**
  Expected: FAIL.

- [x] **Step 3: Implementar**
  - `seeds/demo_data.py`: crea o reutiliza cada registro por clave natural (placa, nombre, `uniqueId`); usuarios conductor con `is_driver=True` y grupo `logistica.group_conductor`.
  - `seeds/gps_demo.py`: envía posiciones con `timestamp` UTC actual y `speed` en nudos (Traccar lo convierte).
  - Lo de la especificación §11 (cinco pedidos) se crea con `sale.order` y `action_confirm()`; las entregas quedan en `en_preparacion` (sin preparar, para la prueba de Task 13).

- [x] **Step 4: Ejecutar pruebas y verificar que pasan**
  Run: `docker compose exec -T odoo python3 /mnt/extra-addons/../seeds/demo_data.py` (ver ruta real en el contenedor), luego `python3 seeds/gps_demo.py`. Expected: pruebas en verde.

- [x] **Step 5: Verificar idempotencia**
  Run: volver a ejecutar ambos scripts. Expected: sin duplicados.

---

## Phase C — Integración y verificación

### Task 13: Verificación de extremo a extremo y documentación

> **Hecho el 2026-11-08:** `python scripts/verify_flujo.py` → 14/14 criterios; el paso 5 (instalación sobre una base nueva `logistica_dev_prueba`) no se hizo: se verificó antes el arranque desde cero de la Fase 1 en un proyecto limpio.

Cierra los 14 criterios de §13 con una prueba automatizada y actualiza los scripts de despliegue.

**Files:**
- Create: `scripts/verify_flujo.py` (solo biblioteca estándar: `urllib`, `xmlrpc.client`, `json`; se ejecuta en el host)
- Modify: `scripts/setup.ps1`, `scripts/setup.sh` (instalación de `logistica_entregas`, `logistica_checkout`, `logistica_conductor`, `logistica_analitica_ia`; paso `etl bootstrap`)
- Modify: `README.md` (secciones de los servicios, flujo funcional y verificación)

**Interfaces:**
- Consumes: todas las tareas anteriores.
- Produces: informe con PASS/FAIL por criterio.

- [x] **Step 1: Escribir la verificación** (un bloque por criterio de §13, en el mismo orden)
  1. Cliente navega, compra sin cuenta y marca destino → flujo HTTP `/shop` → `/shop/cart` → `/shop/address` con coordenadas → pago de prueba.
  2. El pedido aparece en Odoo con productos, contacto y coordenadas → XML-RPC `sale.order`.
  3. Pasa a preparación sin aprobación manual → `logistica.entrega.state == 'en_preparacion'`.
  4. Al menos 3 vehículos/conductores con dispositivo verificable → `fleet.vehicle` con `traccar_device_id` distinto.
  5. El administrador genera y revisa una asignación desde la bodega común → `logistica.planificador.action_proponer()` y origen = bodega.
  6. El conductor ve solo sus rutas, confirma carga e inicia → HTTP `/logistica/conductor`.
  7. Posiciones de Traccar asociadas al vehículo correcto con marca de tiempo → `logistica.traccar.posicion`.
  8. La llegada GPS no marca entregado → estado de la entrega sin cambio tras posición cercana.
  9. Conductor marca «Entregado» o «No entregado» con motivo y auditoría → eventos.
  10. Una ruta iniciada no recibe pedidos nuevos → pedido nuevo fuera de la ruta.
  11. Cliente consulta su pedido con enlace protegido → HTTP `/logistica/seguimiento/<token>`.
  12. ETL extrae ambas APIs, valida y carga el modelo dimensional → `etl run` y conteos en `dwh`.
  13. El BI usa el DWH → `GET http://127.0.0.1:8501/_stcore/health` y ausencia de dependencias de Odoo (Task 4).
  14. El modelo de IA predice destinos, incluye métricas y presenta ruta vial → `/predict`, `/metrics`, `/route`.

- [x] **Step 2: Ejecutar y verificar que falla**
  Run: `python scripts/verify_flujo.py`. Expected: FAIL en los criterios no cumplidos todavía.

- [x] **Step 3: Corregir lo que falle**
  Cada fallo se corrige en la tarea que lo produce; no se relajan las comprobaciones.

- [x] **Step 4: Ejecutar la verificación completa**
  Run: `python scripts/verify_flujo.py`. Expected: `14/14 criterios cumplidos` y código de salida `0`.

- [ ] **Step 5: Verificar instalación limpia y actualización**
  Run: `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1` sobre una base nueva (`logistica_dev_prueba`), y luego la actualización sobre `logistica_dev`. Expected: sin errores en el log de Odoo y `verify_flujo.py` en verde.

---

## Self-review del plan

- **Cobertura de §13 (14 criterios):** verificados en Task 13 paso 1 (1 → Tareas 7 y 12; 2 → 6 y 7; 3 → 6; 4 → 5 y 12; 5 → 8; 6 → 10; 7 → 9 y 12; 8 → 6 y 9; 9 → 6 y 10; 10 → 8; 11 → 7; 12 → 3; 13 → 4; 14 → 2 y 11).
- **Cobertura de §5 (módulos M1–M7):** M1 → T5; M2 → T7; M3 → T6; M4 → T8; M5 → T9; M6 → T10; M7 → T11.
- **Cobertura de §8 (estados):** C6 de entregas y rutas; transiciones en T6 y T8.
- **Cobertura de §9 (optimización):** C1 y T1, T8.
- **Cobertura de §10 (analítica/IA):** T3, T4, T2, T11.
- **Cobertura de §12 (seguridad):** T7 (token, rate limit, sin coordenadas), T9 (sin credenciales), T10 (reglas por conductor), T4 (BI sin Odoo), T11 (no asigna pedidos).
- **Consistencia de nombres:** los estados y motivos son los de Global Constraints y se usan igual en T6, T8, T10 y T13. Las rutas HTTP son las de C1 y C2.
- **Huecos conocidos:** los centroides de zonas (D10) son aproximados y deben verificarse con el usuario. La carga de OSRM con mapa real queda opcional (D2).
