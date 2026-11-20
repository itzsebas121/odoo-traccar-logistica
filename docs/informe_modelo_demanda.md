# Informe: elección del modelo de pronóstico de demanda

**Pregunta:** ¿cuántas unidades de cada producto se pedirán en cada zona de Ambato en los próximos 7 días?

**Resultado:** se despliega la **media del mismo día de la semana de las últimas 8 semanas** (`media_dia_semana_8`),
calculada por **clusters DBSCAN** de ubicación de los clientes. Se compararon 24 modelos en 4 formas de dividir la
ciudad. Ningún modelo de aprendizaje automático que el servidor pueda usar sin reentrenar la mejoró en al menos 3 %. A
nivel de producto y semana, acierta el volumen con un error del 18 %, y en 7 de cada 10 productos más vendidos el error
semanal queda dentro de ±20 %.

| Dato | Valor |
|---|---|
| Corrida de la comparativa | `20261119T041520Z` (tabla completa: `services/ml/analisis/comparativa_modelos.md`) |
| Datos | 14 788 líneas de venta reales, 21-may-2026 a 16-nov-2026 (180 días), 30 productos |
| Series evaluadas | producto × unidad espacial: 1188 (H3), 437 (KMeans, k = 15), 298 (DBSCAN, 10 clusters), 210 (zona) |
| Validación | 3 cortes de 7 días al final del histórico (27-oct, 3-nov y 10-nov), sin mezclar pasado y futuro |
| Hardware | CPU para los modelos estadísticos y tabulares; GPU NVIDIA RTX 5070 para los de PyTorch (LSTM, N-BEATS, N-HiTS, TFT, Chronos), con 1000 pasos de entrenamiento |
| Modelo desplegado | `20261119143010-media_dia_semana_8-12ada628` en `services/ml/models/demanda.joblib` |

## 1. Cómo se midió

Para cada corte se entrena con los días anteriores y se pronostican los 7 siguientes, que el modelo no ha visto. Todos
los modelos usan las mismas series y los mismos cortes.

| Métrica | Qué mide | Por qué importa |
|---|---|---|
| **WAPE 7d** (principal) | Error del total de la semana de cada serie ÷ unidades vendidas | Es lo que se planifica: compras y rutas de la semana. |
| **WAPE 7d zona / total** | Lo mismo tras sumar el pronóstico a producto × zona, y a producto | Nivel común para comparar unidades espaciales de distinto tamaño. |
| **Mejora %** | Cuánto baja el WAPE 7d frente al **mejor** modelo simple de la misma unidad | Un modelo complejo solo vale la pena si mejora claramente lo simple. |
| **Sesgo** | (pronóstico − real) ÷ real, en total | Negativo = se queda corto; cerca de −1 = predice casi cero. |
| WAPE día, MASE | Error día a día | Se informa, pero **no decide**: con ventas ralas, predecir cero parece bueno día a día. |

## 2. Regla de elección

1. Se compara cada modelo con el **mejor baseline** de su unidad (no con el más débil). Los baselines son reglas fijas
   sin aprendizaje: repetir el último día, la semana anterior, la media de 28 días y la media del mismo día de la
   semana.
2. Un modelo es candidato si cumple las tres condiciones:
   - mejora el WAPE 7d al menos **3 %**;
   - su **|sesgo| es ≤ 0,5**;
   - **el servidor lo puede usar sin entrenar**. Esto se cumple con los modelos tabulares globales: el estimador se guarda
     ya entrenado y el servidor solo llama a `predict`. Los modelos por serie (ARIMA, ETS, Croston, Prophet, redes de
     series, Chronos) se ajustan cada vez que predicen, así que no lo cumplen.
3. Si ningún modelo es candidato, se despliega el mejor baseline.
4. La unidad espacial se elige por el **WAPE 7d a nivel zona**. Por serie, la unidad más gruesa siempre parece mejor
   solo porque suma más ventas.

## 3. Resultados por unidad espacial

| Unidad | Series | Mejor baseline (WAPE 7d) | Mejor modelo servible (WAPE 7d, mejora) | Mejor modelo en general (WAPE 7d, mejora) | WAPE 7d zona del baseline |
|---|---|---|---|---|---|
| h3:8 | 1188 | media_dia_semana_8 (0,896) | lightgbm_tweedie (0,873, 2,6 %) | auto_arima (0,866, 3,3 %) | 0,451 |
| kmeans | 437 | media_dia_semana_8 (0,661) | xgboost_tweedie (0,650, 1,6 %) | xgboost_tweedie (0,650, 1,6 %) | 0,413 |
| **dbscan** | 298 | **media_dia_semana_8 (0,520)** | lightgbm_tweedie (0,517, 0,6 %) | auto_ets (0,513, 1,4 %) | **0,391** |
| zona | 210 | media_dia_semana_8 (0,455) | ridge (0,455, 0,1 %) | auto_ets (0,451, 0,8 %) | 0,455 |

