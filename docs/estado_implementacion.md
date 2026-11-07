# Estado de la implementación — Sistema Inteligente de Rastreo y Analítica de Rutas

**Fecha:** 2026-11-05

**Actualización 2026-11-07 (Fase 1, no reescribe esta tabla):** la tarea 7 de `docs/superpowers/plans/2026-11-06-fase1-odoo-traccar.md` ya está en el código: cron de un minuto hacia `cron_sincronizar` y botón «Sincronizar ahora». La tarea 8 tiene el simulador OsmAnd (`seeds/simular.py`) y sus pruebas locales; la comprobación en vivo de eventos no se hizo. La tarea 9 tiene el escaneo estático y el E2E escrito; el E2E no se corrió contra el stack. La tarea 9 de *este* documento (monitoreo GPS: llegada por proximidad, mapa, informes) sigue pendiente. El detalle vive en el README, sección de estado.
**Especificación:** [flujo_funcional_odoo_traccar.md](flujo_funcional_odoo_traccar.md)
**Plan de implementación:** [superpowers/plans/2026-11-05-rastreo-analitica-rutas.md](superpowers/plans/2026-11-05-rastreo-analitica-rutas.md)

---

## 1. Resumen

| Estado | Tareas del plan |
|---|---|
| **Hecho y revisado** | 1 routing · 2 ML · 3 ETL/DWH · 4 BI · 5 logistica_base · 6 logistica_entregas · 7 logistica_checkout · consolidación de Docker Compose |
| **Pendiente** | 8 logistica_despacho · 9 logistica_traccar (monitoreo) · 10 logistica_conductor · 11 logistica_analitica_ia · 12 datos de demostración · 13 verificación de extremo a extremo y documentación de despliegue |

Cada tarea hecha tuvo implementación, pruebas y una revisión independiente. Las correcciones se re-revisaron de forma acotada hasta quedar sin hallazgos críticos ni importantes. Los hallazgos menores que quedaron abiertos están en la sección 6.

**Aviso importante:** el flujo funcional completo (despacho, conductor, monitoreo y verificación de los 14 criterios de §13) **todavía no está implementado**. Lo que hay es la base técnica: analítica, datos, checkout y entregas.

---

## 2. Cómo arrancar

| Qué | Comando | Servicios |
|---|---|---|
| Núcleo (por defecto) | `docker compose up -d` | `db`, `odoo` (8069), `traccar` (8082, 5055) |
| Analítica | `docker compose --profile analitica up -d` | `routing` (8001), `ml` (8002), `bi` (8501) |
| ETL (bajo demanda) | `docker compose --profile etl run --rm etl ...` | `etl` (requiere `ODOO_PASSWORD`) |

Los servicios de analítica no arrancan por defecto para no saturar la máquina. Mientras estén apagados, las pantallas de Odoo que los usen (planificación y predicción) mostrarán un error. Es lo esperado.

**Variables nuevas en `.env`** (ver `.env.example`):

| Variable | Obligatoria | Para qué |
|---|---|---|
| `ODOO_PASSWORD` | Sí, para `etl run` | Contraseña del usuario `admin` de Odoo. Sin valor por defecto. |
| `DWH_DB_PASSWORD` | No | Si tiene valor, el bootstrap crea el rol de solo lectura `dwh_ro` para BI. Vacía, no se crea el rol. |
| `ROUTING_OSRM_URL` | No | Servidor OSRM para distancias por carretera. Si falta, se usa estimación haversine × 1,3, etiquetada como tal. |

---

## 3. Hecho, por tarea

