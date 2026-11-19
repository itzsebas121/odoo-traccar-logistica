# Comparativa de modelos de pronóstico de demanda por ubicación

Corrida `20261119T041520Z`. Backtest con origen móvil: 3 cortes de 7 días al final del histórico, mismas series (producto × unidad espacial) y mismos cortes para todos los modelos.

**Métrica principal: WAPE 7d** (error absoluto del total de los 7 días de cada serie / unidades reales; menor es mejor). **7d zona / 7d total**: el mismo error tras sumar las predicciones a producto × zona del DWH y a producto; es el nivel común para comparar unidades espaciales de distinto tamaño. **Mejora %**: cuánto baja el WAPE 7d frente al mejor baseline de la misma unidad. WAPE día = el error día a día: **no decide**, porque un modelo que predice casi cero gana ahí con conteos ralos (se le ve en el sesgo, cerca de −1). MASE < 1: menos error que repetir la semana anterior. Sesgo > 0: sobreestima.

## Modelo elegido

**media_dia_semana_8** (baseline, librería propio (numpy)) con unidad espacial **dbscan**, procedencia REAL: WAPE 7d 0.520 (zona 0.391, total 0.182), mejora 0.0 % sobre el mejor baseline, WAPE diario 1.067, MAE 0.725, MASE 0.922, sesgo -0.076.

**Por qué:** Ningun modelo mejora al mejor baseline en al menos 3 % de WAPE 7d con |sesgo| <= 0.50: se elige el baseline media_dia_semana_8.

Regla: cada modelo se compara con el **mejor baseline** de su unidad y procedencia. Es elegible si baja el WAPE 7d al menos 3 %, su |sesgo| es ≤ 0.50 y se puede servir sin reentrenar (modelo tabular global: el servidor solo predice); entre los elegibles gana el de menor WAPE 7d (a menos de 2 %, el más rápido). Si ninguno lo es, se elige el baseline. La unidad se elige entre las basadas en coordenadas (H3, KMeans, DBSCAN) por el WAPE 7d a nivel zona (a menos de 2 %, la de más series); la zona del DWH es la referencia.

## REAL · unidad h3:8

