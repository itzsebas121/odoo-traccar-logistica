# Decisiones de Fase 1

## Tarea 2: herramientas de healthcheck (paso 1, verificado 2026-11-06)

| Servicio | Herramienta disponible | Resultado | Decision |
|---|---|---|---|
| traccar | `wget` (`/usr/bin/wget`); `curl` ausente | `command -v` solo devuelve wget | healthcheck con `wget -q -O /dev/null` |
| odoo | `python3` con `urllib.request` | `import urllib.request` correcto | healthcheck con `python3 -c` |

Rutas probadas sin credenciales:
- `http://127.0.0.1:8082/api/server` (traccar): HTTP 200 sin autenticacion. No hace falta ruta alternativa.
- `http://127.0.0.1:8069/web/login` (odoo): HTTP 200.

## Tarea 2: healthchecks en compose.yaml

- odoo: `python3` sobre `http://127.0.0.1:8069/web/login`.
- traccar: `wget` sobre `http://127.0.0.1:8082/api/server`.
- Ambos: interval 10s, timeout 5s, retries 10, start_period 60s.

## Tarea 2: modulos que instala o actualiza el script

Lista de 11 modulos. Se amplio la lista del script anterior con `logistica_entregas` y `logistica_checkout`, porque ambos estan en `odoo/addons`, ya estaban instalados en la base de desarrollo y `logistica_checkout` depende de `logistica_entregas`.

## Tarea 2: paso de seeds

`seeds/seed.py` todavia no existe (Tarea 3). Mientras no exista, el paso 5 imprime un aviso y no ejecuta nada:
- Windows: `AVISO: seeds\seed.py no existe todavia (pendiente: Tarea 3 del plan). Se omite el sembrado.`
- Linux: `AVISO: seeds/seed.py no existe todavia (pendiente: Tarea 3 del plan). Se omite el sembrado.`

## Tarea 4: causa del duplicate key en POST /api/users (verificado 2026-11-06)

Evidencia del fallo (`docker compose logs db`):

```
2026-11-06 14:16:51.740 UTC [40] ERROR:  duplicate key value violates unique constraint "tc_users_pkey"
2026-11-06 14:16:51.740 UTC [40] DETAIL:  Key (id)=(1) already exists.
2026-11-06 14:16:51.740 UTC [40] STATEMENT:  INSERT INTO tc_users(temporary, poiLayer, ..., deviceLimit) VALUES (...) RETURNING *
```

La sentencia no incluye la columna `id`: el valor sale del default de identidad de `tc_users.id` (secuencia `tc_users_id_seq`). La secuencia devolvio 1 mientras la fila admin (id=1) ya existia.

Causa: la secuencia estaba desincronizada respecto a los datos. Antes del fallo debia estar en su estado inicial (`last_value=1, is_called=false`), sin avanzar pese a existir la fila id=1; esto se infiere de que `nextval` devolvio 1 (no se registro el estado previo). El primer INSERT sin id tomo el 1 y colisiono. El fallo consume el valor, por eso la secuencia quedo en `last_value=1, is_called=true`, el estado que parecia correcto. Los INSERT siguientes reciben 2, 3, ...

Demostracion (tabla temporal en una sesion psql; no toca `tc_users`):

| Paso | Resultado |
|---|---|
| INSERT con id explicito 1 | secuencia en (1, false) |
| INSERT sin id | ERROR duplicate key, Key (id)=(1) |
| secuencia tras el fallo | (1, true) |
| siguiente INSERT sin id | id 2 |

Origen de la desincronizacion: no determinado. Los INSERT correctos no quedan en el log de Postgres, y el repositorio no inserta en `tc_users` (ni Liquibase ni scripts). El reinicio sin apagado limpio de la base a las 14:15:33 no lo explica: la recuperacion de PostgreSQL no retrocede secuencias. Hipotesis no comprobada: una insercion manual con id explicito o una restauracion que no restauro la secuencia.

Pruebas de la API con la secuencia ya sana (todas con HTTP 200):

