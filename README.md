# Odoo + Traccar Logística UTA

Sistema de gestión de entregas con Odoo 16, Traccar GPS, PostgreSQL, planificación de rutas y portal móvil para conductores.

## Servicios y puertos

| Servicio | URL | Puerto |
|---|---|---:|
| Odoo | http://localhost:8069 | 8069 |
| Traccar | http://localhost:8082 | 8082 |
| Routing | http://localhost:8001 | 8001 |
| PostgreSQL | interno en Docker | 5432 |
| Traccar GPS | conexión de dispositivos | 5055 |

El servicio `routing` se inicia con el perfil `analitica`.

## Requisitos

- Docker y Docker Compose
- Python 3
- Linux/macOS: Bash
- Windows: PowerShell

## Instalación inicial

1. Copiar la configuración:

```bash
cp .env.example .env
```

2. Editar `.env` y reemplazar los valores `CAMBIAR_*`.

3. Levantar el núcleo, crear la base, instalar módulos y cargar semillas:

```bash
./scripts/setup.sh
```

En Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Para incluir rutas, ML y BI:

```bash
./scripts/setup.sh --con-analitica
docker compose --profile analitica up -d
```

## Arranque manual

```bash
docker compose up -d db odoo traccar
docker compose --profile analitica up -d routing ml bi
```

Comprobar estado:

```bash
docker compose ps
curl http://localhost:8001/health
```

## Base de datos y restauración

Base Odoo principal: `logistica_dev`.

Restaurar una copia de PostgreSQL:

```bash
./scripts/restore.sh backups/odoo_logistica_YYYYMMDD_HHMMSS.dump backups/traccar_YYYYMMDD_HHMMSS.dump backups/filestore_YYYYMMDD_HHMMSS.tar.gz
```

Respaldar el entorno:

```bash
./scripts/backup.sh
```

Los snapshots de referencia están en `database/snapshot/`. Para una instalación limpia, se recomienda usar `scripts/setup.sh`, que crea la base e instala los módulos automáticamente.

## Semillas y datos de demostración

Los datos están en:

- `seeds/data/odoo.json`
- `seeds/data/traccar.json`
- `seeds/data/simulacion.json`

Ejecutar o repetir el sembrado:

```bash
env $(grep -v '^#' .env | grep '=' | xargs) python3 seeds/seed.py
```

El seeder es idempotente: no duplica conductores, vehículos, dispositivos ni pedidos existentes.

El escenario actual usa la sede UTA en Ambato y pedidos de prueba hacia La Manzana de Oro, Alobamba, Mocha, Viñas, Píllaro, Picaihua, Huachi Grande y Cevallos.

## Accesos y claves

Las claves de desarrollo se guardan únicamente en el archivo `.env` y no se versionan. El archivo de ejemplo indica qué valores deben configurarse para Odoo, Traccar, la integración y los conductores.

Usuarios del portal del conductor:

- `sebastipan109@gmail.com`
- `angelica.martinez@uta.local`
- `bryan.viteri@uta.local`
- `daniel.moyolema@uta.local`

Portal:

```text
http://localhost:8069/logistica/conductor
```

Tienda y selección de coordenadas del cliente:

```text
http://localhost:8069/shop
```

El cliente selecciona el punto en el mapa durante el checkout. Las coordenadas se guardan en el pedido y pasan a la entrega.

## Flujo de prueba

1. Entrar a Odoo como administrador.
2. Marcar las entregas como **Preparado para despacho**.
3. Ir a **Logística → Planificar despacho**.
4. Seleccionar vehículos y pulsar **Proponer rutas**.
5. Aprobar la ruta.
6. Entrar al portal con un conductor.
7. Confirmar carga, iniciar recorrido y registrar cada parada.
8. Simular posiciones GPS si se desea probar Traccar:

```bash
env $(grep -v '^#' .env | grep '=' | xargs) python3 seeds/simular.py
```

## Pruebas

Pruebas de semillas y escaneo estático:

```bash
python3 -m unittest seeds.tests.test_schema seeds.tests.test_simular tests.estatico.test_sin_datos_quemados -v
```

Pruebas de Odoo:

```bash
docker compose exec -T odoo odoo \
  --db_host=db --db_port=5432 \
  --db_user=odoo \
  -d logistica_dev --test-enable \
  --test-tags /logistica --stop-after-init \
  --http-port=8070 --log-level=test
```

## Detener y limpiar

Detener servicios conservando datos:

```bash
docker compose down
```

Eliminar también volúmenes y datos locales:

```bash
docker compose down -v
```

Este último comando borra las bases y requiere volver a ejecutar la instalación.

## Despliegue en Dokploy

Crear una aplicación Compose apuntando al repositorio GitHub y a la rama `main`. Dokploy debe usar `compose.yaml`. El servicio `routing` arranca por defecto porque Odoo lo necesita para proponer rutas.

Configurar como secretos las variables mínimas:

```text
ODOO_DB_PASSWORD
ODOO_ADMIN_PASSWORD
TRACCAR_DB_PASSWORD
TRACCAR_ADMIN_PASSWORD
TRACCAR_ADMIN_EMAIL
ODOO_URL
ODOO_DB
ODOO_USER
ODOO_PASSWORD
TRACCAR_URL
TRACCAR_INTERNAL_URL
INTEGRATION_TRACCAR_EMAIL
INTEGRATION_TRACCAR_PASSWORD
DEMO_CONDUCTOR_PASSWORD
```

Para una primera prueba sin dominio, usar la IP pública del servidor:

```text
ODOO_URL=http://IP_DEL_SERVIDOR:8069
TRACCAR_URL=http://IP_DEL_SERVIDOR:8082
TRACCAR_INTERNAL_URL=http://traccar:8082
TRACCAR_OSMAND_URL=http://IP_DEL_SERVIDOR:5055
```

Publicar únicamente estos puertos:

- `8069/TCP`: Odoo.
- `8082/TCP`: panel y API de Traccar.
- `5055/TCP`: dispositivos GPS.

No publicar `5432/TCP` de PostgreSQL. Mantener persistentes los volúmenes de PostgreSQL, Odoo y Traccar. Cuando exista dominio, configurar HTTPS y actualizar las URLs públicas.
