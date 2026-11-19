# Comparativa de modelos de pronóstico de demanda por ubicación

Corrida `20261117T150751Z`. Backtest con origen móvil: 3 cortes de 7 días al final del histórico, mismas series (producto × unidad espacial) y mismos cortes para todos los modelos.

**Métrica principal: WAPE 7d** (error absoluto del total de los 7 días de cada serie / unidades reales; menor es mejor). WAPE = el mismo error medido día a día (más duro: el ruido diario de un conteo ralo no se compensa). MASE < 1: menos error que repetir la semana anterior. Sesgo > 0: sobreestima.

## Modelo elegido

**lightgbm_tweedie** (ml_arboles, librería lightgbm) con unidad espacial **dbscan**, procedencia REAL: WAPE 7d 0.517, WAPE diario 1.017, MAE 0.691, MASE 0.879.

Regla: menor WAPE entre los modelos que le ganan al estacional ingenuo (`estacional_7`); si otro queda a menos de 2 % del mejor y es más rápido, gana el más rápido. Los baselines son la referencia y no se eligen. La unidad se elige entre las basadas en coordenadas (H3, KMeans, DBSCAN); la zona del DWH es la referencia.

## REAL · unidad h3:8

| # | Modelo | Familia | Librería | WAPE 7d | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_arima | estadistico | statsforecast | 0.866 | 1.529 | 0.261 | 0.733 | 0.995 | -0.108 | 159.8 | 229 | ok |
| 2 | lightgbm_tweedie | ml_arboles | lightgbm | 0.873 | 1.524 | 0.260 | 0.735 | 0.992 | -0.095 | 8.5 | 11 | ok |
| 3 | xgboost_tweedie | ml_arboles | xgboost | 0.874 | 1.503 | 0.256 | 0.737 | 0.978 | -0.123 | 207.0 | 15 | ok |
| 4 | auto_ets | estadistico | statsforecast | 0.895 | 1.557 | 0.265 | 0.735 | 1.014 | -0.083 | 13.4 | 229 | ok |
| 5 | media_dia_semana_8 | baseline | propio (numpy) | 0.896 | 1.554 | 0.265 | 0.763 | 1.012 | -0.076 | 0.0 | 0 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.901 | 1.567 | 0.267 | 0.734 | 1.020 | -0.063 | 13.7 | 308 | ok |
| 7 | adida | intermitente | statsforecast | 0.903 | 1.553 | 0.265 | 0.737 | 1.011 | -0.082 | 8.4 | 229 | ok |
| 8 | ridge | ml_lineal | scikit-learn | 0.927 | 1.617 | 0.276 | 0.729 | 1.053 | -0.013 | 5.6 | 196 | ok |
| 9 | mlp | deep_learning | scikit-learn | 0.934 | 1.603 | 0.273 | 0.738 | 1.043 | -0.017 | 27.4 | 196 | ok |
| 10 | hist_gb_poisson | ml_arboles | scikit-learn | 0.936 | 1.636 | 0.279 | 0.743 | 1.065 | 0.042 | 9.4 | 196 | ok |
| 11 | media_movil_28 | baseline | propio (numpy) | 0.944 | 1.587 | 0.271 | 0.743 | 1.033 | -0.046 | 0.0 | 0 | ok |
| 12 | chronos_bolt | fundacional | chronos-forecasting | 0.958 | 1.041 | 0.177 | 0.784 | 0.677 | -0.893 | 16.4 | 792 | ok |
| 13 | lstm | deep_learning | neuralforecast | 0.973 | 1.006 | 0.172 | 0.791 | 0.655 | -0.945 | 6.6 | 951 | ok |
| 14 | tft | deep_learning | neuralforecast | 0.973 | 1.010 | 0.172 | 0.791 | 0.657 | -0.936 | 27.9 | 951 | ok |
| 15 | croston_sba | intermitente | statsforecast | 0.974 | 1.665 | 0.284 | 0.737 | 1.084 | 0.030 | 6.5 | 229 | ok |
| 16 | nbeats | deep_learning | neuralforecast | 0.982 | 1.010 | 0.172 | 0.793 | 0.657 | -0.954 | 14.3 | 951 | ok |
| 17 | nhits | deep_learning | neuralforecast | 0.985 | 1.012 | 0.173 | 0.794 | 0.659 | -0.954 | 14.6 | 951 | ok |
| 18 | croston | intermitente | statsforecast | 0.990 | 1.702 | 0.290 | 0.737 | 1.108 | 0.084 | 7.6 | 229 | ok |
| 19 | random_forest | ml_arboles | scikit-learn | 1.011 | 1.768 | 0.302 | 0.737 | 1.151 | 0.211 | 21.4 | 196 | ok |
| 20 | poisson_glm | ml_lineal | scikit-learn | 1.013 | 1.616 | 0.275 | 0.745 | 1.052 | 0.005 | 13.2 | 196 | ok |
| 21 | tsb | intermitente | statsforecast | 1.061 | 1.615 | 0.275 | 0.764 | 1.051 | -0.024 | 6.7 | 229 | ok |
| 22 | estacional_7 | baseline | propio (numpy) | 1.122 | 1.719 | 0.293 | 1.035 | 1.119 | -0.028 | 0.0 | 0 | ok |
| 23 | naive | baseline | propio (numpy) | 1.479 | 1.551 | 0.265 | 0.956 | 1.010 | -0.210 | 0.1 | 0 | ok |
|  | prophet | estadistico | prophet |  |  |  |  |  |  |  | 55 | omitido: 1188 series > limite 800 (modelo por serie, lento) |