| Variante | Cuerpo | Resultado |
|---|---|---|
| a | name, email, password | 200 |
| b | + readonly=true | 200 |
| c | + administrator=false | 200 |
| d | + id=0 | 200 |
| e | + id=null | 200 |
| f | readonly=true, administrator=false | 200 |
| g | + id=1 | 200; Traccar ignora el id del cuerpo y asigna 8 |

Ninguna variante reproduce el error: no es un fallo de la API. Con la secuencia sana, POST /api/users funciona.

## Tarea 4: workaround aplicado (resincronizar la secuencia, solo hacia adelante)

```sql
SELECT setval('tc_users_id_seq', GREATEST((SELECT max(id) FROM tc_users), (SELECT last_value FROM tc_users_id_seq)), true);
```

Aplicado en la base de desarrollo tras las pruebas: antes (9, true), despues (9, true); no cambio nada porque la secuencia ya estaba por encima del id maximo. Usar esta sentencia si POST /api/users vuelve a dar duplicate key en `tc_users_pkey` tras restaurar la base de Traccar. No se anadio al setup (`scripts/setup.*`), porque esos ficheros estan fuera de la lista de la Tarea 4; queda como decision pendiente.

## Tarea 4: usuario de integracion en Traccar

- Correo: `integracion@logistica.local` (en `.env`; el brief no fijaba valor). Contrasena: `INTEGRATION_TRACCAR_PASSWORD` de `.env` (no se documenta aqui).
- Traccar: usuario id 9, `readonly=t`, `administrator=f`.
- Permisos sobre dispositivos: los tres (`GPS-ABC-1234`, `GPS-DEF-5678`, `GPS-GHI-9012`) mediante `POST /api/permissions` (204). Sin ese permiso, `GET /api/positions?deviceId=` devuelve 400 "Device access denied".
- `seeds/seed.py`, paso `_sembrar_usuario_integracion`: clave natural email; crea el usuario, corrige perfil y contrasena si difieren, y vincula los dispositivos.
- `traccar.server` de Odoo: `username` = correo de integracion y `password` = `INTEGRATION_TRACCAR_PASSWORD` (comparado, no mostrado). Ya no usa las credenciales de admin.

Permisos verificados con el usuario de integracion:

| # | Peticion | Estado | Nota |
|---|---|---|---|
| 1 | `GET /api/devices` | 200 | lista los 3 dispositivos |
| 2 | `GET /api/positions?deviceId=4` | 200 | dispositivo vinculado |
| 3 | `GET /api/reports/route?deviceId=4&from=...&to=...` (`Accept: application/json`) | 200 | |
| 4 | `POST /api/devices` (name `probe-denied-check`) | 400 | rechazado: `SecurityException: Write access denied`. El brief esperaba 401 o 403 |
| 5 | `GET /api/users` | 200 | `[]`: no ve la fila admin |

Controles adicionales (probes): `GET /api/positions` de un dispositivo sin vinculo devuelve 400 "Device access denied"; una contrasena incorrecta devuelve 401.

Odoo (XML-RPC): `action_test_connection` devuelve exito; `action_sync_devices` (GET /api/devices autenticado) deja `state=connected` sin error. Nota: `action_test_connection` llama a `GET /api/server`, que Traccar no protege; no comprueba la clave. La prueba real de credenciales es la sincronizacion autenticada.

Seeder: la primera ejecucion creo el usuario y sus 3 permisos y actualizo `traccar.server`; la segunda y la tercera no crearon ni actualizaron nada (24 omitidos). Prueba de rotacion: con una clave temporal, el seeder la aplico (200 con la nueva, 401 con la de `.env`); la ejecucion normal restauro la de `.env` (200).

## Tarea 4: limpieza de probes

- Creados 7 usuarios `probe-a` a `probe-g` (ids 2 a 8) con POST /api/users; todos borrados (DELETE, 204 cada uno).
- Dispositivos `probe-*`: ninguno quedo creado (los dos intentos de POST /api/devices fueron rechazados).
- Verificado en la base: 0 filas `probe-*` en `tc_users` y en `tc_devices`. Archivo temporal de contrasenas de prueba borrado.