- **DBSCAN gana como unidad.** Tiene el menor error a nivel zona (0,391), mejor que KMeans (0,413), H3 (0,451) y que la
  propia zona del DWH (0,455). Se adapta a dónde están los clientes en lugar de usar una cuadrícula o límites fijos.
- **En ninguna unidad un modelo servible mejora 3 % al baseline.** El más cercano es LightGBM en H3, con 2,6 %.
  AutoARIMA llega a 3,3 % en H3, pero se ajusta al predecir, y el servidor no entrena.

## 4. Tabla completa en la unidad elegida (DBSCAN)

| # | Modelo | Familia | WAPE 7d | 7d zona | 7d total | Mejora % | Sesgo | WAPE día | MASE | Seg. | ¿Servible sin reentrenar? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_ets | estadistico | 0,513 | 0,389 | 0,194 | 1,4 | -0,085 | 1,068 | 0,923 | 15,0 | no |
| 2 | auto_arima | estadistico | 0,516 | 0,384 | 0,194 | 0,7 | -0,088 | 1,066 | 0,922 | 79,2 | no |
| 3 | lightgbm_tweedie | ml_arboles | 0,517 | 0,391 | 0,210 | 0,6 | -0,087 | 1,017 | 0,879 | 8,5 | sí |
| 4 | **media_dia_semana_8** ⭐ | baseline | 0,520 | 0,391 | **0,182** | 0,0 | -0,076 | 1,067 | 0,922 | 0,0 | sí |
| 5 | ridge | ml_lineal | 0,524 | 0,389 | 0,188 | -0,7 | -0,018 | 1,087 | 0,940 | 2,5 | sí |
| 6 | catboost_tweedie | ml_arboles | 0,524 | 0,393 | 0,204 | -0,8 | -0,043 | 1,056 | 0,913 | 13,4 | sí |
| 7 | hist_gb_poisson | ml_arboles | 0,526 | 0,392 | 0,183 | -1,2 | 0,007 | 1,075 | 0,929 | 9,7 | sí |
| 8 | prophet | estadistico | 0,527 | 0,395 | 0,185 | -1,3 | -0,059 | 1,064 | 0,920 | 66,3 | no |
| 9 | croston_sba | intermitente | 0,530 | 0,404 | 0,202 | -2,0 | -0,079 | 1,076 | 0,930 | 15,9 | no |
| 10 | xgboost_tweedie | ml_arboles | 0,533 | 0,416 | 0,247 | -2,4 | -0,146 | 1,010 | 0,873 | 7,0 | sí |
| 11 | mlp | deep_learning | 0,535 | 0,396 | 0,201 | -2,9 | 0,028 | 1,099 | 0,950 | 14,5 | sí |
| 12 | croston | intermitente | 0,535 | 0,407 | 0,198 | -3,0 | -0,030 | 1,092 | 0,944 | 15,5 | no |
| 13 | adida | intermitente | 0,537 | 0,407 | 0,203 | -3,2 | -0,062 | 1,073 | 0,928 | 22,4 | no |
| 14 | random_forest | ml_arboles | 0,551 | 0,407 | 0,208 | -5,9 | 0,092 | 1,134 | 0,980 | 10,1 | sí |
| 15 | media_movil_28 | baseline | 0,553 | 0,409 | 0,191 | -6,4 | -0,046 | 1,079 | 0,933 | 0,0 | sí |
| 16 | poisson_glm | ml_lineal | 0,554 | 0,407 | 0,214 | -6,6 | -0,014 | 1,067 | 0,922 | 26,3 | sí |
| 17 | tsb | intermitente | 0,633 | 0,472 | 0,247 | -21,7 | -0,020 | 1,114 | 0,963 | 17,4 | no |
| 18 | chronos_bolt | fundacional | 0,635 | 0,603 | 0,585 | -22,2 | -0,585 | 0,860 | 0,743 | 3,7 | no |
| 19 | tft | deep_learning | 0,649 | 0,608 | 0,586 | -24,8 | -0,586 | 0,855 | 0,739 | 75,2 | no |
| 20 | lstm | deep_learning | 0,651 | 0,612 | 0,594 | -25,3 | -0,594 | 0,851 | 0,736 | 42,1 | no |
| 21 | nbeats | deep_learning | 0,671 | 0,625 | 0,596 | -29,0 | -0,596 | 0,870 | 0,752 | 42,0 | no |
| 22 | nhits | deep_learning | 0,674 | 0,604 | 0,563 | -29,6 | -0,561 | 0,867 | 0,749 | 44,3 | no |
| 23 | estacional_7 | baseline | 0,687 | 0,509 | 0,287 | -32,1 | -0,028 | 1,287 | 1,112 | 0,0 | sí |
| 24 | naive | baseline | 1,051 | 0,900 | 0,559 | -102,1 | -0,210 | 1,195 | 1,033 | 0,0 | sí |