## REAL · unidad kmeans

| # | Modelo | Familia | Librería | WAPE 7d | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | xgboost_tweedie | ml_arboles | xgboost | 0.650 | 1.234 | 0.572 | 1.225 | 0.913 | -0.151 | 46.3 | 15 | ok |
| 2 | auto_arima | estadistico | statsforecast | 0.651 | 1.284 | 0.595 | 1.222 | 0.950 | -0.096 | 63.8 | 229 | ok |
| 3 | lightgbm_tweedie | ml_arboles | lightgbm | 0.653 | 1.254 | 0.582 | 1.217 | 0.928 | -0.111 | 3.9 | 11 | ok |
| 4 | auto_ets | estadistico | statsforecast | 0.653 | 1.287 | 0.597 | 1.220 | 0.952 | -0.092 | 7.9 | 229 | ok |
| 5 | media_dia_semana_8 | baseline | propio (numpy) | 0.661 | 1.298 | 0.602 | 1.256 | 0.960 | -0.076 | 0.0 | 0 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.667 | 1.294 | 0.600 | 1.222 | 0.957 | -0.055 | 7.3 | 308 | ok |
| 7 | mlp | deep_learning | scikit-learn | 0.673 | 1.303 | 0.604 | 1.221 | 0.964 | -0.049 | 14.3 | 196 | ok |
| 8 | ridge | ml_lineal | scikit-learn | 0.673 | 1.328 | 0.616 | 1.207 | 0.983 | -0.014 | 2.5 | 196 | ok |
| 9 | hist_gb_poisson | ml_arboles | scikit-learn | 0.677 | 1.324 | 0.614 | 1.231 | 0.980 | -0.017 | 5.4 | 196 | ok |
| 10 | croston_sba | intermitente | statsforecast | 0.683 | 1.312 | 0.608 | 1.224 | 0.971 | -0.070 | 6.4 | 229 | ok |
| 11 | prophet | estadistico | prophet | 0.688 | 1.303 | 0.604 | 1.233 | 0.965 | -0.058 | 57.6 | 55 | ok |
| 12 | croston | intermitente | statsforecast | 0.690 | 1.335 | 0.619 | 1.225 | 0.988 | -0.021 | 6.6 | 229 | ok |
| 13 | adida | intermitente | statsforecast | 0.691 | 1.308 | 0.606 | 1.233 | 0.968 | -0.072 | 8.1 | 229 | ok |
| 14 | poisson_glm | ml_lineal | scikit-learn | 0.708 | 1.327 | 0.615 | 1.217 | 0.982 | -0.028 | 10.0 | 196 | ok |
| 15 | media_movil_28 | baseline | propio (numpy) | 0.710 | 1.321 | 0.612 | 1.233 | 0.978 | -0.046 | 0.0 | 0 | ok |
| 16 | random_forest | ml_arboles | scikit-learn | 0.712 | 1.406 | 0.652 | 1.219 | 1.041 | 0.115 | 7.8 | 196 | ok |
| 17 | tsb | intermitente | statsforecast | 0.818 | 1.367 | 0.634 | 1.276 | 1.012 | -0.014 | 7.0 | 229 | ok |
| 18 | chronos_bolt | fundacional | chronos-forecasting | 0.823 | 0.986 | 0.457 | 1.314 | 0.730 | -0.769 | 5.1 | 792 | ok |
| 19 | tft | deep_learning | neuralforecast | 0.867 | 0.970 | 0.450 | 1.330 | 0.718 | -0.805 | 28.0 | 951 | ok |
| 20 | lstm | deep_learning | neuralforecast | 0.872 | 0.965 | 0.447 | 1.332 | 0.714 | -0.823 | 3.4 | 951 | ok |
| 21 | estacional_7 | baseline | propio (numpy) | 0.882 | 1.514 | 0.702 | 1.705 | 1.120 | -0.028 | 0.0 | 0 | ok |
| 22 | nbeats | deep_learning | neuralforecast | 0.909 | 0.985 | 0.456 | 1.364 | 0.729 | -0.878 | 14.4 | 951 | ok |
| 23 | nhits | deep_learning | neuralforecast | 0.915 | 0.984 | 0.456 | 1.367 | 0.728 | -0.884 | 14.8 | 951 | ok |
| 24 | naive | baseline | propio (numpy) | 1.291 | 1.405 | 0.651 | 1.601 | 1.040 | -0.210 | 0.0 | 0 | ok |

