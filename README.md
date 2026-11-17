# Odoo + Traccar Logística UTA

Sistema de gestión de entregas con Odoo 16, Traccar GPS, PostgreSQL, planificación de rutas, portal móvil para conductores y **Bitácora**, el panel del administrador con un asistente de IA y la gestión de la base de datos.

## Servicios y puertos

| Servicio | Para qué | URL local | Puerto |
|---|---|---|---:|
| `odoo` | ERP: ventas, facturas, entregas, despacho, tienda y portal del conductor | http://localhost:8069 | 8069 |
| `traccar` | Panel y API del GPS | http://localhost:8082 | 8082 |
| `traccar` | Recepción de posiciones de los dispositivos (OsmAnd) | — | 5055 |
| `agente` | **Bitácora**: asistente del administrador y gestión de la base de datos | http://127.0.0.1:8003 | 8003 |
| `routing` | Optimización de rutas (lo usa Odoo) | http://127.0.0.1:8001/health | 8001 |
| `db` | PostgreSQL 15 (bases `logistica_dev` y `traccar`) | solo red interna | — |
| `odoo-init`, `seed` | Tareas de un solo uso: instalar módulos y cargar datos de demostración | — | — |

Opcionales con perfiles: `ml` y `bi` (`--profile analitica`) y `etl` (`--profile etl`).

## Requisitos