*Seg.: segundos de entrenamiento y predicción en los 3 cortes.*

**Lectura:**
- **Los 16 primeros quedan a menos de 8 % entre sí.** Con estos datos hay poca señal extra que aprender más allá
  del patrón semanal. Las ventas dependen sobre todo del día de la semana, y eso ya lo captura la media del mismo día.
- **El baseline elegido tiene el menor error por producto y semana de toda la tabla** (7d total 0,182). LightGBM queda
  en 0,210 y XGBoost en 0,247.
- **Las redes profundas y Chronos predicen de menos.** Tienen sesgo entre −0,56 y −0,60, es decir, pronostican alrededor
  de la mitad de lo que se vende. Ganan en WAPE diario (0,85) solo porque predecir poco parece bueno cuando la mayoría de
  los días una serie vende 0 o 1 unidad. Con la GPU y 1000 pasos de entrenamiento siguió igual, así que no es falta de
  entrenamiento.

## 5. Qué tan buenas son las predicciones

Medido sobre los 3 cortes, en semanas que el modelo no vio. La tabla compara con LightGBM, el mejor modelo de
aprendizaje automático servible.

| Indicador | media_dia_semana_8 (elegido) | lightgbm_tweedie |
|---|---|---|
| Precisión del volumen por producto y semana (1 − WAPE) | **81,8 %** | 79,0 % |
| Productos con error semanal ≤ 20 % | **51 %** | 49 % |
| Productos con error semanal ≤ 30 % | **69 %** | 66 % |
| Top 10 productos con error semanal ≤ 20 % | **70 %** | 63 % |
| Error del total de la tienda por semana (cortes 1, 2, 3) | 13,5 % · 6,7 % · **2,0 %** | 15,8 % · 13,2 % · 3,8 % |
| Sesgo total | −7,6 % (se queda un poco corto) | −8,7 % |
| Cobertura de la banda p10–p90, por serie y día (meta 80 %) | **82,4 %** | 78,8 % |

La banda p10–p90 se calibró con los cortes 1 y 2 y se midió en el corte 3. Que cubra el 82 % de los días cuando la
meta es el 80 % significa que el rango probable que muestra el tablero es fiable.

**Última semana evaluada (10 al 16 de noviembre), 10 productos más vendidos:**

| Producto | Vendido | Pronóstico | Error |
|---|---|---|---|
| Leche entera funda 1 L | 141 | 144,6 | +2,6 % |
| Arroz blanco grano largo 2 kg | 113 | 119,0 | +5,3 % |
| Azúcar blanca 2 kg | 82 | 82,0 | 0,0 % |
| Papel higiénico paquete 4 rollos | 73 | 80,8 | +10,6 % |
| Aceite vegetal 1 L | 82 | 70,5 | −14,0 % |
| Fideo tallarín 400 g | 84 | 64,0 | −23,8 % |
| Atún en aceite lata 180 g | 64 | 69,0 | +7,8 % |
| Huevos cubeta 30 unidades | 44 | 53,4 | +21,3 % |
| Detergente en polvo 1 kg | 45 | 46,3 | +2,8 % |
| Queso fresco 500 g | 68 | 41,6 | −38,8 % |

Siete de los diez quedan dentro de ±15 %. Los desvíos grandes (queso, fideo) son semanas con picos que no seguían el
patrón de las 8 semanas anteriores.

**Hasta dónde llega:**
- El error **por serie** (producto × cluster, WAPE 7d 0,52) es alto, porque cada serie vende pocas unidades por semana.
  El modelo sirve para planificar **por producto y por zona** (errores de 18 % y 39 %), no unidad por unidad en cada
  punto de la ciudad.
- Al ser una media de 8 semanas, reacciona con retraso a cambios bruscos: promociones, un producto nuevo o un feriado
  que no se repite. Los productos sin ventas en un cluster se pronostican en 0.
- El sesgo de −7,6 % indica que tiende a quedarse un poco corto. Para compras conviene mirar el p90 de la banda.