| # | Componente | Qué quedó | Pruebas | Revisión |
|---|---|---|---|---|
| 1 | `services/routing` | API `/matrix`, `/route`, `/optimize`. Solver OR-Tools con capacidad. Razón `sin_capacidad` o `sin_ruta` por parada no asignada. Máximo 200 paradas. Cada respuesta indica su fuente (`osrm` o `estimado_haversine`). | 38 pasan | Aprobada tras 1 ronda de correcciones |
| 2 | `services/ml` | Entrenamiento con corte temporal 80/20 (sin aleatorio). Métricas completas y comparación con predictor base. `/predict` devuelve destino, probabilidades y alternativas. Recarga el modelo al reentrenar. Resultado en datos SIMULADOS: accuracy 0,764 frente a 0,259 del base. | 9 pasan | Aprobada tras 1 ronda |
| 3 | `services/etl` | Extracción de Odoo (XML-RPC) y Traccar (API). Staging, reglas de calidad y rechazados. Modelo dimensional (`DIM_*`, `FACT_*`) en `logistica_dwh`. Vinculación entrega–recorrido solo con coincidencia verificable de vehículo, ruta y ventana. Rol `dwh_ro` de solo lectura. Carga de 547 filas SIMULADO. | 23 pasan | Aprobada tras 1 ronda |
| 4 | `services/bi` | Panel Streamlit sobre el DWH. Consultas OLAP con `ROLLUP`. Filtros de fecha y de procedencia (REAL/SIMULADO). No importa Odoo. | 4 pasan (requiere `DWH_ADMIN_DSN`) | Aprobada |
| 5 | `logistica_base` | Bodega única activa. Configuración con radio de llegada 50 m, GPS desactualizado a los 300 s, capacidad por defecto de 10 bultos. Zonas de Ambato con centroides aproximados. | 5 pasan (con el de traccar) | Aprobada tras 1 ronda |
| 6 | `logistica_entregas` | Entrega por pedido. Máquina de estados con bloqueo de fila. Eventos de solo lectura. Token seguro con vencimiento y revocación. Auditoría de cambios de destino (`destino_corregido`). Gestores no pueden crear entregas ni fijar estados por ORM. | 17 pasan | Aprobada tras 4 rondas |
| 7 | `logistica_checkout` | Checkout con mapa y validación de coordenadas. Confirmación automática **solo** con proveedor de pago de prueba. Seguimiento público con token: 404 si es inválido, revocado o vencido. Límite de 30 peticiones por minuto. Revocación de token para gestores. | 34 pasan en la ejecución combinada, 0 omitidas | Aprobada tras 1 ronda |
| — | `compose.yaml` | Un solo archivo. Perfiles `analitica` y `etl`. Sin credenciales por defecto en el código. | `docker compose config` válido | — |

---

## 4. Pendiente

### Tarea 8 — `logistica_despacho` (planificación, rutas, carga y ejecución)
- Reescribir rutas con los estados de §8.3: `borrador → planificada → carga_confirmada → en_recorrido → cerrada`, más `cancelada` e `interrumpida`.
- Planificador que llama a `/optimize` desde la bodega común y crea rutas en borrador.
- Aprobación del plan; confirmación de carga por el conductor; inicio que bloquea pedidos nuevos (§1.1 regla 7).
- Cierre con resultados diferenciados (fallidos no cuentan como entregados).
- Convertir `route_id` de la entrega a `Many2one` y añadir `route_stop_ids` (ruling R11).
- Quitar el filtro provisional del menú «Pedidos por Despachar» y unificar la raíz de menús (hallazgos diferidos).

### Tarea 9 — `logistica_traccar` (monitoreo GPS)
- Registro de lecturas por vehículo, sin duplicados.
- Sondeo periódico (cron, 1 minuto) de `/api/positions`.
- Marca de desactualizado a los 300 s, mostrando «Última ubicación conocida» sin simular movimiento.
- Llegada por proximidad (50 m) que solo registra `posible_llegada`, nunca `entregado`.
- Informes de ruta, viajes y paradas. Mapa de monitoreo sin credenciales en el navegador.

### Tarea 10 — `logistica_conductor` (portal móvil)
- Rutas en `/logistica/conductor`, solo las propias (reglas de registro por conductor).
- Confirmar carga, iniciar, llegada, entregado, no entregado con motivo obligatorio.
- Idempotencia: un doble clic no duplica eventos.
- Falta `security.xml` con el grupo `logistica.group_conductor` (ruling R13).