## REAL · unidad dbscan

| # | Modelo | Familia | Librería | WAPE 7d | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_ets | estadistico | statsforecast | 0.513 | 1.068 | 0.726 | 1.469 | 0.923 | -0.085 | 6.4 | 229 | ok |
| 2 | auto_arima | estadistico | statsforecast | 0.516 | 1.066 | 0.725 | 1.464 | 0.922 | -0.088 | 51.2 | 229 | ok |
| 3 | lightgbm_tweedie ⭐ | ml_arboles | lightgbm | 0.517 | 1.017 | 0.691 | 1.444 | 0.879 | -0.087 | 3.6 | 11 | ok |
| 4 | media_dia_semana_8 | baseline | propio (numpy) | 0.520 | 1.067 | 0.725 | 1.500 | 0.922 | -0.076 | 0.0 | 0 | ok |
| 5 | ridge | ml_lineal | scikit-learn | 0.524 | 1.087 | 0.739 | 1.443 | 0.940 | -0.018 | 1.6 | 196 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.524 | 1.056 | 0.718 | 1.452 | 0.913 | -0.043 | 6.5 | 308 | ok |
| 7 | hist_gb_poisson | ml_arboles | scikit-learn | 0.526 | 1.075 | 0.731 | 1.451 | 0.929 | 0.007 | 3.0 | 196 | ok |
| 8 | prophet | estadistico | prophet | 0.527 | 1.064 | 0.723 | 1.463 | 0.920 | -0.059 | 35.8 | 55 | ok |
| 9 | croston_sba | intermitente | statsforecast | 0.530 | 1.076 | 0.731 | 1.470 | 0.930 | -0.079 | 6.3 | 229 | ok |
| 10 | xgboost_tweedie | ml_arboles | xgboost | 0.533 | 1.010 | 0.686 | 1.465 | 0.873 | -0.146 | 432.2 | 15 | ok |
| 11 | mlp | deep_learning | scikit-learn | 0.535 | 1.099 | 0.747 | 1.432 | 0.950 | 0.028 | 11.1 | 196 | ok |
| 12 | croston | intermitente | statsforecast | 0.535 | 1.092 | 0.742 | 1.469 | 0.944 | -0.030 | 6.4 | 229 | ok |
| 13 | adida | intermitente | statsforecast | 0.537 | 1.073 | 0.730 | 1.473 | 0.928 | -0.062 | 7.7 | 229 | ok |
| 14 | random_forest | ml_arboles | scikit-learn | 0.551 | 1.134 | 0.771 | 1.448 | 0.980 | 0.092 | 5.5 | 196 | ok |
| 15 | media_movil_28 | baseline | propio (numpy) | 0.553 | 1.079 | 0.734 | 1.469 | 0.933 | -0.046 | 0.0 | 0 | ok |
| 16 | poisson_glm | ml_lineal | scikit-learn | 0.554 | 1.067 | 0.725 | 1.452 | 0.922 | -0.014 | 17.0 | 196 | ok |
| 17 | tsb | intermitente | statsforecast | 0.633 | 1.114 | 0.757 | 1.518 | 0.963 | -0.020 | 6.3 | 229 | ok |
| 18 | chronos_bolt | fundacional | chronos-forecasting | 0.635 | 0.860 | 0.584 | 1.558 | 0.743 | -0.585 | 4.7 | 792 | ok |
| 19 | tft | deep_learning | neuralforecast | 0.645 | 0.855 | 0.581 | 1.557 | 0.739 | -0.573 | 28.3 | 951 | ok |
| 20 | lstm | deep_learning | neuralforecast | 0.651 | 0.852 | 0.579 | 1.564 | 0.736 | -0.593 | 3.5 | 951 | ok |
| 21 | nbeats | deep_learning | neuralforecast | 0.670 | 0.859 | 0.584 | 1.586 | 0.742 | -0.621 | 14.0 | 951 | ok |
| 22 | estacional_7 | baseline | propio (numpy) | 0.687 | 1.287 | 0.875 | 2.055 | 1.112 | -0.028 | 0.0 | 0 | ok |
| 23 | nhits | deep_learning | neuralforecast | 0.771 | 0.896 | 0.609 | 1.714 | 0.774 | -0.735 | 15.1 | 951 | ok |
| 24 | naive | baseline | propio (numpy) | 1.051 | 1.195 | 0.812 | 1.962 | 1.033 | -0.210 | 0.0 | 0 | ok |

