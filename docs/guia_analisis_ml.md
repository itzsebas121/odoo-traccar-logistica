# Guía para implementar el análisis de modelos de ML (predicción de destinos)

**Estado:** documento de diseño para una implementación posterior. El ETL ya deja en el Data Warehouse todo lo que esta guía usa. El servicio `services/ml` existe y funciona (entrena, evalúa y sirve `/predict`), pero el análisis de modelos que se describe aquí **no está implementado**.

**Requisito que cubre:** §10.4 de la [especificación](flujo_funcional_odoo_traccar.md) y el último criterio de §13. El clasificador recibe vehículo, día, hora y zona de origen, y devuelve el destino probable, las alternativas y sus probabilidades. Se valida con partición temporal, accuracy, precision, recall, F1, matriz de confusión y comparación con un predictor básico. Los datos reales y los simulados van separados.

**Antes de empezar:** el ETL tiene que correr sin fallos (`etl report` sin errores en las últimas corridas).

---

## 1. De dónde salen los datos

El ML solo lee `logistica_dwh`, con el rol de solo lectura `dwh_ro` (`DWH_DSN` en `compose.yaml`). Nunca lee Odoo, Traccar ni staging.

| Vista | Una fila por | Para qué |
|---|---|---|
| `v_viajes_entrenamiento` | viaje (REAL o SIMULADO) con las dos zonas conocidas | **Contrato C3.** Es la que lee hoy `mlsvc.train --source dwh`. Columnas: `vehiculo_codigo`, `fecha_hora` (UTC, ISO con `Z`), `zona_origen`, `zona_destino`, `procedencia`. No se cambia. |
| `v_ml_viajes` | viaje | Dataset ampliado: `recorrido_sk`, `conductor`, `inicio_utc`, `fin_utc`, `fecha_local`, `hora_local`, `dia_semana_local` (1 = lunes), `franja`, `fin_de_semana`, coordenadas de origen y destino, `distancia_km`, `duracion_min`, velocidades, `num_paradas`, `ruta_id_odoo`, `en_ruta`, `entregas_vinculadas`. Las zonas pueden ser NULL: para entrenar, filtrar `zona_origen IS NOT NULL AND zona_destino IS NOT NULL`. |
| `v_ml_transiciones_paradas` | parada con resultado (entregado o no entregado) | Segunda fuente de etiquetas: destinos de negocio confirmados en Odoo, de una parada a la siguiente dentro de la ruta. En la primera parada `zona_origen` es NULL, porque se sale de la bodega. |

Reglas del ETL que conviene saber al interpretar los datos (detalle en [services/etl/README.md](../services/etl/README.md)):

- **Zona** = la del centroide más cercano de `logistica.zona`. A más de 4 km de todos, `otra`.
- **Hora local** = la de `ETL_TZ` (America/Guayaquil, UTC−5 sin horario de verano). `dim_tiempo` y las vistas `v_ml_*` ya la traen. `v_viajes_entrenamiento` la deja en UTC y `mlsvc/features.py` resta un desfase **fijo** de 5 horas (`TZ_OFFSET_H`). Si se cambia `ETL_TZ`, la hora del ML deja de coincidir con la del ETL; en ese caso conviene que las variables salgan de `hora_local` y `dia_semana_local` de `v_ml_viajes`.
- **Coordenadas** en `v_ml_viajes`: solo en viajes con ruta (privacidad, §12). No son variables del modelo; sirven para el análisis espacial de los viajes de la operación.
- **Conductor** de un viaje: el de su ruta y, fuera de ruta, el que tenía el vehículo cuando se cargó el viaje.
- **SIMULADO**: `etl simulate --dias N` genera la jornada de 07:00 a 21:00 locales. Se puede repetir con otra `N`, u otro día, sin duplicar: cada día de calendario sale siempre igual. Lo genera con un destino preferido por vehículo y franja (`etl/simulate.py`, `PREFERIDO`) y un 20 % de ruido. Por diseño, un buen modelo tiene que acertar alrededor del 80 % en estos datos.
- **Viajes REAL**: Traccar ya descarta los viajes muy cortos (`minimalTripDistance` y `minimalTripDuration`). Un viaje que todavía no terminó no está en el DWH: entra en la corrida siguiente.

## 2. Qué conviene preparar en el servicio ML (pendientes conocidos)

Son defectos de `services/ml` que el análisis va a encontrar. Conviene corregirlos antes o junto con el análisis:

