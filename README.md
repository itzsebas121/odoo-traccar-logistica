# Sistema Inteligente de Rastreo y Analítica de Rutas

Proyecto integrador de **Odoo 16 Community**, **Traccar**, servicios ETL, PostgreSQL, analítica de datos e inteligencia artificial.

---

## 📌 Etapa 1: Infraestructura Base con Docker Compose

Esta etapa inicial implementa y valida el despliegue local y portable de **Odoo 16 Community** y **PostgreSQL 15**.

### Arquitectura de Servicios

- **db (`postgres:15`)**: Base de datos relacional para Odoo con comprobación de estado de salud (`healthcheck`). El puerto 5432 no se expone al host público para maximizar la seguridad.
- **odoo (`odoo:16.0`)**: Servidor ERP Odoo 16 Community, conectado a la base de datos interna mediante resolución DNS de Docker Compose. El puerto `8069` se publica exclusivamente en la interfaz local (`127.0.0.1:8069`) durante el desarrollo.

### Persistencia y Volúmenes

- `postgres_odoo_data`: Volumen gestionado por Docker para los datos de PostgreSQL (`/var/lib/postgresql/data`).
- `odoo_data`: Volumen gestionado por Docker para los adjuntos y sesiones de Odoo (`/var/lib/odoo`).
- `./odoo/addons`: Directorio montado como bind mount en `/mnt/extra-addons` para el desarrollo de módulos personalizados.

---

## 🚀 Requisitos Previos

- **Docker Desktop** (en Windows/macOS) con backend WSL2 / contenedores Linux, o **Docker Engine + Docker Compose v2** (en Ubuntu/Debian).
- Git con normalización de finales de línea (gestionado automáticamente vía `.gitattributes`).

---

## 🛠️ Instrucciones de Instalación y Despliegue

### 1. Clonar el repositorio

```bash
git clone <URL_DEL_REPOSITORIO>
cd odoo-traccar-logistica
```

### 2. Configurar las variables de entorno

Copie el archivo de plantilla `.env.example` para generar su `.env` local:

**En Linux / macOS / Git Bash:**
```bash
cp .env.example .env
```

**En Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Edite el archivo `.env` y asigne contraseñas seguras para su entorno local:
```env
ODOO_DB_PASSWORD=una_contrasena_segura_para_desarrollo
ODOO_ADMIN_PASSWORD=contrasena_maestra_para_gestionar_bd
```

> **Seguridad**: El archivo `.env` está expresamente excluido de Git mediante `.gitignore`. Nunca confirme contraseñas en archivos versionados.

### 3. Validar y levantar los contenedores

Valide la configuración de Docker Compose:
```bash
docker compose config
```

Inicie los servicios en segundo plano:
```bash
docker compose up -d
```

### 4. Verificar el estado de los servicios

```bash
docker compose ps
```

Deberá observar ambos servicios activos y el servicio de base de datos con estado `(healthy)`:
- `odoo-traccar-logistica-db-1`: `Up (healthy)`
- `odoo-traccar-logistica-odoo-1`: `Up`

Para consultar los registros en tiempo real:
```bash
docker compose logs -f
```

---

## 🌐 Acceso a la Interfaz Web de Odoo

Una vez que ambos contenedores estén en estado saludable, abra su navegador web en:

👉 [http://localhost:8069](http://localhost:8069)

En el primer inicio, Odoo mostrará el asistente de creación de base de datos (`/web/database/selector`):

1. **Master Password**: Ingrese la contraseña maestra de administración (definida o sugerida).
2. **Database Name**: Ingrese el nombre para la base de datos de desarrollo (ej. `odoo_logistica_dev`).
3. **Email / Contraseña**: Credenciales para el usuario administrador de Odoo.
4. **Country / Language**: Configure según su preferencia (ej. Spanish / Colombia).

---

## 🧩 Desarrollo de Módulos Personalizados

Los módulos desarrollados por el equipo se ubican en el directorio `./odoo/addons/`:

- `logistica_base`
- `logistica_traccar`
- `logistica_despacho`
- `logistica_conductor`
- `logistica_ecommerce`

Cada módulo debe contar con su estructura estándar (`__init__.py`, `__manifest__.py`, `models/`, `views/`). Al montarse en `/mnt/extra-addons`, Odoo los detectará tras activar el **Modo Desarrollador** y ejecutar **Actualizar lista de aplicaciones** desde la interfaz web.

---

## 🛑 Comandos Útiles de Mantenimiento

- **Detener los servicios (sin perder datos):**
  ```bash
  docker compose down
  ```
- **Reiniciar los servicios:**
  ```bash
  docker compose restart
  ```
- **Detener y eliminar contenedores y redes (conservando volúmenes de datos):**
  ```bash
  docker compose down
  ```
- **Inspeccionar registros de Odoo:**
  ```bash
  docker compose logs odoo --tail=50
  ```
- **Inspeccionar registros de PostgreSQL:**
  ```bash
  docker compose logs db --tail=50
  ```