## Tarea 4: desviaciones

1. Correo del usuario de integracion: `integracion@logistica.local` (el brief no lo fijaba).
2. El seeder vincula el usuario a los dispositivos. El texto del brief no lo pedia, pero el paso 4 (`GET /api/positions` con 200) no es posible sin ese vinculo.
3. El rechazo de escritura devuelve 400, no 401 ni 403: en esta imagen de Traccar, la denegacion de acceso es un `SecurityException` que responde 400.
4. El esquema exige exactamente un usuario de integracion con `readonly=true` y `administrator=false`. Las dos pruebas nuevas de `test_schema.py` se escribieron junto con la implementacion, no con una ejecucion en rojo previa.
5. Si la clave del usuario existente no se acepta (401), el seeder la actualiza por PUT. Si el perfil difiere, tambien corrige el perfil.
6. `scripts/verify_integration.py` no se toco (su borrado sigue pendiente de aprobacion).

## Tarea 7: cron y boton manual (2026-11-07)

- `ir.cron` `logistica_traccar.ir_cron_traccar_sincronizar`: activo, cada 1 minuto, `numbercall = -1`, `doall = False`, codigo `model.cron_sincronizar()`.
- `user_id` no se escribe en el XML. Al cargar los datos del modulo el entorno es el superusuario, asi que el cron queda en uid 1. `cron_sincronizar` rechaza a cualquier otro usuario que no sea gestor de flota.
- `noupdate="1"`: un `-u logistica_traccar` no pisa el intervalo si alguien lo cambia en Ajustes.
- El boton «Sincronizar ahora» de la ficha del servidor llama a `action_sincronizar_ahora` y solo lo ve `fleet.fleet_group_manager`. No llama a `sincronizar_todo` (privado desde la tarea 6).
- `logistica.traccar_poll_minutes` no se redefinió. Ya vale `1` en `odoo/addons/logistica_base/data/logistica_config_data.xml`. El cron no consulta ese parametro en cada vuelta: `interval_number` es la agenda de Odoo. Cambiar el parametro no mueve el cron. Queda asi a proposito, para no tener dos sitios escribiendo la misma clave ni un cron que se reescriba solo.

## Tarea 8: simulador OsmAnd (2026-11-07, verificado en vivo)

- `seeds/simular.py` lee `seeds/data/simulacion.json` y hace `GET {TRACCAR_OSMAND_URL}/?id=&lat=&lon=&speed=&timestamp=`. `speed` va en nudos, como ya convierte el conector de Odoo. `timestamp` va en segundos unix, no en milisegundos.
- `TRACCAR_OSMAND_URL` no tiene valor por defecto. `SIM_INTERVALO_S` vacia significa 0.
- La ruta de `GPS-ABC-1234` tiene dos puntos: el primero a ~1,1 km al norte del circulo `Bodega central` (radio 300 m), a 10 nudos; el segundo en el centro del circulo, a 40 nudos. Verificado en vivo contra Traccar 6.x: el segundo punto genera `deviceOverspeed` (atributos `speed` 40.0 y `speedLimit` 30.0) y `geofenceEnter` (geocerca `Bodega central`), ambos en la misma marca de tiempo. El `speedLimit` va en **nudos**: en `GPS-GHI-9012` una posicion de 20 nudos (37 km/h) con limite 30 no genera exceso; si fuera km/h (30 km/h = 16,2 nudos) lo generaria. El valor 30 queda como definitivo para la demostracion.
- La consulta `GET /api/reports/events?deviceId=&from=&to=` con `Accept: application/json` y sin filtro `type` devuelve ambos eventos. El filtro con `type` repetido sigue sin probarse: el conector no lo necesita si pide todos los tipos y filtra en Odoo.
- Pruebas: `python -m unittest seeds.tests.test_simular seeds.tests.test_schema -v` → 13 OK. No abren red.
- `schema.cargar()` ahora exige `rutas`. `seeds/seed.py` lo llama, asi que un JSON de simulacion sin rutas deja de sembrar. Es intencional: el mismo archivo alimenta al seeder y al simulador.