| # | Pendiente | Dónde | Qué hacer |
|---|---|---|---|
| M1 | La lista `ZONAS` está fija en el código. Si en Odoo se crea una zona nueva, el ETL la carga y la usa como etiqueta, pero `/predict` rechaza esa zona como origen. | `mlsvc/__init__.py`, `serve.py` | Validar `origin_zone` contra las etiquetas y categorías del modelo entrenado, guardadas en `model.joblib`, o leerlas de `dim_zona`. |
| M2 | Entrena con REAL y SIMULADO mezclados y solo informa el conteo de cada uno. | `mlsvc/train.py` | Parámetro `--procedencia REAL\|SIMULADO\|todas`, y métricas por procedencia en `metrics.json`. |
| M3 | `model.joblib` y `metrics.json` no se escriben de forma atómica. | `train.py` | Escribir en un archivo temporal y renombrarlo con `os.replace`. |
| M4 | La contraseña de `DWH_DSN` no va codificada en la URL: se rompe con `@`, `:` o `/`. | `compose.yaml`, `train.py` | Usar variables separadas y `psycopg2.connect(**kwargs)`, como hace el BI. |
| M5 | Si hay menos de 4 clases, devuelve menos de 3 alternativas. Además, la conexión a la base no se cierra y `vehicle_code` no se valida. | `serve.py`, `train.py` | Documentarlo en la respuesta o validarlo. Cerrar la conexión con `with closing(...)`. |
| M6 | El predictor base es solo «la clase más frecuente». | `train.py` | Añadir un segundo predictor base, más honesto: el destino más frecuente por vehículo y franja. Es la referencia que el modelo tiene que superar. |

## 3. Plan del análisis

### 3.1. Exploración (cuaderno o script `services/ml/analisis/`)

1. **Volumen y procedencia:** número de viajes por procedencia, vehículo y semana. Fecha del primer y del último viaje.
2. **Distribución de la etiqueta:** viajes por `zona_destino`. Si una clase tiene menos del 5 % de los viajes, hay que decidir si se agrupa en `otra`.
3. **Patrones:** mapa de calor de destino por hora local y por día de la semana. Matriz de origen a destino, que es lo que el modelo debería aprender.
4. **Calidad:**
   - viajes con zona NULL (sin coordenadas);
   - viajes de la bodega a la bodega;
   - distancia o duración atípicas, que se ven en un diagrama de caja.
5. **Fuente de negocio:** el mismo análisis con `v_ml_transiciones_paradas`, para comparar los destinos que dice el GPS con los que confirma Odoo.

Consulta base:

```sql
SELECT vehiculo_codigo, inicio_utc, hora_local, dia_semana_local, franja, fin_de_semana,
       zona_origen, zona_destino, distancia_km, duracion_min, en_ruta, procedencia
FROM v_ml_viajes
WHERE zona_origen IS NOT NULL AND zona_destino IS NOT NULL
ORDER BY inicio_utc;
```

### 3.2. Variables

| Variable | Origen | Codificación |
|---|---|---|
| vehículo (obligatoria, §10.4) | `vehiculo_codigo` | one-hot (`handle_unknown="ignore"`) |
| zona de origen (obligatoria) | `zona_origen` | one-hot |
| hora (obligatoria) | `hora_local` + minutos de `inicio_utc` | seno y coseno sobre 24 h |
| día (obligatoria) | `dia_semana_local` | seno y coseno sobre 7 días, o `fin_de_semana` |
| franja (opcional) | `franja` | one-hot |
| conductor (opcional) | `conductor` | one-hot. Ojo: solo es útil si el conductor se conoce **antes** del viaje. |

**No usar como variable** nada que solo se conoce al terminar el viaje: `distancia_km`, `duracion_min`, `lat_destino`, `lon_destino`, `entregas_vinculadas`. Filtran la respuesta al modelo y las métricas saldrían infladas.

### 3.3. Partición y validación

- **Temporal, nunca aleatoria:** el 80 % más antiguo para entrenar y el 20 % más reciente para probar (ya lo hace `split_temporal`). Si hay pocos datos, usar validación hacia adelante: `TimeSeriesSplit` con 3 a 5 cortes.
- **Por procedencia:** entrenar y evaluar REAL y SIMULADO por separado y presentarlos en tablas distintas (§10.4). Con pocos datos REAL, se puede entrenar con todo y evaluar **solo con REAL**, y decirlo explícitamente.
- **Métricas** (ya las calcula `entrenar`): accuracy, precision, recall y F1 en macro, matriz de confusión con las etiquetas en orden fijo, y comparación con el predictor base.
- **Añadir:** top-3 accuracy (si el destino real está entre las 3 primeras predicciones, que es lo que muestra Odoo) y F1 por clase.

### 3.4. Modelos que comparar