## REAL · unidad zona

| # | Modelo | Familia | Librería | WAPE 7d | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_ets | estadistico | statsforecast | 0.451 | 1.013 | 0.978 | 1.818 | 0.920 | -0.086 | 6.0 | 229 | ok |
| 2 | auto_arima | estadistico | statsforecast | 0.452 | 1.013 | 0.977 | 1.815 | 0.919 | -0.095 | 45.8 | 229 | ok |
| 3 | ridge | ml_lineal | scikit-learn | 0.455 | 1.023 | 0.987 | 1.784 | 0.928 | -0.021 | 1.2 | 196 | ok |
| 4 | lightgbm_tweedie | ml_arboles | lightgbm | 0.455 | 0.980 | 0.945 | 1.780 | 0.889 | -0.079 | 2.6 | 11 | ok |
| 5 | media_dia_semana_8 | baseline | propio (numpy) | 0.455 | 1.026 | 0.989 | 1.872 | 0.931 | -0.076 | 0.0 | 0 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.455 | 1.005 | 0.969 | 1.788 | 0.912 | -0.033 | 5.9 | 308 | ok |
| 7 | xgboost_tweedie | ml_arboles | xgboost | 0.462 | 0.975 | 0.940 | 1.795 | 0.885 | -0.092 | 250.9 | 15 | ok |
| 8 | mlp | deep_learning | scikit-learn | 0.463 | 1.007 | 0.971 | 1.767 | 0.913 | -0.032 | 8.6 | 196 | ok |
| 9 | hist_gb_poisson | ml_arboles | scikit-learn | 0.467 | 1.020 | 0.984 | 1.781 | 0.926 | -0.012 | 2.3 | 196 | ok |
| 10 | prophet | estadistico | prophet | 0.468 | 1.013 | 0.977 | 1.815 | 0.920 | -0.062 | 28.7 | 55 | ok |
| 11 | poisson_glm | ml_lineal | scikit-learn | 0.477 | 1.015 | 0.979 | 1.786 | 0.921 | -0.017 | 13.2 | 196 | ok |
| 12 | random_forest | ml_arboles | scikit-learn | 0.480 | 1.056 | 1.018 | 1.785 | 0.958 | 0.047 | 4.2 | 196 | ok |
| 13 | croston_sba | intermitente | statsforecast | 0.483 | 1.023 | 0.986 | 1.836 | 0.928 | -0.087 | 7.5 | 229 | ok |
| 14 | croston | intermitente | statsforecast | 0.483 | 1.036 | 0.999 | 1.834 | 0.940 | -0.039 | 8.7 | 229 | ok |
| 15 | adida | intermitente | statsforecast | 0.486 | 1.031 | 0.994 | 1.840 | 0.935 | -0.052 | 10.0 | 229 | ok |
| 16 | media_movil_28 | baseline | propio (numpy) | 0.487 | 1.031 | 0.995 | 1.825 | 0.936 | -0.046 | 0.0 | 0 | ok |
| 17 | tsb | intermitente | statsforecast | 0.569 | 1.066 | 1.028 | 1.893 | 0.967 | -0.014 | 7.3 | 229 | ok |
| 18 | chronos_bolt | fundacional | chronos-forecasting | 0.589 | 0.855 | 0.825 | 1.915 | 0.776 | -0.534 | 4.3 | 792 | ok |
| 19 | estacional_7 | baseline | propio (numpy) | 0.600 | 1.242 | 1.198 | 2.532 | 1.128 | -0.028 | 0.0 | 0 | ok |
| 20 | nbeats | deep_learning | neuralforecast | 0.615 | 0.861 | 0.831 | 1.941 | 0.781 | -0.549 | 13.9 | 951 | ok |
| 21 | tft | deep_learning | neuralforecast | 0.621 | 0.861 | 0.830 | 1.941 | 0.781 | -0.546 | 26.3 | 951 | ok |
| 22 | lstm | deep_learning | neuralforecast | 0.622 | 0.859 | 0.829 | 1.941 | 0.780 | -0.547 | 3.9 | 951 | ok |
| 23 | nhits | deep_learning | neuralforecast | 0.736 | 0.894 | 0.862 | 2.091 | 0.811 | -0.694 | 14.6 | 951 | ok |
| 24 | naive | baseline | propio (numpy) | 1.016 | 1.180 | 1.138 | 2.427 | 1.071 | -0.210 | 0.0 | 0 | ok |

