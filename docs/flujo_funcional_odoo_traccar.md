# ESPECIFICACIÓN FUNCIONAL — SISTEMA INTELIGENTE DE RASTREO Y ANALÍTICA DE RUTAS

**Proyecto:** Integración de Odoo 16 + Traccar  
**Tipo de documento:** Definición funcional y flujo de trabajo  
**Versión:** 1.0 — propuesta para revisión  
**Estado:** Análisis y diseño; **no representa funcionalidades ya implementadas**

> **Alcance de este documento:** qué hará cada sistema y módulo, qué verán los usuarios, qué campos manejarán, cómo se comunicarán Odoo y Traccar, y cómo se conectará la operación con la analítica y la IA. **No se incluyen infraestructura, contenedores, servidores ni despliegue.**

---

## 1. Objetivo del sistema

Diseñar una solución de distribución de productos en la que los clientes puedan realizar pedidos en una tienda pública de Odoo, seleccionar su punto de entrega en un mapa y consultar el estado de sus compras; Odoo administrará productos, clientes, pedidos, vehículos, conductores, asignaciones, despachos y confirmaciones de entrega. Traccar registrará las ubicaciones GPS de los vehículos y proporcionará los recorridos para el seguimiento operativo y el análisis histórico.

Los vehículos parten de **una misma bodega**. Las entregas se agrupan en rutas antes del despacho; cuando el conductor confirma la carga e inicia una ruta, esta queda **cerrada a nuevos pedidos que no estén físicamente en el vehículo**.

Se integrarán los registros de ambos sistemas para cumplir el trabajo académico: extracción por APIs, ETL, Data Warehouse, visualización BI y clasificación de destinos probables mediante aprendizaje automático.

### 1.1. Reglas de negocio ya acordadas

1. El catálogo de productos será **público**, sin obligación de crear una cuenta de cliente.
2. En el checkout, el cliente facilitará los datos necesarios e indicará un **punto preciso en el mapa**.
3. Para las pruebas, **no habrá aprobación administrativa manual** de cada pedido; la confirmación automática depende de las validaciones configuradas (datos, disponibilidad y método de compra permitido).
4. Todos los conductores saldrán desde **una bodega común**.
5. El sistema propondrá una **asignación de pedidos a vehículos/conductores** y un **orden de visitas** que minimice costos de recorrido y respete restricciones. El administrador podrá supervisar y ajustar el despacho antes de iniciarlo.
6. El conductor deberá confirmar que lleva los productos correspondientes antes de iniciar la ruta.
7. Cuando la ruta esté iniciada, los pedidos nuevos pasarán a la **siguiente ruta** u otro vehículo disponible; no se añadirán automáticamente al vehículo en marcha.
8. El conductor registrará **«Entregado»** o **«No entregado»**, con motivo en el segundo caso.
9. **Traccar aporta ubicación GPS; Odoo determina el estado del pedido y de la entrega.** Estar cerca del destino no equivale a haber entregado.
10. La IA exigida para el proyecto **predice destinos probables a partir de históricos**; no sustituye al motor de optimización de rutas ni adivina compras futuras.

### 1.2. Delimitación: requisito académico frente a ampliación funcional

| Elemento | Clasificación | Observación |
|---|---|---|
| Odoo 16 con Fleet, Contacts y Sales; vehículos, conductores, clientes, pedidos y asignaciones | Requisito académico | Fuente administrativa de datos. |
| Traccar Client y Server; posiciones, rutas, viajes y paradas | Requisito académico | Fuente geográfica. |
| Vinculación vehículo de Odoo ↔ dispositivo de Traccar | Requisito académico | Correspondencia inequívoca. |
| APIs, staging, ETL, calidad y Data Warehouse dimensional | Requisito académico | Integración y trazabilidad. |
| Consultas OLAP y dashboard BI desde el Data Warehouse | Requisito académico | No sustituir por el panel operacional. |
| Modelo de clasificación de destinos y mapa de ruta sugerida | Requisito académico | Entrenar, evaluar y mostrar probabilidades. |
| eCommerce público con checkout geográfico | **Ampliación funcional propuesta** | No figura como obligación específica en la guía. |
| Asignación automática multivehículo, interfaz móvil y confirmación de entregas | **Ampliación funcional propuesta** | Aporta un caso de uso logístico completo. |
| Predicción de compras, cancelaciones o demanda futura | **Fuera del alcance inicial** | Requeriría otros conjuntos de datos y modelos. |

---

## 2. Responsabilidades y propiedad de los datos