## 6. Cómo se usa (entrenar en local, predecir en el servidor)

```bash
# Local (con GPU para los modelos de PyTorch; sin compose.gpu.yaml corre todo en CPU)
docker compose -f compose.yaml -f compose.gpu.yaml --profile benchmark run --rm ml-benchmark
docker compose --profile benchmark run --rm ml-benchmark python -m mlsvc.demanda.train --source dwh
# se suben services/ml/models/demanda.joblib, demanda_metrics.json, SHA256SUMS y services/ml/analisis/comparativa_modelos.*
# (el entrenamiento actualiza SHA256SUMS; el servidor no carga un .joblib cuyo hash no coincida con él)

# Servidor: solo predice. Lo hace solo el servicio ml-programado (cada ML_PREDECIR_MIN minutos); a mano:
docker compose --profile analitica run --rm ml-predecir
```

- **El servidor no entrena.** `ml-programado` (o `ml-predecir` a mano) carga el paquete, comprueba que las versiones
  de las librerías coincidan, lee las ventas de su propio DWH y calcula los 7 días desde hoy. Con un baseline la regla
  es fija; con un modelo tabular sería `predict`, sin `fit`. Hay una prueba automática que falla si en ese camino se
  llama a `fit`.
- **Pronostica todo lo del servidor**, no solo lo que vio al entrenar. Un producto nuevo (id de Odoo que el modelo no
  conoce) se pronostica con su propia historia. Una venta lejos de todo lo que el modelo conoció (más de 1,5 km del
  punto de entrenamiento más cercano en `dbscan`) no se fuerza a una unidad lejana: forma una unidad nueva
  (`s<lat>_<lon>`) con el centro y el contorno de sus pedidos. Las coordenadas son las exactas de Odoo, sin redondear.
- **El pronóstico se ve en tres sitios:**
  - el **Tablero** del asistente, pestaña *Pronóstico* (real frente a pronóstico, con la banda);
  - `/demanda/predict` del servicio `ml`;
  - la vista `v_bi_demanda_real_vs_pronostico`.
- **Cambiar de modelo** sin rehacer la comparativa:
  `python -m mlsvc.demanda.train --modelo lightgbm_tweedie --unidad dbscan`. LightGBM queda a 0,6 % del baseline: es la
  opción si se prefiere un modelo que use calendario, feriados y ubicación como variables. Con más meses de historia
  podría superarlo.
- **Repetir la comparativa** cada vez que haya bastantes datos nuevos (por ejemplo, cada mes). La regla es la misma, así
  que si un modelo de aprendizaje automático empieza a ganar por más de 3 %, se elige solo.

## 7. Despliegue en el servidor (en este orden)

El modelo ya viene entrenado en el repo. En el servidor no se entrena nada. En el entorno del servidor (Dokploy:
*Environment*) deben estar `DWH_DB_PASSWORD`, `DWH_ETL_PASSWORD`, `ETL_STG_PASSWORD` y `DWH_ML_PASSWORD`. Con eso
basta un redespliegue:

- `etl-scheduler` corre `etl bootstrap` (sin `--reset`: agrega tablas `ml_*`, vistas `v_bi_*` y roles) y carga el DWH;
- `ml-programado` calcula el pronóstico con el modelo entrenado y lo guarda en el DWH.

A mano, si hiciera falta:

```bash
docker compose --profile etl run --rm etl bootstrap           # SIN --reset
docker compose --profile etl run --rm etl run --mode full
docker compose --profile analitica run --rm ml-predecir       # pronóstico con el modelo entrenado; no entrena
```

Comprobaciones:

- `curl -s http://127.0.0.1:8002/demanda/health`: `"status": "ok"` y `prediccion_servidor` con fecha. Si dice `error`,
  el archivo `demanda.joblib` no coincide con `SHA256SUMS` y el servicio no lo carga: vuelva a subir el par completo.
- `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/demanda/comparativa`: `200`.
- Tablero, pestaña *Pronóstico* (asistente y Odoo): con datos. Si sale vacía, revise los registros de
  `ml-programado`: avisan si falta `DWH_ML_PASSWORD` o si el DWH aún no tiene ventas.

Notas:

- `ml-programado` recalcula el pronóstico cada `ML_PREDECIR_MIN` minutos (60 por defecto).
- `models/demanda_prediccion.joblib` lo genera el servidor con sus propios datos. No va en el repo y no está en
  `SHA256SUMS`, porque no sale de una revisión.
- Reentrenar o cambiar de modelo se hace en local. Hay que subir juntos `demanda.joblib`, `demanda_metrics.json` y
  `SHA256SUMS`.