## Tarea 9: escaneo estatico y E2E (2026-11-07)

- El escaneo vive en `tests/estatico/escaneo.py`. Excluye `seeds/data/`, `.env*`, `docs/`, `backups/` y el indice local `.codegraph/`.
- Tokens: `uniqueId`, `ref`, `marca`, `modelo`, `cliente` y el `name` de una geocerca (el objeto que tiene `area`). No se buscan placas ni nombres de persona: `ABC-1234` y `Carlos` ya estan en las fixtures de ETL y BI, de la fase anterior. Buscarlos dejaria el escaneo en rojo por codigo que no es de esta fase.
- Un literal `password` de 8 caracteres o mas cuenta solo fuera de `tests/`. Dentro de las pruebas hay contraseñas ficticias a proposito (por ejemplo, un caracter raro en el DSN del ETL).
- `scripts/verify_integration.py` es la unica excepcion. El test `test_la_excepcion_conocida_sigue_teniendo_datos_quemados` falla el dia que ese archivo deje de tener datos quemados, para obligar a quitar la excepcion. No se borro el archivo: sigue pendiente de aprobacion.
- El E2E (`tests/e2e/test_flujo.py`) no se ejecuto contra el stack: faltan las variables. Si faltan, las pruebas se omiten. La sincronizacion usa `action_sincronizar_ahora`. Reiniciar `traccar` u `odoo` exige `E2E_REINICIO=1`.
- Como la ruta del simulador repite los mismos timestamps, el reinicio comprueba que el conteo de posiciones no baja. No exige un lote nuevo con otros timestamps: el JSON no tiene un segundo lote. (Reemplazado el 2026-11-07: ver más abajo, el simulador ya desplaza los timestamps.)

### Tarea 9: corrida en vivo del E2E (2026-11-07) y tres defectos que encontró

Con el stack vivo y `.env` cargado, `python -m unittest tests.e2e.test_flujo -v` pasa 3 pruebas (seed idempotente, posición en Odoo con el vehículo correcto, eventos `deviceOverspeed` y `geofenceEnter` en Odoo). Con `E2E_REINICIO=1` pasan también `test_reinicio_traccar_sin_perdidas` y `test_reinicio_odoo_sin_perdidas`: 5 OK en 45 s (corrida de la usuaria en su consola, que tiene `docker`). Sin esa variable los reinicios se omiten. La primera corrida falló y destapó tres defectos reales:

1. **`python seeds/simular.py` no arrancaba** (`No module named 'seeds'`). `seed.py` se ejecuta como script y `simular.py` solo funcionaba como paquete. Ahora `simular.py` prueba `from seeds import schema` y, si falla, `import schema`. Funciona de las dos formas.
2. **Odoo nunca veía las posiciones simuladas.** Un dispositivo sin watermark se sincroniza desde su `create_date` (hoy), y `simulacion.json` traía timestamps fijos de 2025-11-07, fuera de la ventana. El simulador ahora desplaza los timestamps para que el último punto sea «ahora» y conserva el espacio entre puntos. Cada corrida genera posiciones nuevas, lo que además permite probar los reinicios con lotes nuevos. Prueba: `test_timestamps_se_desplazan_a_ahora_conservando_el_espacio`.
3. **Odoo no recibía `geofenceEnter` ni `geofenceExit`.** Traccar oculta los eventos de geocerca a quien no tiene permiso sobre ella, y el usuario de integración solo tenía permiso sobre dispositivos. Comprobado con sus credenciales: `GET /api/geofences` devolvía `[]` y los eventos solo traían `deviceOverspeed`. `seeds/seed.py` ahora otorga también el permiso `userId`+`geofenceId` (idempotente: la segunda corrida no crea nada).

Dato extra: la consulta de eventos con el parámetro `type` repetido (`type=a&type=b`) funciona en Traccar y es la que usa el conector. Queda cerrado ese pendiente de la Tarea 8.