| Componente | Qué administra | Qué **no** administra |
|---|---|---|
| **Odoo 16** | Catálogo, contactos, pedidos, destinos, bodega, flota, conductores, rutas de despacho, paradas, estados de entrega y evidencias. | El historial GPS primario recibido del celular. |
| **Traccar Server** | Dispositivos GPS, posiciones con fecha/hora, velocidad, eventos, recorridos y paradas. | Clientes, productos, órdenes de venta y confirmaciones comerciales de entrega. |
| **Traccar Client (móvil)** | Captura y transmisión de ubicación del teléfono autorizado mientras corresponda. | Gestión de pedidos, botones de entrega o registro de ventas. |
| **Motor de rutas (servicio lógico de optimización)** | Matriz de tiempos/distancias, distribución de pedidos y secuencia recomendada de paradas. | Decisiones de venta o estados comerciales. |
| **ETL y Data Warehouse** | Copia histórica controlada, vinculación de fuentes, limpieza, métricas y modelo dimensional. | Modificación directa de pedidos operativos. |
| **BI** | Indicadores históricos, comparaciones y filtros. | Confirmaciones de entrega o asignaciones operativas. |
| **IA de destinos** | Estimación de zona/destino probable según patrones históricos y evaluación del modelo. | Planificación obligatoria de entregas conocidas. |

**Principio de integración:** cada dato tiene una fuente responsable. No se debe escribir directamente en las tablas internas de Traccar ni duplicar innecesariamente el catálogo comercial. La vinculación se realiza mediante IDs y APIs.

---

## 3. Actores y experiencias de uso

### 3.1. Cliente — tienda pública de Odoo

**Acceso:** navegador web, sin cuenta obligatoria.

**Pantallas propuestas:**

1. **Inicio / Catálogo:** categorías, productos, precios, disponibilidad y buscador.
2. **Detalle del producto:** nombre, descripción, foto, precio, cantidad y botón «Agregar al carrito».
3. **Carrito:** productos, cantidades, subtotal y posibilidad de corregirlos.
4. **Checkout:** formulario de contacto, dirección descriptiva y **selector de ubicación en mapa**.
5. **Confirmación:** número de pedido, resumen, condiciones de compra y enlace privado de seguimiento.
6. **Seguimiento del pedido:** estados simplificados y, cuando aplique, información limitada del reparto.

**Campos posibles del checkout:**

| Campo | Obligatorio | Uso |
|---|---|---|
| Nombre completo | Sí | Identificar receptor. |
| Teléfono | Sí | Contacto de entrega; validación de formato. |
| Correo electrónico | Según modalidad | Enviar comprobante/enlace si el cliente dispone de correo. |
| Dirección descriptiva | Sí | Calle, número, sector, referencia. |
| Latitud y longitud | Sí | Destino exacto en el mapa. |
| Referencia de ubicación | Recomendado | Casa, edificio, piso, indicaciones. |
| Productos y cantidades | Sí | Contenido del pedido. |
| Observaciones | Opcional | Indicaciones no sensibles. |
| Método de pago de prueba | Según configuración | No se presupone una pasarela real. |
| Aceptación de términos y aviso de privacidad | Según diseño legal | Uso de datos de contacto y ubicación. |

**Reglas:**

- El cliente puede colocar/mover un pin; no basta con almacenar una dirección de texto.
- La ubicación seleccionada se conserva ligada **al pedido**, de modo que una futura edición de los datos generales del contacto no cambie retroactivamente el destino de ese pedido.
- Las coordenadas deben validarse y encontrarse dentro de una zona atendida, si se configura cobertura.
- Sin autenticación del cliente, el enlace de seguimiento debe usar un **token de acceso no predecible**, con caducidad o revocación y sin revelar datos de otras órdenes.
- Para las pruebas, al completar el checkout se valida el pedido y se envía a preparación **sin una aprobación manual**. Si faltan datos o no hay disponibilidad, no se confirma de manera silenciosa.

### 3.2. Administrador — centro de operaciones en Odoo

**Acceso:** usuario autenticado con permisos administrativos correspondientes.

**Secciones propuestas:**

- **Resumen operativo:** pedidos nuevos, en preparación, preparados, asignados, en ruta, entregados, fallidos y vehículos disponibles.
- **Gestión de pedidos:** filtrar, inspeccionar dirección y pin, revisar productos, detectar incidencias.
- **Flota y conductores:** vehículos, capacidades, conductores y asociación al dispositivo Traccar.
- **Planificación de despacho:** seleccionar pedidos preparados, generar propuesta de asignación/orden y revisar resultados.
- **Rutas de despacho:** bodega de origen, conductor, vehículo, secuencia de paradas, distancia/tiempo estimados y situación de carga.
- **Monitoreo GPS:** mapa con última posición válida, hora de actualización y recorrido ligado a la ruta activa.
- **Incidencias:** entregas fallidas, pedidos pendientes de reprogramación, desconexiones GPS y desviaciones.
- **Analítica predictiva:** consulta de destino probable y alternativas, con probabilidades y ruta sugerida.

**Acciones del administrador:**