1. Predictor base de la clase más frecuente (ya existe).
2. Predictor base del destino más frecuente por vehículo y franja (M6).
3. Regresión logística multinomial, interpretable.
4. Random Forest (el actual: 200 árboles, `random_state=42`).
5. Opcional: gradient boosting (`HistGradientBoostingClassifier`).

El modelo elegido se guarda con `model_version` y con las métricas del corte de prueba. `/metrics` las expone, y tanto el BI (pestaña Modelo) como el asistente de Odoo (`logistica_analitica_ia`) las leen de ahí.

### 3.5. Presentación de resultados

- Tabla comparativa de modelos, por procedencia.
- Matriz de confusión del modelo elegido.
- Importancia de las variables (permutation importance).
- Tres ejemplos de `/predict`, con su ruta sugerida en el mapa (servicio `routing`, `/route`).

## 4. Cómo se corre de punta a punta

```bash
# 1. Datos al DWH
docker compose --profile etl run --rm etl bootstrap
docker compose --profile etl run --rm etl run --mode full
docker compose --profile etl run --rm etl simulate --dias 60      # histórico SIMULADO

# 2. Entrenamiento con el DWH (rol dwh_ro, necesita DWH_DB_PASSWORD en .env)
docker compose --profile analitica run --rm ml python -m mlsvc.train --source dwh

# 3. Servir y probar
docker compose --profile analitica up -d ml
curl -s localhost:8002/metrics
curl -s -X POST localhost:8002/predict -H 'Content-Type: application/json' \
     -d '{"vehicle_code":"SIM-001","reference_datetime":"2026-11-10T14:30:00Z","origin_zone":"centro"}'
```

Con el `etl-scheduler` en marcha, el DWH se actualiza cada `ETL_INTERVAL_MIN`. Para reentrenar de forma periódica hay dos opciones: un cron del host, o un servicio análogo al `etl-scheduler` que corra `mlsvc.train --source dwh`, por ejemplo una vez al día, después de la corrida completa.

## 5. Criterios de aceptación del análisis

- [ ] El entrenamiento lee del DWH (`--source dwh`), nunca de Odoo ni de Traccar.
- [ ] La partición es temporal y `metrics.json` guarda la fecha de corte.
- [ ] Hay métricas separadas para REAL y SIMULADO, o se explica por qué solo hay una.
- [ ] El modelo supera los dos predictores base en accuracy y en F1 macro sobre el corte de prueba.
- [ ] La matriz de confusión y el top-3 se presentan en el BI o en el informe.
- [ ] `/predict` acepta todas las zonas que existen en `dim_zona` (M1).
- [ ] No se usa como variable nada que solo se conoce al terminar el viaje.


---

## 6. Pronóstico de demanda de artículos por ubicación (implementado)

Segunda pregunta del ML: **¿cuántas unidades de cada artículo se pedirán en cada ubicación en los próximos 7 días?** Código en `services/ml/mlsvc/demanda/`; no cambia `/predict` (destinos), que sigue usando Odoo.

- **Datos:** `v_ml_ventas_geo` (una fila por línea de pedido, con la ubicación aproximada del pedido a ~110 m: `fact_ventas.lat_aprox/lon_aprox`). El historial de demostración (Ambato, 3 meses de pedidos) lo carga el módulo `logistica_demo` en Odoo (`seeds/seed.py`), `seeds/gps_historico.py` manda el GPS de sus rutas a Traccar y el ETL lo lleva al DWH. Ese historial es sintético: el ETL marca `SIMULADO` sus pedidos (`client_order_ref` `H-*`/`HOY-*`) y sus rutas (`historial-demo`), igual que los viajes de `etl simulate`. El benchmark elige con `REAL` si hay días suficientes; si no, con `TODAS` (y si tampoco, `SIMULADO`).
- **Unidad espacial** (no solo la zona fija): celdas H3 (`h3:7/8/9`), KMeans (k por silueta), DBSCAN y la zona del DWH como referencia. `espacial.py`.
- **Variables sin fuga del futuro:** rezagos de 7, 14, 21 y 28 días (≥ horizonte), medias desplazadas, calendario de Ecuador (feriados, quincena y fin de mes), producto, categoría y ubicación de la unidad. `features.py`.
- **Evaluación:** backtest con origen móvil (3 cortes de 7 días al final), mismas series y cortes para todos los modelos. Métricas: **WAPE 7d (principal)**, WAPE 7d a nivel zona y total (las predicciones sumadas a producto × zona y a producto), mejora % frente al mejor baseline, WAPE diario, MAE, RMSE, MASE y sesgo.
- **Regla de elección** (`benchmark.elegir`): cada modelo se compara con el **mejor baseline** de su unidad (no solo con `estacional_7`). Es elegible si baja el WAPE 7d al menos 3 % (`BENCH_MEJORA_MIN`), su |sesgo| es ≤ 0,5 (`BENCH_SESGO_MAX`) y el servidor lo puede usar sin entrenar (modelo tabular global: baselines, Ridge, Poisson, árboles, MLP). Si ninguno lo es, se elige el mejor baseline y el informe lo dice. La unidad espacial se elige por el WAPE 7d **a nivel zona**, común a todas las unidades: el WAPE por serie favorece a la unidad más gruesa solo porque agrega más. A menos de 2 %, gana la unidad con más series.
- **El WAPE diario no decide:** los modelos de deep learning y el fundacional predicen casi cero (sesgo ≈ −0,9) y con conteos ralos eso parece un buen error diario. El sesgo los excluye.
- **Modelos comparados (24):** naive, estacional, medias móviles, Croston, SBA, TSB, ADIDA, AutoETS, AutoARIMA, Prophet, Ridge, Poisson, Random Forest, HistGB, XGBoost, LightGBM, CatBoost, MLP, LSTM, N-BEATS, N-HiTS, TFT y Chronos-Bolt (fundacional).

