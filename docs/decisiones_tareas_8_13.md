# Decisiones y hallazgos de las tareas 8 a 13 (plan general)

Fecha: 2026-11-08. Resultado: `scripts/test_odoo.ps1` → 0 fallos en 146 pruebas de Odoo; `scripts/verify_flujo.py` → 14/14 criterios.

## Decisiones de diseño

| # | Decisión | Motivo |
|---|---|---|
| T8-1 | Las paradas solo se editan con la ruta en **borrador**. El plan permitía también «planificada»; se endureció porque al aprobar las entregas pasan a «asignado». | Evita rutas con entregas en estados distintos. |
| T8-2 | Una entrega no puede estar en dos rutas activas (`borrador`, `planificada`, `carga_confirmada`, `en_recorrido`) y un vehículo no puede tener dos rutas en recorrido. | La asociación posición GPS → ruta depende de que haya una sola. |
| T8-3 | El planificador excluye los vehículos que ya tienen una ruta activa ese día y las entregas ya incluidas en una ruta activa. | Ejecutarlo dos veces no duplica rutas. |
| T8-4 | Las acciones validan primero (actor, estado) y escriben después con `sudo()`; el conductor solo tiene permiso de lectura. | Un usuario no puede fijar estados ni tiempos por ORM. |
| T8-5 | Al cerrar la ruta, las paradas «no entregado» llevan su entrega a «pendiente de reprogramación» (D7). Interrumpir hace lo mismo con lo que seguía «en recorrido». | Mantiene la máquina de estados de la entrega. |
| T8-6 | Cancelar también se permite desde «carga confirmada». | Las entregas siguen «asignado» y pueden volver a «preparado». |
| T8-7 | Nuevos tipos de evento de entrega: `no_asignado`, `desasignado`, `ruta_interrumpida` (extensión con `selection_add` desde despacho). | Dejar rastro de lo que el planificador no asignó y de los cambios de ruta. |
| T8-8 | `logistica.entrega.route_id` y el `route_id` del evento siguen siendo enteros; se añade `ruta_id` (Many2one calculado). | Convertir la columna exigía una clave foránea con valores 0 ya usados (R11 difiere). |
| T9-1 | `cron_poll_positions` del plan no se crea: lo cubre `cron_sincronizar` de la Fase 1. | Evita dos sondeos para lo mismo. |
| T9-2 | La llegada por proximidad corre dentro de `traccar.device._registrar_posicion`, en un savepoint, y un fallo nunca rompe la sincronización. | La posición ya quedó guardada; la llegada es secundaria. |
| T9-3 | `get_route_report`, `get_trips` y `get_stops` son públicos (solo leen) y exigen personal de flota. | La regla F1-R16 pide privadas las operaciones que escriben con sudo. |
| T9-4 | El mapa de monitoreo exige **gestor de flota**. | Odoo limita a «Flota / Usuario» a los vehículos que conduce (descubierto en la primera corrida). |
| T10-1 | El grupo se llama `logistica_conductor.group_conductor` (el plan decía `logistica.group_conductor`). | Un id de otro módulo exige que ese módulo esté instalado. |
| T10-2 | El conductor es un usuario interno con ese grupo (implica `base.group_user`), no un usuario de portal. Las reglas de registro lo limitan a sus rutas, paradas, entregas y eventos; el personal de flota conserva acceso completo con una regla `[(1,'=',1)]`. | Evita las restricciones de ACL de usuarios de portal sobre flota y entregas. |
| T10-3 | Una ruta ajena y una inexistente responden igual (404 al ver, 403 al actuar). Cada acción corre en un savepoint. | No revelar datos y no dejar cambios a medias. |
| T11-1 | Una falla del servicio de rutas **no bloquea** la predicción: la consulta se guarda sin geometría. Una falla del modelo sí: mensaje «El modelo predictivo no está disponible» y no se crea consulta. | La predicción es el dato principal; la ruta es un complemento. |
| T11-2 | Las consultas son de solo inserción (`write` y `unlink` lanzan error). `origin_zone` se valida en código, no con NOT NULL. | Auditoría, y poder lanzar `ValidationError` con un mensaje claro. |
| T12-1 | La demostración vive en `seeds/data/*.json` y `seeds/seed.py` (no en `seeds/demo_data.py`, borrado en la Fase 1). La clave inicial de los conductores sale de `DEMO_CONDUCTOR_PASSWORD` en `.env`. | Sin datos de negocio ni credenciales en el código (F1-D10). |
| T12-2 | El seeder **alinea la bodega activa** de Odoo con la geocerca de Traccar (nombre y coordenadas del JSON). El esquema comprueba que la bodega caiga dentro de la geocerca. | La demostración mezclaba una bodega de Ambato con coordenadas de Bogotá. |
| T13-1 | `verify_flujo.py` recorre el checkout por HTTP real hasta el pago de prueba (la transacción de pago se crea por XML-RPC, como hace el módulo de checkout en sus pruebas), el portal del conductor por HTTP, y el resto por XML-RPC. Actúa sobre la base de desarrollo. | Es la prueba de aceptación de §13. |

## Defectos encontrados al ejecutar

1. **`_gps_snapshot` (entregas) buscaba el dispositivo por `traccar.device.vehicle_id`**, un campo inerte: todo evento salía con «GPS no disponible». Ahora usa `fleet.vehicle.traccar_device_id`. Prueba: `test_gps_se_adjunta_a_la_entrega_del_vehiculo`.
2. **Los asistentes (modelos transitorios) no tenían permisos.** Con un usuario normal fallaban por RPC y por la interfaz con «No group currently allows this operation». Las pruebas corrían como superusuario y no lo veían. Se añadieron los permisos y pruebas que usan cada asistente como gestor de flota. Lo detectaron los criterios 5 y 14 de `verify_flujo.py`.
3. **El mapa de monitoreo no mostraba vehículos a un usuario de «Flota / Usuario»** (regla de registro de Odoo). Ahora exige gestor.
4. **Una prueba de CSRF enviaba un cuerpo vacío**, que el cliente HTTP convierte en GET (405). Error de la prueba.
5. **Seguridad (pendientes del README):** «Probar Conexión» no tenía control de gestor y los errores podían guardar cabeceras de autorización. Corregidos, con pruebas.

## Cómo se verifica

| Qué | Comando |
|---|---|
| Pruebas de todos los módulos de logística (instala/actualiza y reinicia Odoo) | `powershell -ExecutionPolicy Bypass -File .\scripts\test_odoo.ps1` |
| Los 14 criterios de §13 | `python scripts/verify_flujo.py` (con `.env` cargado; ver `tests/README.md`) |
| Sin Docker | `python -m unittest tests.estatico.test_sin_datos_quemados seeds.tests.test_schema seeds.tests.test_simular -v` |