- Corregir destinos **antes del cierre de la carga**, dejando auditoría.
- Iniciar la planificación automática y **aprobar o ajustar** la propuesta antes del despacho.
- No incorporar automáticamente pedidos nuevos a un vehículo cuya carga esté cerrada.
- Reprogramar entregas fallidas o preparar un retorno a bodega.
- Consultar datos de Traccar **desde Odoo**, sin requerir uso habitual de la consola administrativa de Traccar.

### 3.3. Conductor / transportista — vista móvil de Odoo

**Acceso:** usuario autenticado; solamente sus rutas y entregas asignadas.

**Pantallas propuestas:**

1. **Mis rutas:** ruta del día, vehículo, número de pedidos, estado y punto de salida.
2. **Detalle de ruta:** listado ordenado de paradas, mapa, destino siguiente y cantidades o bultos a cargar.
3. **Confirmación de carga:** revisión de pedidos/bultos; botón «Confirmar carga».
4. **Recorrido activo:** «Iniciar recorrido», destino actual, siguiente parada y acceso a navegación vial.
5. **Entrega individual:** datos mínimos del receptor, indicaciones, «Registrar llegada», «Entregado» o «No entregado».
6. **Cierre de ruta:** entregas completadas, fallidas, bultos pendientes y retorno a bodega cuando proceda.

**Campos visibles en una tarjeta de entrega:** número de pedido, nombre del receptor, teléfono enmascarado cuando aplique, dirección, referencia, ubicación, orden de parada, productos o bultos, observaciones y estado.

**Confirmación de entrega:**

- Al pulsar **«Entregado»**, Odoo verifica que el usuario sea el conductor asignado y que la entrega permita esa transición.
- Registra conductor, instante de confirmación, ruta, parada, resultado y evidencia disponible.
- Se puede contemplar foto o firma como extensión, pero **no debe exigirse para la primera prueba** si no es un requisito académico.
- La ubicación GPS más reciente puede adjuntarse como dato complementario, indicando su antigüedad y precisión disponible; **no sustituye** la acción de confirmación.

**Entrega fallida:**

- Botón **«No entregado»** con motivo obligatorio y observación opcional.
- Motivos propuestos: cliente ausente, dirección incorrecta, cliente rechaza, acceso impedido, problema con el producto, otro.
- El pedido queda pendiente de reprogramación o devolución; no desaparece del historial ni se contabiliza como entregado.

**Relación con Traccar Client:** el conductor usa la vista móvil de Odoo para las operaciones; Traccar Client instalado y autorizado en ese mismo teléfono transmite las posiciones GPS. **Traccar Client no muestra ni confirma pedidos por sí solo.**

---

## 4. Módulos estándar de Odoo que se reutilizarán

> Los nombres de modelos mencionados son referencias típicas de Odoo 16; los campos concretos deben comprobarse al implementar. Las funcionalidades nuevas de despacho no aparecen automáticamente por instalar los módulos base.

| Aplicación estándar | Modelos / entidades orientativas | Funcionalidad reutilizada |
|---|---|---|
| **Contacts** (`contacts`) | `res.partner` | Clientes y direcciones. |
| **Sales** (`sale_management`) | `sale.order`, `sale.order.line` | Pedidos comerciales, productos, cantidades e importes. |
| **Fleet** (`fleet`) | `fleet.vehicle`, información de conductor | Vehículos, matrículas, referencias de conductor. |
| **Website** (`website`) | Sitio web | Interfaz pública del cliente. |
| **eCommerce** (`website_sale`) | Carrito y venta web | Catálogo, carrito y checkout integrados con ventas. |
| **Products / Inventory** (según configuración) | `product.template`, `product.product` y, si se habilita, existencias | Catálogo y disponibilidad; preparación física si se usa inventario. |

### 4.1. Integración del eCommerce con el flujo logístico

**Lo que ya aporta el eCommerce:** exhibición de productos, carrito, proceso de compra y creación de información comercial del pedido.

**Lo que agregará nuestra personalización:**

1. Campo/mapa de destino en el checkout.
2. Validación de coordenadas y datos mínimos de entrega.
3. Asociación permanente de destino geográfico al pedido.
4. Regla de confirmación de pedidos de prueba según disponibilidad y modalidad configurada.
5. Generación de una **solicitud logística de entrega** a partir del pedido válido.
6. Vínculo entre pedido comercial, entrega logística, despacho, conductor y vehículo.
7. Página/enlace de seguimiento para cliente invitado.

**Importante:** `sale.order` tiene sus propios estados comerciales. No debemos utilizarlos como sustituto de los estados logísticos. Por ejemplo, una venta confirmada puede estar «en preparación» o «en ruta» y todavía no estar entregada.

---

## 5. Módulos personalizados propuestos para Odoo

Los identificadores siguientes son **nombres propuestos**, todavía no definitivos. Las tablas son un **catálogo conceptual de campos**, no un esquema SQL aprobado.