| # | Modelo | Familia | Librería | WAPE 7d | 7d zona | 7d total | Mejora % | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_arima | estadistico | statsforecast | 0.866 | 0.441 | 0.188 | 3.3 | 1.529 | 0.261 | 0.733 | 0.995 | -0.108 | 255.8 | 229 | ok |
| 2 | lightgbm_tweedie | ml_arboles | lightgbm | 0.873 | 0.440 | 0.199 | 2.6 | 1.524 | 0.260 | 0.735 | 0.992 | -0.095 | 16.8 | 11 | ok |
| 3 | xgboost_tweedie | ml_arboles | xgboost | 0.874 | 0.451 | 0.225 | 2.5 | 1.503 | 0.256 | 0.737 | 0.978 | -0.123 | 16.5 | 15 | ok |
| 4 | auto_ets | estadistico | statsforecast | 0.895 | 0.453 | 0.191 | 0.2 | 1.557 | 0.265 | 0.735 | 1.014 | -0.083 | 30.0 | 229 | ok |
| 5 | media_dia_semana_8 | baseline | propio (numpy) | 0.896 | 0.451 | 0.182 | 0.0 | 1.554 | 0.265 | 0.763 | 1.012 | -0.076 | 0.1 | 0 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.901 | 0.444 | 0.200 | -0.5 | 1.567 | 0.267 | 0.734 | 1.020 | -0.063 | 23.7 | 308 | ok |
| 7 | adida | intermitente | statsforecast | 0.903 | 0.459 | 0.195 | -0.7 | 1.553 | 0.265 | 0.737 | 1.011 | -0.082 | 16.1 | 229 | ok |
| 8 | ridge | ml_lineal | scikit-learn | 0.927 | 0.444 | 0.190 | -3.5 | 1.617 | 0.276 | 0.729 | 1.053 | -0.013 | 5.9 | 196 | ok |
| 9 | mlp | deep_learning | scikit-learn | 0.934 | 0.472 | 0.239 | -4.2 | 1.603 | 0.273 | 0.738 | 1.043 | -0.017 | 50.3 | 196 | ok |
| 10 | hist_gb_poisson | ml_arboles | scikit-learn | 0.936 | 0.470 | 0.191 | -4.4 | 1.636 | 0.279 | 0.743 | 1.065 | 0.042 | 19.3 | 196 | ok |
| 11 | media_movil_28 | baseline | propio (numpy) | 0.944 | 0.486 | 0.191 | -5.4 | 1.587 | 0.271 | 0.743 | 1.033 | -0.046 | 0.1 | 0 | ok |
| 12 | chronos_bolt | fundacional | chronos-forecasting | 0.958 | 0.920 | 0.893 | -6.9 | 1.041 | 0.177 | 0.784 | 0.677 | -0.893 | 18.6 | 2059 | ok |
| 13 | lstm | deep_learning | neuralforecast | 0.973 | 0.945 | 0.945 | -8.6 | 1.006 | 0.172 | 0.791 | 0.655 | -0.945 | 78.0 | 2202 | ok |
| 14 | croston_sba | intermitente | statsforecast | 0.974 | 0.486 | 0.206 | -8.7 | 1.665 | 0.284 | 0.737 | 1.084 | 0.030 | 12.6 | 229 | ok |
| 15 | tft | deep_learning | neuralforecast | 0.980 | 0.931 | 0.922 | -9.3 | 1.025 | 0.175 | 0.790 | 0.667 | -0.922 | 96.3 | 2202 | ok |
| 16 | nbeats | deep_learning | neuralforecast | 0.983 | 0.964 | 0.964 | -9.7 | 1.006 | 0.171 | 0.794 | 0.655 | -0.964 | 118.7 | 2202 | ok |
| 17 | nhits | deep_learning | neuralforecast | 0.983 | 0.966 | 0.966 | -9.7 | 1.004 | 0.171 | 0.794 | 0.654 | -0.966 | 53.5 | 2202 | ok |
| 18 | croston | intermitente | statsforecast | 0.990 | 0.500 | 0.216 | -10.5 | 1.702 | 0.290 | 0.737 | 1.108 | 0.084 | 11.6 | 229 | ok |
| 19 | random_forest | ml_arboles | scikit-learn | 1.011 | 0.533 | 0.274 | -12.7 | 1.768 | 0.302 | 0.737 | 1.151 | 0.211 | 33.6 | 196 | ok |
| 20 | poisson_glm | ml_lineal | scikit-learn | 1.013 | 0.472 | 0.217 | -13.0 | 1.616 | 0.275 | 0.745 | 1.052 | 0.005 | 15.3 | 196 | ok |
| 21 | tsb | intermitente | statsforecast | 1.061 | 0.564 | 0.253 | -18.4 | 1.615 | 0.275 | 0.764 | 1.051 | -0.024 | 13.4 | 229 | ok |
| 22 | estacional_7 | baseline | propio (numpy) | 1.122 | 0.600 | 0.287 | -25.1 | 1.719 | 0.293 | 1.035 | 1.119 | -0.028 | 0.1 | 0 | ok |
| 23 | naive | baseline | propio (numpy) | 1.479 | 1.013 | 0.559 | -65.0 | 1.551 | 0.265 | 0.956 | 1.010 | -0.210 | 0.1 | 0 | ok |
|  | prophet | estadistico | prophet |  |  |  |  |  |  |  |  |  |  | 55 | omitido: 1188 series > limite 800 (modelo por serie, lento) |

## REAL · unidad kmeans