### Tarea 11 — `logistica_analitica_ia` (predicción en Odoo)
- Asistente para elegir vehículo, fecha, hora y zona de origen.
- Llama a `/predict` y a `/route`. Guarda cada consulta como auditoría.
- Muestra destino, alternativas, probabilidades y ruta en mapa. No asigna pedidos.

### Tarea 12 — Datos de demostración
- Bodega, tres vehículos con conductor, tres dispositivos Traccar (`LOG-001`…`LOG-003`), cinco productos publicados y cinco pedidos confirmados.
- Posiciones GPS de prueba enviadas a Traccar por el protocolo OsmAnd (puerto 5055).

### Tarea 13 — Verificación de extremo a extremo y despliegue
- `scripts/verify_flujo.py` con los 14 criterios de §13, sin dependencias externas.
- Actualizar `scripts/setup.ps1` y `setup.sh` (módulos nuevos, arranque de analítica).
- Actualizar el README con los servicios, perfiles y pasos de verificación.

---

## 5. Decisiones tomadas sin confirmar

La especificación deja algunas preguntas abiertas (§14) y valores sin fijar. Estas son las decisiones tomadas; **conviene confirmarlas**.

| # | Decisión | Por qué | Confirmar |
|---|---|---|---|
| D1 | Almacén de datos en PostgreSQL, no SQL Server | SQL Server aparece solo en el resumen de §15 | **Sí** |
| D2 | Distancias: OSRM si hay URL; si no, estimación haversine × 1,3 etiquetada | No hay mapa OSM garantizado | Sí |
| D3 | Capacidad en bultos (1 entrega = 1 bulto) | §14.3 abierta | Sí |
| D4 | Preparación con botón manual «Marcar preparado» | §14.1 abierta | Sí |
| D5 | Pago de prueba sin cobro real; confirmación automática solo con proveedor de prueba | §14.2 abierta | Sí |
| D6 | Radio de llegada 50 m; GPS desactualizado a los 300 s | Valores no fijados | Sí |
| D7 | Entrega fallida queda pendiente de reprogramación; el administrador decide | §14.6 abierta | Sí |
| D8 | Seguimiento público sin coordenadas del vehículo | §14.5 abierta | Sí |
| D9 | Histórico de demostración marcado como SIMULADO | §10.4 | No |
| D10 | Centroides de zonas aproximados | La especificación no da coordenadas | **Sí** |
| D11 | Sin commits durante la implementación (ahora sí, por petición) | Petición del usuario | No |

Otras decisiones de diseño tomadas durante las revisiones (rulings R1–R25) están en el libro de control, que es local y no se versiona. Las más relevantes:

- **R1:** la restricción de dispositivo Traccar único vive en `logistica_traccar`, para evitar un ciclo de dependencias.
- **R6:** los generadores de datos simulados de ML y ETL son separados, para que los servicios no se importen entre sí.
- **R19 y R21:** `ODOO_PASSWORD` y `DWH_DB_PASSWORD` se pasan sin `:?`, porque esa sintaxis rompe todos los comandos de Compose cuando la variable falta.
- **R20:** el rol `dwh_ro` real no se creó, porque requiere una contraseña nueva que decide el usuario.
- **R25:** la confirmación automática solo aplica al proveedor de prueba.

---

## 6. Hallazgos diferidos (para la revisión final)

Son defectos o mejoras que las revisiones marcaron como menores. No bloquearon las tareas, pero hay que resolverlos antes de dar el sistema por terminado.

**Defectos reales (prioridad):**
- `services/bi/app.py:47`: si se selecciona una sola fecha, el filtro queda silenciosamente vacío y se muestran todos los datos.