### Módulo 1 — `logistica_base` (configuración y vínculos)

**Responsabilidad:** entidades compartidas, bodega de origen, configuraciones operativas y correspondencia Odoo–Traccar.

**Funciones:**

- Definir la bodega principal y sus coordenadas.
- Registrar tipos/capacidades de vehículos para planificación.
- Asociar cada vehículo de Odoo con un dispositivo único de Traccar.
- Comprobar que no existan asociaciones activas duplicadas.
- Definir umbrales de cercanía, tiempos de actualización GPS y parámetros básicos de operación.

**Campos posibles:**

| Entidad | Campos propuestos |
|---|---|
| Bodega / punto de despacho | `name`, `address`, `latitude`, `longitude`, `active` |
| Vinculación GPS | `vehicle_id`, `traccar_device_id`, `traccar_unique_id`, `active`, `linked_at`, `last_checked_at` |
| Parámetros operativos | `arrival_radius_m`, `gps_stale_after_seconds`, `dispatch_cutoff`, `route_recalculation_policy` |

### Módulo 2 — `logistica_checkout` (destinos y seguimiento público)

**Responsabilidad:** ampliar el eCommerce estándar sin reemplazar el catálogo ni el carrito.

**Funciones:**

- Selector de punto geográfico en checkout.
- Datos de referencia para el transportista.
- Validación de cobertura y datos.
- Enlace de consulta de pedido para cliente sin cuenta.
- Conversión del pedido válido a solicitud logística.

**Campos posibles del destino asociado al pedido:**

`order_id`, `recipient_name`, `phone`, `delivery_address_text`, `delivery_reference`, `delivery_latitude`, `delivery_longitude`, `location_confirmed_at`, `delivery_notes`, `coverage_validation_status`.

**Seguridad del seguimiento público:** token no predecible, alcance a un solo pedido, datos minimizados, expiración/revocación y protección contra intentos masivos.

### Módulo 3 — `logistica_entregas` (gestión de pedidos logísticos)

**Responsabilidad:** crear la unidad «entrega» vinculada con la venta.

**Funciones:**

- Registrar una entrega por pedido cuando corresponda.
- Separar estado comercial de estado de entrega.
- Gestionar preparación, disponibilidad para despacho, asignación y resultado final.
- Conservar eventos auditables y motivo de fallo.

**Campos posibles de entrega:**

`delivery_id`, `sale_order_id`, `customer_id`, `destination_latitude`, `destination_longitude`, `destination_address`, `status`, `prepared_at`, `route_id`, `vehicle_id`, `driver_id`, `stop_sequence`, `dispatched_at`, `arrived_at`, `completed_at`, `failed_reason`, `notes`.

**Nota de alcance:** para la primera versión puede asumirse **una entrega por pedido**, pero el modelo debe permitir en el futuro entregas parciales o múltiples bultos sin romper la relación con `sale.order`.

### Módulo 4 — `logistica_despacho` (planificación y asignación)

**Responsabilidad:** crear rutas de despacho y asignar entregas a vehículos antes de su salida.

**Funciones:**

- Seleccionar pedidos preparados y sin ruta.
- Validar flota disponible y capacidad de carga.
- Solicitar una propuesta de asignación y secuencia de paradas al motor de optimización.
- Revisar o modificar la propuesta.
- Registrar una ruta por conductor/vehículo, con origen común en bodega.
- Cerrar la carga y bloquear incorporación automática de pedidos ajenos a esa ruta.

**Campos posibles de ruta:**

`route_id`, `route_code`, `warehouse_id`, `vehicle_id`, `driver_id`, `planned_start_at`, `status`, `planned_distance_km`, `planned_duration_min`, `confirmed_load_at`, `started_at`, `finished_at`, `optimization_version`.

**Campos posibles de parada:**

`stop_id`, `route_id`, `delivery_id`, `sequence`, `destination_latitude`, `destination_longitude`, `estimated_arrival_at`, `actual_arrival_at`, `actual_completed_at`, `status`.

**Qué optimiza y qué no:** usa destinos **conocidos y confirmados** de pedidos actuales. La secuencia recomendada no requiere entrenar IA: es un problema de optimización de rutas con restricciones (capacidad, disponibilidad, tiempos y bodega común).

### Módulo 5 — `logistica_traccar` (integración GPS)

**Responsabilidad:** comunicación autorizada de Odoo con Traccar.

**Funciones:**

- Consultar catálogo de dispositivos.
- Recuperar última ubicación y su fecha/hora.
- Recuperar histórico y datos de viajes/paradas por dispositivo y rango de fechas.
- Mostrar vehículos en el mapa de Odoo.
- Asociar posiciones con la ruta activa **solo cuando los IDs y períodos coincidan**.
- Identificar GPS desactualizado, ausencia de señal y posible proximidad a un destino.