| # | Modelo | Familia | Librería | WAPE 7d | 7d zona | 7d total | Mejora % | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | xgboost_tweedie | ml_arboles | xgboost | 0.650 | 0.425 | 0.236 | 1.6 | 1.234 | 0.572 | 1.225 | 0.913 | -0.151 | 8.2 | 15 | ok |
| 2 | auto_arima | estadistico | statsforecast | 0.651 | 0.412 | 0.187 | 1.4 | 1.284 | 0.595 | 1.222 | 0.950 | -0.096 | 107.5 | 229 | ok |
| 3 | lightgbm_tweedie | ml_arboles | lightgbm | 0.653 | 0.416 | 0.211 | 1.3 | 1.254 | 0.582 | 1.217 | 0.928 | -0.111 | 9.2 | 11 | ok |
| 4 | auto_ets | estadistico | statsforecast | 0.653 | 0.414 | 0.186 | 1.3 | 1.287 | 0.597 | 1.220 | 0.952 | -0.092 | 13.1 | 229 | ok |
| 5 | media_dia_semana_8 | baseline | propio (numpy) | 0.661 | 0.413 | 0.182 | 0.0 | 1.298 | 0.602 | 1.256 | 0.960 | -0.076 | 0.0 | 0 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.667 | 0.409 | 0.196 | -1.0 | 1.294 | 0.600 | 1.222 | 0.957 | -0.055 | 10.9 | 308 | ok |
| 7 | mlp | deep_learning | scikit-learn | 0.673 | 0.422 | 0.200 | -1.8 | 1.303 | 0.604 | 1.221 | 0.964 | -0.049 | 23.0 | 196 | ok |
| 8 | ridge | ml_lineal | scikit-learn | 0.673 | 0.416 | 0.187 | -1.9 | 1.328 | 0.616 | 1.207 | 0.983 | -0.014 | 4.0 | 196 | ok |
| 9 | hist_gb_poisson | ml_arboles | scikit-learn | 0.677 | 0.426 | 0.189 | -2.4 | 1.324 | 0.614 | 1.231 | 0.980 | -0.017 | 12.5 | 196 | ok |
| 10 | croston_sba | intermitente | statsforecast | 0.683 | 0.427 | 0.200 | -3.4 | 1.312 | 0.608 | 1.224 | 0.971 | -0.070 | 16.1 | 229 | ok |
| 11 | prophet | estadistico | prophet | 0.688 | 0.433 | 0.189 | -4.2 | 1.303 | 0.604 | 1.233 | 0.965 | -0.058 | 103.0 | 55 | ok |
| 12 | croston | intermitente | statsforecast | 0.690 | 0.431 | 0.194 | -4.5 | 1.335 | 0.619 | 1.225 | 0.988 | -0.021 | 17.4 | 229 | ok |
| 13 | adida | intermitente | statsforecast | 0.691 | 0.437 | 0.195 | -4.6 | 1.308 | 0.606 | 1.233 | 0.968 | -0.072 | 16.7 | 229 | ok |
| 14 | poisson_glm | ml_lineal | scikit-learn | 0.708 | 0.432 | 0.210 | -7.1 | 1.327 | 0.615 | 1.217 | 0.982 | -0.028 | 13.1 | 196 | ok |
| 15 | media_movil_28 | baseline | propio (numpy) | 0.710 | 0.444 | 0.191 | -7.4 | 1.321 | 0.612 | 1.233 | 0.978 | -0.046 | 0.0 | 0 | ok |
| 16 | random_forest | ml_arboles | scikit-learn | 0.712 | 0.444 | 0.208 | -7.8 | 1.406 | 0.652 | 1.219 | 1.041 | 0.115 | 12.1 | 196 | ok |
| 17 | tsb | intermitente | statsforecast | 0.818 | 0.514 | 0.251 | -23.7 | 1.367 | 0.634 | 1.276 | 1.012 | -0.014 | 15.5 | 229 | ok |
| 18 | chronos_bolt | fundacional | chronos-forecasting | 0.823 | 0.782 | 0.769 | -24.5 | 0.986 | 0.457 | 1.314 | 0.730 | -0.769 | 3.5 | 2059 | ok |
| 19 | tft | deep_learning | neuralforecast | 0.872 | 0.829 | 0.824 | -31.9 | 0.966 | 0.448 | 1.333 | 0.715 | -0.824 | 97.7 | 2202 | ok |
| 20 | lstm | deep_learning | neuralforecast | 0.872 | 0.828 | 0.823 | -31.9 | 0.965 | 0.447 | 1.332 | 0.714 | -0.823 | 37.8 | 2202 | ok |
| 21 | nbeats | deep_learning | neuralforecast | 0.872 | 0.840 | 0.836 | -32.0 | 0.964 | 0.447 | 1.332 | 0.713 | -0.836 | 51.8 | 2202 | ok |
| 22 | nhits | deep_learning | neuralforecast | 0.875 | 0.851 | 0.848 | -32.4 | 0.964 | 0.447 | 1.335 | 0.714 | -0.848 | 60.7 | 2202 | ok |
| 23 | estacional_7 | baseline | propio (numpy) | 0.882 | 0.553 | 0.287 | -33.4 | 1.514 | 0.702 | 1.705 | 1.120 | -0.028 | 0.0 | 0 | ok |
| 24 | naive | baseline | propio (numpy) | 1.291 | 0.936 | 0.559 | -95.3 | 1.405 | 0.651 | 1.601 | 1.040 | -0.210 | 0.0 | 0 | ok |