```bash
docker compose --profile etl run --rm etl bootstrap                  # tablas ml_*, vistas y rol dwh_ml
docker compose --profile historico run --rm gps-historico            # GPS de las rutas del historial en Traccar (el historial en Odoo lo carga `seed`)
docker compose --profile etl run --rm etl run --mode full
# EN LOCAL (el servidor no entrena). La imagen benchmark parte de la misma requirements.txt que producción.
docker compose --profile benchmark run --rm ml-benchmark            # tabla comparativa
docker compose --profile benchmark run --rm ml-benchmark python -m mlsvc.demanda.train --source dwh
# se commitean services/ml/models/demanda.joblib, demanda_metrics.json y services/ml/analisis/comparativa_modelos.*

# EN EL SERVIDOR (después de cada `etl run`): predice con sus datos, sin entrenar
docker compose --profile analitica run --rm ml-predecir
```

**Entrenar en local, predecir en el servidor.** `train` guarda en `demanda.joblib` el estimador ya ajustado, las series, el asignador espacial, las bandas p10/p90 y las versiones de las librerías. `mlsvc.demanda.predecir` (servicio `ml-predecir`) carga ese paquete, se detiene si las versiones instaladas no coinciden, lee las ventas del DWH del servidor, traduce los productos por su id de Odoo (el `producto_sk` de cada DWH es distinto), arma los rezagos y llama a `predict`: pronóstico de 7 días y un backtest de la última semana, sin `fit`. Escribe `models/demanda_prediccion.joblib` (lo usa `/demanda/predict`), `ml_pronostico_demanda`, `ml_unidad_espacial` y copia la comparativa a `ml_evaluacion_modelos`. `/demanda/health` dice qué versión hay, hasta qué día predijo el servidor y avisa si falta el modelo o las versiones difieren.

Resultados: `services/ml/analisis/comparativa_modelos.md` (también `.csv` y `.json`) y la tabla `ml_evaluacion_modelos`. Endpoints `/demanda/*` y vistas para dashboards: ver [guia_dashboard_web_powerbi.md](guia_dashboard_web_powerbi.md).

**Pendientes M3 y M4 de la sección 2:** resueltos para el modelo de demanda (escritura atómica y conexión por partes con `psycopg2.connect(**kwargs)`); `DWH_DSN` ya no existe.

**Poda:** tras revisar la tabla, dejar en `requirements.txt` solo lo que use el modelo ganador y borrar `requirements-benchmark.txt`, el target `benchmark` del `Dockerfile` y el servicio `ml-benchmark`. Conservar la tabla comparativa.

### Modelo elegido (corrida `20261119T041520Z`, 14 788 líneas de venta, 180 días)

**`media_dia_semana_8` (media del mismo día de la semana de las últimas 8 semanas) con clusters DBSCAN** (298 series
producto × cluster, 10 clusters): WAPE 7d 0,520; a nivel zona 0,391; por producto 0,182 (el menor de la tabla); sesgo
−0,076. Ningún modelo servible sin reentrenar la mejora en 3 % o más: LightGBM queda a 0,6 % en DBSCAN y a 2,6 % en
H3. Los modelos de deep learning y Chronos, entrenados en GPU con 1000 pasos, siguen prediciendo de menos (sesgo
≈ −0,6). El informe completo, con la tabla, la regla y la calidad de las predicciones (cobertura p10–p90 del 82 %
fuera de muestra, 70 % de los 10 productos principales con error semanal ≤ 20 %), está en
[informe_modelo_demanda.md](informe_modelo_demanda.md).