**Campos posibles de registro de lectura GPS:**

`vehicle_id`, `traccar_device_id`, `position_id`, `gps_time`, `latitude`, `longitude`, `speed`, `accuracy_if_available`, `received_at`, `is_stale`.

**Regla:** Odoo puede almacenar la última lectura o caché operativa; el histórico GPS primario permanece en Traccar. Para análisis histórico se extraerá por API al Data Warehouse.

### Módulo 6 — `logistica_conductor` (portal móvil restringido)

**Responsabilidad:** experiencia operativa del transportista dentro de Odoo.

**Funciones:**

- Consultar solo rutas propias.
- Confirmar carga.
- Iniciar y cerrar recorrido.
- Visualizar orden de paradas y destino siguiente.
- Registrar llegada, entrega exitosa o fallida.
- Consultar mapa/abrir navegación hacia una parada.

**Campos posibles de evento de entrega:**

`event_id`, `delivery_id`, `route_id`, `driver_user_id`, `event_type`, `event_time`, `notes`, `failure_reason`, `gps_position_id_if_available`, `evidence_reference`.

**Seguridad:** permisos de registro y reglas de acceso por conductor; no confiar solo en ocultar botones en pantalla.

### Módulo 7 — `logistica_analitica_ia` (interfaz predictiva)

**Responsabilidad:** ofrecer en Odoo una interfaz de consulta de predicciones, sin entrenar el modelo dentro del proceso transaccional.

**Funciones:**

- Elegir vehículo, fecha/día, hora y zona de origen.
- Consultar un modelo de clasificación entrenado con históricos.
- Mostrar destino probable, alternativas y probabilidades.
- Visualizar la ruta vial sugerida desde origen al destino estimado.
- Guardar registro de consultas para auditoría, si se requiere.

**Campos posibles de consulta:**

`vehicle_id`, `reference_datetime`, `origin_zone_id`, `predicted_destination_zone_id`, `class_probabilities`, `model_version`, `prediction_created_at`.

**Distinción:** esta predicción **no asigna automáticamente pedidos reales**. Su función académica es clasificar destinos probables y demostrar el modelo.

---

## 6. Traccar: funcionamiento e interacción con Odoo

### 6.1. Flujo GPS

```text
Teléfono del conductor (Traccar Client)
        |
        | Identificador de dispositivo + posiciones GPS
        v
Traccar Server
        |
        | API REST / actualizaciones autorizadas
        v
Módulo logistica_traccar en Odoo
        |
        +--> Mapa de flota y estado de conexión
        +--> Posible llegada a parada (por proximidad)
        +--> Trazabilidad de ruta y entrega
```

### 6.2. Correspondencia obligatoria

Ejemplo ilustrativo:

| Odoo | Traccar | Resultado |
|---|---|---|
| Vehículo `ABC-1234` (`vehicle_id = 15`) | Dispositivo `device_id = 8` (`unique_id` registrado) | Las posiciones del dispositivo 8 corresponden al vehículo 15. |

**No basta comparar matrículas o nombres:** la vinculación debe persistirse mediante identificadores estables y validar que cada dispositivo activo no esté asignado a dos vehículos simultáneamente.

### 6.3. Consultas de Traccar previstas

| Recurso | Función en el proyecto |
|---|---|
| `/api/devices` | Relacionar dispositivos con vehículos de Odoo. |
| `/api/positions` | Consultar posiciones disponibles / última ubicación. |
| `/api/reports/route` | Recuperar detalle geográfico histórico. |
| `/api/reports/trips` | Consultar viajes detectados. |
| `/api/reports/stops` | Consultar paradas. |

Para reportes se usarán dispositivo y período. Si se utiliza un canal de actualización en vivo, el backend validará permisos y distribución de datos antes de mostrar información a los usuarios.

### 6.4. Llegada vs. entrega

- **Posible llegada:** cálculo de proximidad entre posición GPS y coordenadas de destino (o evento de geocerca debidamente configurada).
- **Llegada registrada:** confirmación operativa del conductor o evento validado, según la regla definitiva.
- **Entregado:** acción expresa del conductor, registrada por Odoo con sello temporal.
- **No entregado:** acción del conductor con motivo de fallo.

Una llegada GPS **nunca marcará automáticamente «Entregado»**.

### 6.5. Fallos de comunicación

- Si no hay señal GPS, mostrar **«Última ubicación conocida»** y cuánto tiempo ha transcurrido; no simular movimiento.
- Si Traccar no responde, Odoo conserva pedidos/asignaciones y registra el error.
- Si el conductor puede confirmar una entrega pero falta posición, guardar el hecho con estado **«GPS no disponible»** y analizar posteriormente.
- Evitar duplicar eventos al reintentar consultas o confirmaciones.

---

## 7. Ciclo completo de un pedido (de extremo a extremo)

