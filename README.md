# Sistema Inteligente de Rastreo y Analítica de Rutas

Proyecto universitario integrador que combina **Odoo 16 Community**, **Traccar GPS Server**, motor de optimización de rutas, procesos ETL, PostgreSQL, almacén dimensional (DWH), analítica de datos e inteligencia artificial predictiva.

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

## 🛠️ Guía Rápida de Despliegue

### 1. Clonar el Repositorio

```bash
git clone https://github.com/sebas/odoo-traccar-logistica.git
cd odoo-traccar-logistica
```

### 2. Configurar Variables de Entorno

Copie la plantilla de variables de entorno:

**En Linux / macOS / Git Bash:**
```bash
cp .env.example .env
```

**En Windows PowerShell:**
```powershell
Copy-Item .env.example .env
```

Edite `.env` con contraseñas seguras locales:
```env
ODOO_DB_PASSWORD=una_contrasena_segura_odoo
ODOO_ADMIN_PASSWORD=contrasena_maestra_odoo
TRACCAR_DB_USER=traccar
TRACCAR_DB_PASSWORD=una_contrasena_segura_traccar
TRACCAR_ADMIN_PASSWORD=clave_admin_traccar_web
```

> **Aviso de Seguridad**: `.env` está en `.gitignore` y nunca se sube a GitHub.

### 3. Levantar los Servicios con Docker Compose

```bash
docker compose up -d
```

Verifique que todos los contenedores estén activos y saludables:
```bash
docker compose ps
```

---

## 🌐 Accesos a las Plataformas

### 📌 ¿Cómo ingresar a Odoo 16?

> Al tener instalado el módulo de **eCommerce**, si navegas a `http://localhost:8069/` verás directamente la tienda pública. Para entrar al panel de administración del ERP debes usar la URL de login.

| Módulo / Interfaz | URL | Credenciales de Acceso | Descripción |
|---|---|---|---|
| **Odoo - Login Administrativo** | [http://localhost:8069/web/login](http://localhost:8069/web/login) | **Base de Datos:** `logistica_dev`<br>**Email:** `admin`<br>**Contraseña:** `admin` | Formulario para ingresar al backend del ERP. |
| **Odoo - Panel Backend ERP** | [http://localhost:8069/web](http://localhost:8069/web) | *(Requiere sesión iniciada)* | Acceso a Flota, Contactos, Ventas y Rastreo GPS. |
| **Odoo - Tienda eCommerce** | [http://localhost:8069/shop](http://localhost:8069/shop) | *Público (sin login)* | Catálogo de productos para compras sin registro obligatorio. |
| **Traccar - Consola Web y API** | [http://localhost:8082](http://localhost:8082) | **Usuario:** `admin@logistica.local`<br>**Contraseña:** la definida en `TRACCAR_ADMIN_PASSWORD` | Panel de monitoreo de dispositivos y gestión GPS. |
| **Receptor GPS OsmAnd** | `http://localhost:5055` | *Protocolo OsmAnd* | Puerto para envío de coordenadas desde Traccar Client. |

---

## 🧭 Navegación en Odoo y Uso del Módulo de Rastreo

Una vez autenticado en [http://localhost:8069/web/login](http://localhost:8069/web/login):

1. **Acceder a Flota**: En el menú principal de aplicaciones (icono de 9 puntos arriba a la izquierda), selecciona **Flota** (Fleet).
2. **Servidores Traccar**: En la barra superior de Flota, abre el menú **Rastreo Traccar > Servidores Traccar**:
   - Verás el servidor configurado (`http://traccar:8082`).
   - Puedes usar el botón **"Probar Conexión"** para verificar la comunicación en tiempo real.
   - El botón **"Sincronizar Dispositivos"** consulta la API de Traccar e importa automáticamente los dispositivos GPS registrados.
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
| **Poblar datos de prueba (Seeds)** | `cat seeds/demo_data.py \| docker compose exec -T odoo python3` | `Get-Content seeds/demo_data.py -Raw \| docker compose exec -T odoo python3` |
