"""Metricas de pronostico sobre todos los pares (serie, dia) de los cortes de prueba.

- MAE, RMSE: en unidades.
- WAPE = sum|error| / sum(real): error relativo ponderado por volumen (no se indefine con ceros, a diferencia del
  MAPE). Es la metrica principal de la tabla.
- MASE = MAE / MAE dentro de la muestra del estacional ingenuo (y_t - y_{t-7}), agrupado: < 1 significa que el
  modelo comete menos error que repetir la semana anterior en el entrenamiento.
- WAPE 7d = el mismo error pero sobre el TOTAL de los 7 dias de cada serie (lo que importa para planificar compras o
  rutas de la semana): los errores de un dia se compensan con los del dia siguiente.
- sesgo = sum(pronostico - real) / sum(real): > 0 sobreestima, < 0 subestima.
"""
import numpy as np


def escala_mase(entreno, estacion=7):
    s = entreno.sort_values(["unique_id", "ds"])
    dif = s.groupby("unique_id")["y"].diff(estacion).abs()
    v = float(dif.mean()) if dif.notna().any() else 0.0
    return v if v > 0 else 1.0


def calcular(real, pred, escala=1.0):
    real, pred = np.asarray(real, float), np.asarray(pred, float)
    err = pred - real
    total = real.sum()
    mae = float(np.abs(err).mean()) if len(err) else float("nan")
    return {
        "mae": mae,
        "rmse": float(np.sqrt((err ** 2).mean())) if len(err) else float("nan"),
        "wape": float(np.abs(err).sum() / total) if total > 0 else float("nan"),
        "mase": float(mae / escala) if escala else float("nan"),
        "sesgo": float(err.sum() / total) if total > 0 else float("nan"),
    }


def wape_semanal(real_semana, pred_semana):
    real, pred = np.asarray(real_semana, float), np.asarray(pred_semana, float)
    total = real.sum()
    return float(np.abs(pred - real).sum() / total) if total > 0 else float("nan")