**BI:**
- Los resultados SIMULADO solo se marcan con un aviso; las tablas no tienen columna de procedencia.
- `olap.py:167`: un DSN con espacios o comillas en la contraseña se rompe. Usar `psycopg2.connect(**kwargs)`.
- Un `placa` NULL se confunde con la fila de total del `ROLLUP`.
- `tests/dwh_schema.sql` copia el esquema del ETL; puede desviarse.

**ML:**
- Escritura no atómica de `model.joblib` y `metrics.json` (se puede leer un archivo a medias durante un reentrenamiento).
- Carga perezosa sin candado; `vehicle_code` sin validar; menos de 3 alternativas si hay menos de 4 clases; conexión a base de datos sin cerrar.

**Routing:**
- `/matrix` acepta valores negativos; `ROUTING_TIME_LIMIT_S` no entero produce un 500; ids duplicados sin validar.
- OSRM por defecto acepta 100 puntos; de 101 a 200 se usa la estimación (etiquetada).

**ETL:**
- Un cambio solo en la ruta no actualiza `planificado_utc`.
- `stg.*` crece sin retención; la contraseña del DSN no se codifica en URL; `REVOKE CONNECT ... FROM PUBLIC` pendiente.
- Faltan pruebas con valores nulos y con desfase horario de Traccar.

**Odoo (`logistica_base`, `logistica_despacho`):**
- `logistica.configuracion.unlink` bloquea la desinstalación del módulo.
- Dos raíces de menú («Logística» y «Despacho & Rutas»).
- La lista de zonas está duplicada en `sale_order.py`.
- Comentarios muertos en `logistica_ruta.py`, que la Tarea 8 reescribe.

**Odoo (`logistica_entregas`, `logistica_checkout`):**
- Los destinos siguen siendo corregibles tras un estado terminal (quedan auditados).
- Límite de peticiones por proceso y por IP directa: correcto con un solo proceso, insuficiente con varios o detrás de un proxy.
- El token aparece en el log de acceso de Odoo (exposición conocida del diseño de URL).
- Si la cobertura tiene mínimo ≥ máximo, se desactiva en silencio.
- La revocación de tokens no genera evento de auditoría.
- Leaflet se carga desde un CDN con SRI; empaquetarlo localmente es una mejora.

**Seguridad:**
- `.env.example` contiene valores de desarrollo para contraseñas (`ODOO_DB_PASSWORD`, `TRACCAR_DB_PASSWORD`, etc.) que **ya estaban en el repositorio antes de este trabajo**. Si el repositorio es público, conviene rotarlos.

---

## 7. Verificaciones pendientes (no ejecutadas)

- **`dwh_ro` real:** no existe porque `DWH_DB_PASSWORD` no está en `.env`. El BI nunca se ha conectado con ese rol.
- **ETL completo con credenciales:** el último `run --mode full` no se repitió después de las correcciones de seguridad; la última ejecución con datos reales fue anterior.
- **Checkout en el navegador:** no se hizo, porque la base de desarrollo no tiene productos publicados.
- **Salud del contenedor `routing`:** la última comprobación lo mostró en `starting`; no se confirmó como `healthy`.
- **Pruebas de BI:** sin `DWH_ADMIN_DSN` se omiten 3 de las 4.
- **Pruebas de Odoo con el servidor vivo:** hay que usar `--http-port=8070`, porque el servidor de desarrollo ocupa el 8069.

---

## 8. Pasos siguientes recomendados

1. Confirmar las decisiones marcadas «Sí» en la sección 5, sobre todo D1 y D10.
2. Añadir `ODOO_PASSWORD` y `DWH_DB_PASSWORD` a `.env`. Con eso se crea `dwh_ro` y se puede verificar el BI en vivo.
3. Implementar las tareas 8 a 13, en ese orden. El despacho (8) debe ir antes del portal del conductor (10).
4. Corregir el defecto del filtro de fecha única del BI.
5. Hacer una revisión final de la rama completa y resolver los hallazgos diferidos de la sección 6.