## REAL · unidad dbscan

| # | Modelo | Familia | Librería | WAPE 7d | 7d zona | 7d total | Mejora % | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_ets | estadistico | statsforecast | 0.513 | 0.389 | 0.194 | 1.4 | 1.068 | 0.726 | 1.469 | 0.923 | -0.085 | 15.0 | 229 | ok |
| 2 | auto_arima | estadistico | statsforecast | 0.516 | 0.384 | 0.194 | 0.7 | 1.066 | 0.725 | 1.464 | 0.922 | -0.088 | 79.2 | 229 | ok |
| 3 | lightgbm_tweedie | ml_arboles | lightgbm | 0.517 | 0.391 | 0.210 | 0.6 | 1.017 | 0.691 | 1.444 | 0.879 | -0.087 | 8.5 | 11 | ok |
| 4 | media_dia_semana_8 ⭐ | baseline | propio (numpy) | 0.520 | 0.391 | 0.182 | 0.0 | 1.067 | 0.725 | 1.500 | 0.922 | -0.076 | 0.0 | 0 | ok |
| 5 | ridge | ml_lineal | scikit-learn | 0.524 | 0.389 | 0.188 | -0.7 | 1.087 | 0.739 | 1.443 | 0.940 | -0.018 | 2.5 | 196 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.524 | 0.393 | 0.204 | -0.8 | 1.056 | 0.718 | 1.452 | 0.913 | -0.043 | 13.4 | 308 | ok |
| 7 | hist_gb_poisson | ml_arboles | scikit-learn | 0.526 | 0.392 | 0.183 | -1.2 | 1.075 | 0.731 | 1.451 | 0.929 | 0.007 | 9.7 | 196 | ok |
| 8 | prophet | estadistico | prophet | 0.527 | 0.395 | 0.185 | -1.3 | 1.064 | 0.723 | 1.463 | 0.920 | -0.059 | 66.3 | 55 | ok |
| 9 | croston_sba | intermitente | statsforecast | 0.530 | 0.404 | 0.202 | -2.0 | 1.076 | 0.731 | 1.470 | 0.930 | -0.079 | 15.9 | 229 | ok |
| 10 | xgboost_tweedie | ml_arboles | xgboost | 0.533 | 0.416 | 0.247 | -2.4 | 1.010 | 0.686 | 1.465 | 0.873 | -0.146 | 7.0 | 15 | ok |
| 11 | mlp | deep_learning | scikit-learn | 0.535 | 0.396 | 0.201 | -2.9 | 1.099 | 0.747 | 1.432 | 0.950 | 0.028 | 14.5 | 196 | ok |
| 12 | croston | intermitente | statsforecast | 0.535 | 0.407 | 0.198 | -3.0 | 1.092 | 0.742 | 1.469 | 0.944 | -0.030 | 15.5 | 229 | ok |
| 13 | adida | intermitente | statsforecast | 0.537 | 0.407 | 0.203 | -3.2 | 1.073 | 0.730 | 1.473 | 0.928 | -0.062 | 22.4 | 229 | ok |
| 14 | random_forest | ml_arboles | scikit-learn | 0.551 | 0.407 | 0.208 | -5.9 | 1.134 | 0.771 | 1.448 | 0.980 | 0.092 | 10.1 | 196 | ok |
| 15 | media_movil_28 | baseline | propio (numpy) | 0.553 | 0.409 | 0.191 | -6.4 | 1.079 | 0.734 | 1.469 | 0.933 | -0.046 | 0.0 | 0 | ok |
| 16 | poisson_glm | ml_lineal | scikit-learn | 0.554 | 0.407 | 0.214 | -6.6 | 1.067 | 0.725 | 1.452 | 0.922 | -0.014 | 26.3 | 196 | ok |
| 17 | tsb | intermitente | statsforecast | 0.633 | 0.472 | 0.247 | -21.7 | 1.114 | 0.757 | 1.518 | 0.963 | -0.020 | 17.4 | 229 | ok |
| 18 | chronos_bolt | fundacional | chronos-forecasting | 0.635 | 0.603 | 0.585 | -22.2 | 0.860 | 0.584 | 1.558 | 0.743 | -0.585 | 3.7 | 2059 | ok |
| 19 | tft | deep_learning | neuralforecast | 0.649 | 0.608 | 0.586 | -24.8 | 0.855 | 0.581 | 1.562 | 0.739 | -0.586 | 75.2 | 2202 | ok |
| 20 | lstm | deep_learning | neuralforecast | 0.651 | 0.612 | 0.594 | -25.3 | 0.851 | 0.579 | 1.564 | 0.736 | -0.594 | 42.1 | 2202 | ok |
| 21 | nbeats | deep_learning | neuralforecast | 0.671 | 0.625 | 0.596 | -29.0 | 0.870 | 0.591 | 1.607 | 0.752 | -0.596 | 42.0 | 2202 | ok |
| 22 | nhits | deep_learning | neuralforecast | 0.674 | 0.604 | 0.563 | -29.6 | 0.867 | 0.589 | 1.590 | 0.749 | -0.561 | 44.3 | 2202 | ok |
| 23 | estacional_7 | baseline | propio (numpy) | 0.687 | 0.509 | 0.287 | -32.1 | 1.287 | 0.875 | 2.055 | 1.112 | -0.028 | 0.0 | 0 | ok |
| 24 | naive | baseline | propio (numpy) | 1.051 | 0.900 | 0.559 | -102.1 | 1.195 | 0.812 | 1.962 | 1.033 | -0.210 | 0.0 | 0 | ok |