- Docker Desktop (Windows/macOS) o Docker Engine con Compose v2 (Linux).
- Python 3.10 o superior (para los scripts de semillas en el host).
- Git, y Bash (Linux/macOS) o PowerShell (Windows).
- Una clave de la API de OpenAI ([platform.openai.com](https://platform.openai.com)) si se quiere usar el asistente.

## Levantar el proyecto en local (paso a paso)

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio> odoo-traccar-logistica
cd odoo-traccar-logistica
```

### 2. Crear el archivo `.env`

```bash
cp .env.example .env          # Windows: Copy-Item .env.example .env
```

Reemplace **todos** los valores `CAMBIAR_*` por contraseñas propias. Para generarlas:

```bash
openssl rand -hex 24          # Windows: python -c "import secrets; print(secrets.token_hex(24))"
```

Valores recomendados para trabajar en local:

```env
ODOO_PROXY_MODE=False
ODOO_WORKERS=0
AGENTE_COOKIE_SEGURA=false
ODOO_URL=http://localhost:8069
ODOO_DB=logistica_dev
ODOO_USER=admin
TRACCAR_URL=http://localhost:8082
TRACCAR_INTERNAL_URL=http://traccar:8082
TRACCAR_ADMIN_EMAIL=admin@logistica.local
INTEGRATION_TRACCAR_EMAIL=integracion@logistica.local
TRACCAR_OSMAND_URL=http://127.0.0.1:5055
OPENAI_API_KEY=sk-...                   # opcional: sin ella el chat avisa que falta
AGENTE_SESSION_SECRET=<openssl rand -hex 32>
```

`ODOO_PASSWORD` puede quedar vacía: se usa `ODOO_ADMIN_PASSWORD`.

### 3. Instalar y arrancar

Un solo comando levanta los servicios, crea la base, instala los módulos y carga los datos de demostración:

```bash
./scripts/setup.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

La primera vez tarda varios minutos (descarga de imágenes e instalación de módulos). El script no arranca si `.env` todavía tiene valores `CAMBIAR_*`.

Para incluir también ML y BI: `./scripts/setup.sh --con-analitica`.

### 4. Entrar

| Dónde | URL | Usuario |
|---|---|---|
| Odoo (ERP) | http://localhost:8069 | `admin` / `ODOO_ADMIN_PASSWORD` |
| Bitácora (asistente y base de datos) | http://127.0.0.1:8003 | el mismo usuario administrador de Odoo |
| Traccar | http://localhost:8082 | `TRACCAR_ADMIN_EMAIL` / `TRACCAR_ADMIN_PASSWORD` |
| Portal del conductor | http://localhost:8069/logistica/conductor | conductores de las semillas / `DEMO_CONDUCTOR_PASSWORD` |
| Tienda | http://localhost:8069/shop | público |

Conductores de las semillas: `sebastipan109@gmail.com`, `angelica.martinez@uta.local`, `bryan.viteri@uta.local`, `daniel.moyolema@uta.local`.

### 5. Uso diario

```bash
docker compose up -d          # arrancar
docker compose ps             # ver estado (todo debe estar "healthy"; odoo-init y seed terminan con "Exited (0)")
docker compose logs -f odoo   # ver registros de un servicio
docker compose down           # detener conservando los datos
```

`docker compose down -v` **borra** las bases y los respaldos guardados en el servidor; después hay que volver a instalar.

Para actualizar módulos de Odoo después de cambiar su código:

```bash
./scripts/update_modules.sh logistica_base,logistica_traccar    # detiene Odoo, actualiza y lo levanta
```

## Bitácora: panel del administrador (`services/agente`)

Interfaz React + shadcn/ui servida por el mismo servicio FastAPI que su API, así que navegador y API comparten origen (sin CORS).

**Autenticación:** se hace contra Odoo. Bitácora envía usuario y contraseña a Odoo (XML-RPC `authenticate`) y solo deja entrar a miembros del grupo *Administración / Ajustes* (`base.group_system`). La contraseña no se guarda: tras el login, Bitácora emite su propia cookie de sesión firmada (`HttpOnly`, `SameSite=Lax`, `Secure` con HTTPS) que dura `AGENTE_SESION_HORAS` (8 h por defecto).

### Asistente

- Chat con GPT de OpenAI (`gpt-6.1-sol` por defecto, configurable con `AGENTE_MODELO`) por la Responses API, que responde con datos de Odoo: ranking de clientes, ficha de cliente (consumo), productos más vendidos, facturas (pendientes, pagadas, vencidas), evolución de ventas y estado de la operación.
- Solo lectura: el modelo elige entre consultas predefinidas con parámetros validados; no escribe SQL.
- Privacidad: las preguntas y los resultados de las consultas se envían a OpenAI para generar la respuesta. Se usa `store=False` (OpenAI no guarda la conversación en su plataforma; el historial vive en el servicio).
- Conversaciones en memoria del servicio durante 24 h (se pierden al reiniciarlo).

### Base de datos

Sección **Base** del menú. Cada operación pide la **contraseña maestra de Odoo** (`ODOO_MASTER_PASSWORD`) además de la sesión de administrador.

- **Crear respaldo:**
  - Odoo: ZIP con el mismo formato que el gestor de bases de Odoo (`dump.sql` + adjuntos del filestore + `manifest.json`); sirve para otra instalación de Odoo 16.
  - Traccar: `.dump` de PostgreSQL.
- **Descargar y borrar** los respaldos guardados en el servidor (volumen `respaldos`).
- **Cargar y restaurar** desde un archivo subido (Odoo: `.zip` de Odoo o `.dump`; Traccar: `.dump`) o desde un respaldo guardado. Hay que escribir `RESTAURAR` para confirmar.
  - Antes de restaurar se crea un respaldo automático de lo que hay.
  - El archivo se restaura en una base temporal y se comprueba. Solo si todo va bien se intercambia con la actual, que queda como `<base>_anterior` (solo la última).
  - Si algo falla antes del intercambio, la base actual no se toca.
  - **Después de restaurar hay que reiniciar el servicio** `odoo` o `traccar` (Dokploy: Restart del servicio; local: `docker compose restart odoo`).

Límite de subida: `AGENTE_MAX_SUBIDA_MB` (2048 por defecto).

Respaldos por línea de comandos (alternativa, desde el host): `./scripts/backup.sh` y `./scripts/restore.sh` (ver los scripts).

### Desarrollo de la interfaz

```bash
cd services/agente/web
npm install
npm run dev        # http://localhost:5173; la API va por proxy a 127.0.0.1:8003
```

Pruebas del backend:

```bash
cd services/agente
pip install -r requirements-dev.txt
pytest
```

## Datos de demostración: «Mercado Andino Ambato»

Una tienda general con entrega a domicilio (comida, bebidas, tecnología, celulares, accesorios, hogar y cuidado
personal) que despacha desde la
**Sede (FISEI, campus Huachi)** a Ambato y alrededores, **hasta Mocha** (radio de cobertura de 19,5 km).

| Qué | Detalle |
|---|---|
| Empresa | Mercado Andino Ambato, en **USD**, plan contable genérico, IVA 0 % (alimentos frescos) y 15 % (el resto) |
| Catálogo | 49 productos en 7 categorías: Comida (12), Bebidas (7, incluye cerveza, vino y ron), Tecnología (7), Celulares (4), Accesorios (7), Hogar (7) y Cuidado personal (5). Fotos reales de Wikimedia Commons (créditos en `seeds/data/imagenes/CREDITOS.md`) y precios de mercado minorista |
| Clientes | 55 (hogares, restaurantes, cafeterías, oficinas, hostal, centro infantil) en **calles reales** de OpenStreetMap; nombres, teléfonos y correos ficticios (`example.com`). Además de su compra habitual, a veces suman un celular, un accesorio o algo para la casa |
| Historial | ~3 meses que terminan ayer: unos 310 pedidos, ~80 rutas cerradas con sus horarios y GPS, entregas fallidas y reprogramadas. **Venta directa**: cada pedido se factura y se paga al hacerlo; no hay crédito ni cuentas por cobrar |
| Hoy | 14 pedidos pagados y listos para despachar, y 1 pedido telefónico sin ubicación (queda en cotización) |

Archivos: `seeds/data/mercado.json` (empresa, clientes, perfiles de compra, parámetros del historial),
`seeds/data/odoo.json` (productos, flota, conductores), `seeds/data/simulacion.json` (pedidos de hoy y recorridos GPS) y
`seeds/data/traccar.json`. El módulo `logistica_demo` hace la carga en el servidor; `seeds/seed.py` lo instala si
falta y lo invoca.

El servicio `seed` lo ejecuta en cada `docker compose up`. Es idempotente: el historial se carga una sola vez y los
productos, clientes y pedidos se actualizan sin duplicarse. Si cambia `version_datos` en `mercado.json` (otro
catálogo), el historial y los pedidos de demostración se borran y se regeneran; los productos que salen del catálogo
se archivan. Para repetirlo desde el host:

```bash
env $(grep -v '^#' .env | grep '=' | xargs) python3 seeds/seed.py
```

`SEED_HISTORIAL=false` omite el historial (por ejemplo, en una instalación real que solo quiere el catálogo).

## Flujo del administrador (despacho)

1. **El cliente compra** en `/shop` y marca su punto en el mapa (el círculo muestra la cobertura). Los pedidos
   creados en Odoo (por teléfono) también exigen ubicación antes de confirmarse.
2. **Al confirmarse**, el pedido queda **«Por despachar»** sin pasos manuales. Si en *Logística → Configuración* se
   activa «Los pedidos se preparan en bodega», hay que marcarlos preparados (también en lote desde la lista).
3. **Logística → Despachar**: el resumen dice cuántas entregas salen y **cuáles no y por qué** (sin ubicación,
   fuera de cobertura, confirmadas después de la hora de corte). *Proponer rutas* las arma con los vehículos disponibles.
4. **Rutas de despacho**: seleccionar las propuestas y pulsar **Aprobar rutas** (una sola vez para todas).
5. **Conductor** (portal `/logistica/conductor`): **Salir a ruta** (un solo botón), y en cada parada *Entregado* o
   *No entregado* con motivo. **La ruta se cierra sola** con la última parada.
6. **Lo que falla vuelve solo a «Por despachar»** para el siguiente despacho, hasta 2 intentos. Con «Dirección
   incorrecta» o intentos agotados pasa a **«Requiere atención»** (filtro en *Entregas*).

Estados que ve el administrador: *Por despachar · En ruta · Entregado · Requiere atención · Devuelto a bodega*
(el estado detallado sigue disponible para auditoría).

Simular posiciones GPS de los vehículos:

```bash
env $(grep -v '^#' .env | grep '=' | xargs) python3 seeds/simular.py
```

## Pruebas

```bash
# Semillas y escaneo estático (sin Docker)
python3 -m unittest seeds.tests.test_schema seeds.tests.test_simular tests.estatico.test_sin_datos_quemados -v

# Módulos de Odoo (con el stack levantado)
docker compose stop odoo
docker compose run --rm --no-deps -T -e ODOO_WORKERS=0 odoo odoo -d logistica_dev \
  --test-enable --test-tags /logistica_traccar,/logistica_conductor,/logistica_checkout \
  --stop-after-init --http-port=8070
docker compose up -d odoo

# Servicio de rutas
docker compose run --rm --no-deps routing python -m pytest -q
```

## Despliegue en Dokploy (paso a paso)

1. **Crear la aplicación:** en Dokploy, *Create Service → Compose*, apuntando a este repositorio y a la rama que quiera desplegar. Archivo: `compose.yaml`.
2. **Variables** (*Environment*): las mismas de `.env`, con contraseñas **nuevas** de producción:

   ```env
   ODOO_DB_PASSWORD=...            ODOO_ADMIN_PASSWORD=...        ODOO_MASTER_PASSWORD=...
   TRACCAR_DB_PASSWORD=...         TRACCAR_ADMIN_PASSWORD=...     INTEGRATION_TRACCAR_PASSWORD=...
   DEMO_CONDUCTOR_PASSWORD=...     AGENTE_SESSION_SECRET=...      OPENAI_API_KEY=...
   ODOO_PROXY_MODE=True            ODOO_WORKERS=2                 AGENTE_COOKIE_SEGURA=true
   AGENTE_FORWARDED_ALLOW_IPS=*
   ODOO_URL=https://odoo.sebasdev.shop        TRACCAR_URL=https://traccar.sebasdev.shop
   TRACCAR_INTERNAL_URL=http://traccar:8082   ODOO_DB=logistica_dev   ODOO_USER=admin
   TRACCAR_ADMIN_EMAIL=<correo real>          INTEGRATION_TRACCAR_EMAIL=integracion@sebasdev.shop
   ```

3. **Dominios** (*Domains*), todos con HTTPS:

   | Dominio | Ruta | Servicio | Puerto |
   |---|---|---|---|
   | `odoo.sebasdev.shop` | `/` | `odoo` | 8069 |
   | `odoo.sebasdev.shop` | `/websocket` | `odoo` | 8072 |
   | `traccar.sebasdev.shop` | `/` | `traccar` | 8082 |
   | `asistente.sebasdev.shop` (ejemplo) | `/` | `agente` | 8000 |

   Si no puede crear la regla de `/websocket`, use `ODOO_WORKERS=0`.

4. **Puertos y firewall:** abra solo 80/443 (Traefik) y **5055/TCP** (GPS). No publique 5432 (PostgreSQL) ni 8069 directamente. Si el dominio de Traccar está detrás del proxy de Cloudflare, el 5055 no pasa: use un registro «DNS only» para los dispositivos.
5. **Deploy.** El primer despliegue instala los módulos (varios minutos). Los siguientes no reinstalan nada.
6. **GPS:** en la app Traccar Client, servidor `http://traccar.sebasdev.shop:5055` e identificador igual al `uniqueId` del vehículo en `seeds/data/odoo.json`.

### Problemas comunes

- **`password authentication failed for user "odoo"` o `"traccar"`** (`odoo-init` falla o `traccar` queda *unhealthy*): la contraseña de PostgreSQL se fija solo al crear el volumen; cambiarla después en las variables no la actualiza. Vuelva a poner la anterior o cámbiela dentro de la base desde la terminal del contenedor `db`:

  ```bash
  psql -U odoo -d postgres -c "ALTER ROLE odoo WITH PASSWORD '<ODOO_DB_PASSWORD>';"
  psql -U odoo -d postgres -c "ALTER ROLE traccar WITH PASSWORD '<TRACCAR_DB_PASSWORD>';"
  ```

- **`Temporary failure in name resolution` hacia `traccar` en los registros de Odoo:** Traccar no está corriendo; revise los registros del contenedor `traccar` (casi siempre es el punto anterior).
- **Falta una variable obligatoria** (`Configura ...`): el despliegue se detiene a propósito; agréguela en *Environment*.

## Configuración de Odoo en producción

El servicio `odoo` genera su configuración al arrancar ([odoo/init/odoo-entrypoint.sh](odoo/init/odoo-entrypoint.sh)):

- Gestor de bases web deshabilitado (`list_db = False`), una sola base (`dbfilter`) y contraseña maestra `ODOO_MASTER_PASSWORD` (guardada con hash). Los respaldos se gestionan desde Bitácora.
- `odoo-init` instala los módulos solo en una base nueva y aplica `ODOO_ADMIN_PASSWORD` al usuario `admin`.
- En cada arranque, `odoo-init` **actualiza solo los módulos `logistica_*` cuya versión cambió** en su `__manifest__.py`,
  y Odoo se reinicia solo al terminar para cargar el código nuevo. Al modificar un módulo, suba su versión.
- `ODOO_PROXY_MODE=True` solo detrás de Traefik/nginx: Odoo ve la IP real del cliente, el esquema `https` y el host público. Con Odoo publicado directamente en un puerto, déjelo en `False`.
- `ODOO_WORKERS` (2 por defecto): con workers > 0, `/websocket` debe ir a `odoo:8072`.

## Servicios externos de mapas

- Leaflet se sirve desde Odoo (`logistica_base/static/lib/leaflet`), sin depender de unpkg.
- `ROUTING_OSRM_URL` apunta por defecto al servidor **de demostración** de OSRM (~1 petición/s, no apto para producción). El servicio de rutas guarda las rutas 10 min y usa una sola llamada por mapa; en producción conviene un OSRM propio o un proveedor contratado. Si falla, se dibuja la línea recta.
- Los mosaicos de `tile.openstreetmap.org` tampoco admiten uso comercial intensivo: en producción, use un proveedor de mosaicos.