### Etapa 1 — Compra

1. El cliente entra al catálogo público de Odoo.
2. Selecciona productos y cantidades.
3. En checkout completa nombre, teléfono y dirección; coloca el pin de entrega en el mapa.
4. Odoo valida datos, disponibilidad y condiciones de prueba; crea y confirma el pedido cuando corresponda.
5. Se crea una entrega logística vinculada con ese pedido.
6. El cliente recibe un número de pedido y un enlace protegido para consultar su estado.

### Etapa 2 — Preparación

7. El pedido queda **«En preparación»**.
8. Se preparan los productos, físicamente o por simulación explícita en la prueba.
9. Cuando queda listo, pasa a **«Preparado para despacho»**.

> No hay aprobación administrativa del pedido, pero sí debe distinguirse la **preparación física/simulada** de la **asignación de despacho**.

### Etapa 3 — Planificación y asignación

10. El administrador consulta entregas preparadas y vehículos/conductores disponibles.
11. El optimizador considera bodega común, destinos, capacidad, disponibilidad y distancias/tiempos de carretera.
12. Propone qué pedidos llevará cada vehículo y en qué orden visitará a los clientes.
13. El administrador revisa y aprueba/ajusta la propuesta.
14. Odoo registra la ruta y sus paradas con vínculos a pedido, vehículo y conductor.

### Etapa 4 — Despacho

15. El conductor entra a **«Mis rutas»**, comprueba los pedidos que debe cargar y confirma la carga.
16. La ruta pasa a **«Carga confirmada / lista para salida»**.
17. El conductor pulsa **«Iniciar recorrido»**.
18. La ruta queda en ejecución y **no admite nuevos pedidos no cargados**.

### Etapa 5 — Seguimiento y entregas

19. Traccar Client transmite coordenadas mientras el recorrido está autorizado.
20. Odoo consulta las posiciones asociadas al vehículo y muestra el recorrido/última ubicación.
21. La aplicación del conductor muestra la próxima parada según la secuencia de ruta.
22. Al llegar, se puede registrar llegada; el GPS únicamente complementa el evento.
23. El conductor pulsa **«Entregado»** o **«No entregado»** y completa la evidencia/motivo correspondiente.
24. Odoo actualiza la entrega, guarda el evento y refleja el resultado al administrador y en el seguimiento público.
25. El conductor continúa con la siguiente parada pendiente.

### Etapa 6 — Cierre y análisis

26. Una vez gestionadas todas las paradas, se cierra la ruta; se registran bultos pendientes y retorno si corresponde.
27. ETL extrae Odoo y Traccar mediante APIs.
28. Se vinculan pedidos/entregas/rutas con dispositivos/recorridos y se calculan indicadores verificables.
29. Se cargan datos depurados e históricos al Data Warehouse.
30. BI presenta resultados y el modelo de IA permite consultar destinos probables.

---

## 8. Estados propuestos y transiciones

### 8.1. Estado comercial (nativo de Odoo)

El pedido en `sale.order` conserva su ciclo de venta habitual. **No se reemplaza por el estado del reparto.** Las reglas de checkout y confirmación de venta dependen de la modalidad habilitada para las pruebas.

### 8.2. Estado logístico de la entrega

```text
Pendiente de preparación
      |
      v
En preparación
      |
      v
Preparado para despacho
      |
      v
Asignado a ruta
      |
      v
En recorrido
      |
      +--> Llegada registrada --> Entregado
      |
      +--> No entregado --> Pendiente de reprogramación / devolución
```

Un pedido cancelado antes de ser cargado debe salir de la planificación. Un fallo después de salir debe permanecer registrado con su motivo y gestión de retorno/reintento.

### 8.3. Estado logístico de la ruta

`Borrador → Planificada → Carga confirmada → En recorrido → Cerrada`

Adicionalmente: `Cancelada` **antes de iniciar**, o `Interrumpida` **durante la ejecución**, con motivo y autorización.

### 8.4. Reglas de inmutabilidad y cambios

| Situación | Comportamiento propuesto |
|---|---|
| Entra un pedido nuevo antes del cierre de carga | Puede entrar en la planificación si cumple condiciones y se recalcula antes de confirmar. |
| Entra un pedido nuevo con ruta ya iniciada | Permanece en cola para próxima ruta/u otro conductor. |
| Cambia la dirección de una parada ya cargada | Requiere validación operativa y recalcular **solo las paradas aún pendientes** si es viable. |
| Cliente ausente | Marcar «No entregado», registrar motivo, programar retorno o nuevo intento. |
| Vehículo pierde GPS | Mostrar posición antigua; el conductor sigue operando y se registra la incidencia. |
| El conductor no confirma la entrega | El pedido permanece pendiente; la proximidad GPS no lo completa. |
| Una ruta termina con pedidos fallidos | Cerrar con resultados diferenciados, nunca contarlos como entregados. |