## REAL · unidad zona

| # | Modelo | Familia | Librería | WAPE 7d | 7d zona | 7d total | Mejora % | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | auto_ets | estadistico | statsforecast | 0.451 | 0.451 | 0.189 | 0.8 | 1.013 | 0.978 | 1.818 | 0.920 | -0.086 | 12.5 | 229 | ok |
| 2 | auto_arima | estadistico | statsforecast | 0.452 | 0.452 | 0.189 | 0.8 | 1.013 | 0.977 | 1.815 | 0.919 | -0.095 | 62.1 | 229 | ok |
| 3 | ridge | ml_lineal | scikit-learn | 0.455 | 0.455 | 0.188 | 0.1 | 1.023 | 0.987 | 1.784 | 0.928 | -0.021 | 1.3 | 196 | ok |
| 4 | lightgbm_tweedie | ml_arboles | lightgbm | 0.455 | 0.455 | 0.207 | 0.0 | 0.980 | 0.945 | 1.780 | 0.889 | -0.079 | 2.1 | 11 | ok |
| 5 | media_dia_semana_8 | baseline | propio (numpy) | 0.455 | 0.455 | 0.182 | 0.0 | 1.026 | 0.989 | 1.872 | 0.931 | -0.076 | 0.0 | 0 | ok |
| 6 | catboost_tweedie | ml_arboles | catboost | 0.455 | 0.455 | 0.192 | -0.0 | 1.005 | 0.969 | 1.788 | 0.912 | -0.033 | 4.0 | 308 | ok |
| 7 | xgboost_tweedie | ml_arboles | xgboost | 0.462 | 0.462 | 0.224 | -1.5 | 0.975 | 0.940 | 1.795 | 0.885 | -0.092 | 2.0 | 15 | ok |
| 8 | mlp | deep_learning | scikit-learn | 0.463 | 0.463 | 0.184 | -1.6 | 1.007 | 0.971 | 1.767 | 0.913 | -0.032 | 7.6 | 196 | ok |
| 9 | hist_gb_poisson | ml_arboles | scikit-learn | 0.467 | 0.467 | 0.181 | -2.5 | 1.020 | 0.984 | 1.781 | 0.926 | -0.012 | 1.9 | 196 | ok |
| 10 | prophet | estadistico | prophet | 0.468 | 0.468 | 0.189 | -2.9 | 1.013 | 0.977 | 1.815 | 0.920 | -0.062 | 32.4 | 55 | ok |
| 11 | poisson_glm | ml_lineal | scikit-learn | 0.477 | 0.477 | 0.219 | -4.8 | 1.015 | 0.979 | 1.786 | 0.921 | -0.017 | 12.5 | 196 | ok |
| 12 | random_forest | ml_arboles | scikit-learn | 0.480 | 0.480 | 0.191 | -5.5 | 1.056 | 1.018 | 1.785 | 0.958 | 0.047 | 3.5 | 196 | ok |
| 13 | croston_sba | intermitente | statsforecast | 0.483 | 0.483 | 0.202 | -6.0 | 1.023 | 0.986 | 1.836 | 0.928 | -0.087 | 16.8 | 229 | ok |
| 14 | croston | intermitente | statsforecast | 0.483 | 0.483 | 0.197 | -6.1 | 1.036 | 0.999 | 1.834 | 0.940 | -0.039 | 46.3 | 229 | ok |
| 15 | adida | intermitente | statsforecast | 0.486 | 0.486 | 0.197 | -6.7 | 1.031 | 0.994 | 1.840 | 0.935 | -0.052 | 29.1 | 229 | ok |
| 16 | media_movil_28 | baseline | propio (numpy) | 0.487 | 0.487 | 0.191 | -7.0 | 1.031 | 0.995 | 1.825 | 0.936 | -0.046 | 0.0 | 0 | ok |
| 17 | tsb | intermitente | statsforecast | 0.569 | 0.569 | 0.251 | -24.9 | 1.066 | 1.028 | 1.893 | 0.967 | -0.014 | 17.5 | 229 | ok |
| 18 | chronos_bolt | fundacional | chronos-forecasting | 0.589 | 0.589 | 0.534 | -29.4 | 0.855 | 0.825 | 1.915 | 0.776 | -0.534 | 3.7 | 2059 | ok |
| 19 | estacional_7 | baseline | propio (numpy) | 0.600 | 0.600 | 0.287 | -31.7 | 1.242 | 1.198 | 2.532 | 1.128 | -0.028 | 0.0 | 0 | ok |
| 20 | nhits | deep_learning | neuralforecast | 0.604 | 0.604 | 0.506 | -32.7 | 0.884 | 0.852 | 1.966 | 0.802 | -0.492 | 29.3 | 2202 | ok |
| 21 | nbeats | deep_learning | neuralforecast | 0.609 | 0.609 | 0.460 | -33.8 | 0.912 | 0.880 | 2.023 | 0.828 | -0.460 | 24.5 | 2202 | ok |
| 22 | tft | deep_learning | neuralforecast | 0.619 | 0.619 | 0.543 | -35.9 | 0.861 | 0.831 | 1.938 | 0.782 | -0.541 | 51.6 | 2202 | ok |
| 23 | lstm | deep_learning | neuralforecast | 0.622 | 0.622 | 0.549 | -36.6 | 0.859 | 0.829 | 1.941 | 0.780 | -0.547 | 16.5 | 2202 | ok |
| 24 | naive | baseline | propio (numpy) | 1.016 | 1.016 | 0.559 | -123.2 | 1.180 | 1.138 | 2.427 | 1.071 | -0.210 | 0.0 | 0 | ok |

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
