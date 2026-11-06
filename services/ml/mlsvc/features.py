"""Ingenieria de caracteristicas: vehiculo y zona origen one-hot; dia/hora ciclicos."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder

TZ_OFFSET_H = -5  # Ecuador (America/Guayaquil), sin horario de verano
CAT = ["vehiculo_codigo", "zona_origen"]
NUM = ["hora_sin", "hora_cos", "dow_sin", "dow_cos", "hora"]
FEATURES = CAT + NUM


def build_features(vehiculo, fecha_hora, zona_origen) -> pd.DataFrame:
    """Listas/series paralelas -> DataFrame de caracteristicas (hora local)."""
    ts = pd.to_datetime(pd.Series(list(fecha_hora)), utc=True) + pd.Timedelta(hours=TZ_OFFSET_H)
    hora = (ts.dt.hour + ts.dt.minute / 60).to_numpy()
    dow = ts.dt.dayofweek.to_numpy()
    return pd.DataFrame({
        "vehiculo_codigo": list(vehiculo),
        "zona_origen": list(zona_origen),
        "hora_sin": np.sin(2 * np.pi * hora / 24),
        "hora_cos": np.cos(2 * np.pi * hora / 24),
        "dow_sin": np.sin(2 * np.pi * dow / 7),
        "dow_cos": np.cos(2 * np.pi * dow / 7),
        "hora": hora,
    })[FEATURES]


def make_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), CAT)], remainder="passthrough"
    )