---

## 9. Optimización de despacho: qué se calcula

**Entradas operativas:**

- Coordenadas de la bodega única.
- Pedidos preparados con destinos geográficos válidos.
- Capacidad y disponibilidad de vehículos/conductores.
- Duraciones y distancias estimadas por carretera.
- Restricciones de horario u operación que se decidan implementar.

**Salidas:**

- Asignación de cada pedido a un vehículo elegible.
- Orden de paradas recomendado para cada ruta.
- Distancia y tiempo estimados por ruta.
- Pedidos que no pudieron asignarse y su motivo.

**Motor propuesto:** un servicio de cálculo de distancias/tiempos por carretera, combinado con un solucionador de asignación/ruteo. El algoritmo debe **minimizar una función objetivo definida**, no simplemente elegir el pedido geográficamente más cercano en línea recta. La solución será una propuesta sujeta a capacidad y reglas, no una garantía absoluta de óptimo global.

**Separación importante:** este cálculo trabaja con **direcciones reales ya conocidas**; es diferente al modelo de ML que predice el destino probable de un viaje basándose en históricos.

---

## 10. Analítica e inteligencia artificial exigidas por el proyecto

### 10.1. Flujo analítico

```text
Odoo (pedidos, entregas, vehículos, conductores, clientes)
                     +
Traccar (devices, positions, route, trips, stops)
                     |
                     v
       Extracción por interfaces oficiales
                     |
                     v
     Staging de datos originales + validación
                     |
                     v
    ETL: calidad, fechas, zonas y relaciones
                     |
                     v
           Data Warehouse dimensional
                  /       \
                 v         v
             BI / OLAP   Modelo de IA
```

### 10.2. Data Warehouse

**Dimensiones que exige la guía:** `DIM_VEHICULO`, `DIM_CONDUCTOR`, `DIM_TIEMPO`, `DIM_ZONA`, `DIM_CLIENTE`.

**Hechos que exige la guía:** `FACT_RECORRIDOS`, `FACT_ENTREGAS`.

**Detalle adicional exigido:** posiciones GPS históricas que permitan reconstruir el recorrido, claves y trazabilidad al origen.

**Controles ETL:** duplicados, fechas incoherentes, coordenadas inválidas, velocidades anómalas, nulos, husos horarios, unidades de medida, cargas incrementales y registro de datos rechazados.

**Regla de vinculación:** asociar una entrega con un recorrido **solo cuando haya una coincidencia verificable** entre IDs de vehículo/dispositivo, ruta y período.

### 10.3. BI / OLAP

Indicadores de referencia: distancia por vehículo, recorridos por día/hora, duración promedio, zonas visitadas, paradas, entregas por cliente, estado y cumplimiento de lo planificado.

**Los dashboards académicos consultarán el Data Warehouse**, no directamente las tablas transaccionales de Odoo/Traccar. El mapa operacional de Odoo es una interfaz distinta, orientada a actividad actual.

### 10.4. Machine Learning: predicción de destinos

**Entrada del clasificador:** vehículo, día, hora y zona de origen, con base en un histórico etiquetado de viajes.

**Salida:** destino probable, destinos alternativos y probabilidades estimadas.

**Validación:** partición temporal de entrenamiento/prueba, accuracy, precision, recall, F1, matriz de confusión y comparación con un predictor básico.

**Mapa:** una herramienta de enrutamiento construye la ruta vial desde el origen al destino **predicho**. La IA no calcula cada coordenada de la ruta.

**Procedencia de datos:** separar expresamente históricos GPS reales de históricos simulados usados para entrenamiento o demostración.

---

## 11. Ejemplo integrado de operación (datos ficticios)

**Bodega de salida:** bodega central de la distribuidora.  
**Vehículos:** ABC-1234, DEF-5678 y GHI-9012.  
**Conductores:** Carlos, Luis y Pedro.  
**Pedidos nuevos:** cinco pedidos web con ubicaciones de entrega confirmadas.

| Momento | Actor / sistema | Acción | Resultado |
|---|---|---|---|
| 07:30 | Cliente | Compra sin cuenta y marca el punto de entrega. | Pedido registrado en Odoo. |
| 07:35 | Odoo | Valida y confirma la compra de prueba. | Entrega en preparación. |
| 07:50 | Preparación | Se completan los cinco pedidos. | Entregas disponibles para despacho. |
| 08:00 | Odoo / optimizador | Propone asignación y secuencia por vehículo. | Dos entregas a Carlos, dos a Luis, una a Pedro; **solo ilustrativo**. |
| 08:05 | Administrador | Revisa y aprueba rutas. | Despachos planificados. |
| 08:10 | Conductores | Confirman carga e inician rutas. | Ruta cerrada a pedidos nuevos. |
| 08:15–09:30 | Traccar | Recibe ubicaciones GPS. | Seguimiento de vehículos. |
| 08:40 | Carlos | Pulsa «Entregado» en la primera parada. | Entrega cerrada con evento y hora. |
| 09:00 | Luis | Pulsa «No entregado»: cliente ausente. | Incidencia y reprogramación pendientes. |
| Al terminar | ETL / BI | Vincula recorridos con entregas verificables. | Histórico y KPIs actualizados según periodicidad. |
| Consulta posterior | Administrador | Usa módulo de IA de destinos. | Predicción con alternativas, probabilidades y mapa. |