## Familias de modelos

- **baseline**: Reglas simples sin aprendizaje: el piso que cualquier modelo debe superar.
- **intermitente**: Metodos clasicos para demanda con muchos dias en cero (Croston y variantes).
- **estadistico**: Modelos de series de tiempo por serie: suavizado exponencial, ARIMA, Prophet.
- **ml_lineal**: Regresiones globales (una para todas las series) con variables de calendario y rezagos.
- **ml_arboles**: Ensambles de arboles globales; manejan bien ceros, no linealidades e interacciones.
- **deep_learning**: Redes neuronales: MLP sobre las variables y redes de series (LSTM, N-BEATS, N-HiTS, TFT).
- **fundacional**: Modelo preentrenado con millones de series (zero-shot): no se entrena con estos datos.

## Modelos

- `naive` (propio (numpy)): Repite el ultimo dia observado.
- `estacional_7` (propio (numpy)): Mismo dia de la semana anterior (referencia para comparar: MASE y la regla de eleccion).
- `media_movil_28` (propio (numpy)): Media de los ultimos 28 dias.
- `media_dia_semana_8` (propio (numpy)): Media del mismo dia de la semana en las ultimas 8 semanas.
- `croston` (statsforecast): Croston clasico para demanda intermitente.
- `croston_sba` (statsforecast): Croston con correccion de sesgo de Syntetos-Boylan.
- `tsb` (statsforecast): Teunter-Syntetos-Babai (probabilidad de venta).
- `adida` (statsforecast): Agregacion temporal para demanda intermitente.
- `auto_ets` (statsforecast): Suavizado exponencial con estacionalidad semanal.
- `auto_arima` (statsforecast): ARIMA estacional elegido automaticamente.
- `prophet` (prophet): Tendencia + estacionalidad semanal + feriados de Ecuador (una regresion por serie).
- `ridge` (scikit-learn): Regresion lineal regularizada (global).
- `poisson_glm` (scikit-learn): Regresion de Poisson (conteos).
- `random_forest` (scikit-learn): Bosque aleatorio (global).
- `hist_gb_poisson` (scikit-learn): Gradient boosting por histogramas con perdida de Poisson.
- `xgboost_tweedie` (xgboost): XGBoost con perdida Tweedie (conteos con muchos ceros).
- `lightgbm_tweedie` (lightgbm): LightGBM con perdida Tweedie (el enfoque ganador del M5).
- `catboost_tweedie` (catboost): CatBoost con perdida Tweedie.
- `mlp` (scikit-learn): Red neuronal densa (perceptron multicapa) sobre las mismas variables.
- `lstm` (neuralforecast): Red recurrente LSTM (PyTorch).
- `nbeats` (neuralforecast): N-BEATS: bloques densos con descomposicion en tendencia y estacionalidad.
- `nhits` (neuralforecast): N-HiTS: N-BEATS jerarquico por frecuencias.
- `tft` (neuralforecast): Temporal Fusion Transformer (atencion).
- `chronos_bolt` (chronos-forecasting): Modelo fundacional preentrenado (zero-shot, sin entrenar con estos datos).