Si entra un **sexto pedido a las 08:20**, no se añade automáticamente a las rutas de las 08:10: queda pendiente de despacho posterior.

---

## 12. Reglas de seguridad y privacidad funcional

- Usar seguimiento GPS solamente durante actividades autorizadas y consentidas; evitar monitoreo personal continuo fuera de la jornada/operación.
- Restringir el acceso del conductor a sus propias rutas y del cliente invitado a su pedido mediante token.
- No exponer credenciales de Traccar al navegador ni permitir acceso público a su administración.
- Limitar la ubicación visible al cliente a lo necesario para su entrega; evitar revelar otras paradas o datos de terceros.
- Conservar auditoría de asignaciones, confirmaciones, cambios de dirección y fallos.
- Definir retención y eliminación/anonimización de datos de ubicación conforme a la necesidad y obligaciones aplicables.
- Indicar cuándo una ubicación es antigua o un resultado es estimado/simulado.

---

## 13. Criterios de aceptación funcional del flujo completo

- [ ] Un cliente puede navegar el catálogo, comprar sin cuenta y marcar correctamente un destino GPS.
- [ ] El pedido aparece en Odoo con sus productos, datos de contacto y coordenadas de entrega.
- [ ] El pedido pasa a preparación sin aprobación administrativa manual, siempre que supere las validaciones.
- [ ] Existen por lo menos tres vehículos/conductores y una correspondencia verificable con los dispositivos GPS.
- [ ] El administrador puede generar y revisar una asignación de pedidos desde una bodega común.
- [ ] El conductor puede ver únicamente sus rutas, confirmar la carga e iniciar recorrido.
- [ ] Las posiciones de Traccar se muestran asociadas al vehículo correcto y con marca de tiempo.
- [ ] La llegada GPS no marca automáticamente como entregado un pedido.
- [ ] El conductor puede marcar «Entregado» o «No entregado», con motivo de fallo y auditoría.
- [ ] Una ruta iniciada no recibe automáticamente pedidos nuevos que no fueron cargados.
- [ ] El cliente puede consultar el estado de su pedido de forma protegida, sin cuenta obligatoria.
- [ ] Se extraen datos de ambas APIs, se validan y se cargan a un modelo dimensional verificable.
- [ ] El dashboard BI utiliza el Data Warehouse y permite analizar rutas y entregas.
- [ ] El modelo de IA predice destinos probables, incluye métricas de evaluación y presenta una ruta vial en el mapa.

---

## 14. Decisiones que todavía debemos validar antes de implementar

1. **Preparación:** ¿la simulación de preparación será manual mediante botón «Preparado» o mediante inventario/operaciones de Odoo?
2. **Cobro de prueba:** ¿los pedidos se confirmarán como contraentrega, sin cobro, o con otra modalidad controlada?
3. **Capacidad de vehículos:** ¿se medirá por cantidad de paquetes, peso, volumen o máximo de pedidos por ruta?
4. **Confirmación de entrega:** ¿basta el botón del conductor o se exigirá firma/fotografía en una fase posterior?
5. **Seguimiento público:** ¿mostrar estado solamente o también ubicación aproximada cuando el vehículo esté próximo al destino?
6. **Rutas fallidas:** ¿el paquete vuelve a bodega inmediatamente o puede quedar para un segundo intento autorizado?
7. **Cambios de destino:** ¿hasta qué estado puede un cliente corregir su ubicación y quién debe aprobarlo?

Estas decisiones no impiden entender el flujo; deben cerrarse antes de aprobar los modelos y reglas definitivos.

---

## 15. Resumen final del diseño

**El cliente compra** desde el eCommerce público de Odoo y especifica un punto de entrega. **Odoo registra y prepara** el pedido. **El administrador organiza el despacho** con un optimizador de rutas que parte de la bodega común. **El conductor consulta y ejecuta** sus entregas desde una vista móvil de Odoo, confirmando carga, inicio y resultado de cada parada. **Traccar registra los movimientos GPS** que Odoo consulta para supervisión y trazabilidad. Finalmente, **ETL, SQL Server, BI e IA** transforman los registros en análisis históricos y predicciones de destinos, cumpliendo los requisitos académicos.

**Estado del documento:** especificación funcional propuesta para revisión; no describe una implementación existente.
