"""Registro de modelos de pronostico de demanda. Todos tienen la misma firma:

    fn(entreno, fechas, info, ctx) -> DataFrame[unique_id, ds, yhat]

entreno: panel (unique_id, ds, y) hasta el dia anterior al corte; fechas: los HORIZONTE dias a pronosticar;
info: atributos de cada serie (producto_sk, unidad_id, categoria); ctx: {'centros', 'semilla', 'pasos_dl', ...}.

Un modelo cuya libreria no esta instalada se reporta como "omitido": asi el benchmark corre igual con la imagen
completa (requirements-benchmark.txt) que con la de produccion (solo el ganador), y la poda no rompe nada.
"""
import importlib.util
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import features as F


@dataclass
class Modelo:
    nombre: str
    familia: str
    libreria: str
    modulos: tuple                       # modulos de Python que necesita (para saber si esta disponible)
    distribuciones: tuple                # paquetes pip (para medir el peso de las dependencias)
    fn: object
    descripcion: str = ""
    max_series: int = 0                  # 0 = sin limite; si hay mas series se omite (modelos lentos por serie)
    extra: dict = field(default_factory=dict)

    def disponible(self):
        return all(importlib.util.find_spec(m) is not None for m in self.modulos)


def _salida(ids, fechas, valores):
    """Matriz (series x h) -> formato largo, sin negativos."""
    valores = np.clip(np.nan_to_num(np.asarray(valores, float), nan=0.0), 0, None)
    return pd.DataFrame({"unique_id": np.repeat(ids, len(fechas)), "ds": np.tile(np.asarray(fechas), len(ids)),
                         "yhat": valores.reshape(-1)})


def _matriz(entreno):
    m = entreno.pivot(index="unique_id", columns="ds", values="y").sort_index()
    return m.index.to_numpy(), m.columns, m.to_numpy(float)


# ---------------------------------------------------------------------------------------------------- baselines
def naive(entreno, fechas, info, ctx):
    ids, _d, y = _matriz(entreno)
    return _salida(ids, fechas, np.repeat(y[:, -1:], len(fechas), axis=1))


def estacional_7(entreno, fechas, info, ctx):
    ids, dias, y = _matriz(entreno)
    pos = {d: i for i, d in enumerate(dias)}
    cols = [pos.get(pd.Timestamp(f) - pd.Timedelta(days=7 * (1 + (pd.Timestamp(f) - dias[-1]).days // 8)), -1)
            for f in fechas]
    return _salida(ids, fechas, y[:, cols])


def media_movil_28(entreno, fechas, info, ctx):
    ids, _d, y = _matriz(entreno)
    return _salida(ids, fechas, np.repeat(y[:, -28:].mean(axis=1, keepdims=True), len(fechas), axis=1))


def media_dia_semana_8(entreno, fechas, info, ctx):
    """Media del mismo dia de la semana en las ultimas 8 semanas."""
    ids, dias, y = _matriz(entreno)
    dows = np.array([d.dayofweek for d in dias])
    ultimo = len(dias) - 56
    out = []
    for f in fechas:
        m = (dows == pd.Timestamp(f).dayofweek) & (np.arange(len(dias)) >= ultimo)
        out.append(y[:, m].mean(axis=1) if m.any() else y[:, -7:].mean(axis=1))
    return _salida(ids, fechas, np.column_stack(out))


# ---------------------------------------------------------------------------------------------------- statsforecast
def _statsforecast(modelo_sf):
    def fn(entreno, fechas, info, ctx):
        from statsforecast import StatsForecast
        sf = StatsForecast(models=[modelo_sf()], freq="D", n_jobs=ctx.get("n_jobs", -1))
        pred = sf.forecast(df=entreno[["unique_id", "ds", "y"]], h=len(fechas))
        pred = pred.reset_index() if "unique_id" not in pred.columns else pred
        col = [c for c in pred.columns if c not in ("unique_id", "ds")][0]
        return pred.rename(columns={col: "yhat"})[["unique_id", "ds", "yhat"]].assign(
            yhat=lambda d: d["yhat"].clip(lower=0).fillna(0))
    return fn


def _sf(nombre, **kw):
    def crear():
        import statsforecast.models as m
        return getattr(m, nombre)(**kw)
    return crear


# ---------------------------------------------------------------------------------------------------- prophet
def prophet(entreno, fechas, info, ctx):
    import logging
    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
    from prophet import Prophet
    filas = []
    futuro = pd.DataFrame({"ds": pd.to_datetime(fechas)})
    for uid, s in entreno.groupby("unique_id", sort=True):
        if s["y"].sum() == 0:
            filas.append(np.zeros(len(fechas)))
            continue
        m = Prophet(weekly_seasonality=True, yearly_seasonality=False, daily_seasonality=False,
                    uncertainty_samples=0)
        m.add_country_holidays(country_name="EC")
        m.fit(s[["ds", "y"]])
        filas.append(m.predict(futuro)["yhat"].to_numpy())
    ids = np.sort(entreno["unique_id"].unique())
    return _salida(ids, fechas, np.vstack(filas))


# ---------------------------------------------------------------------------------------------------- tabulares
def _tabular(crear, escalar=False):
    """Modelo global (una sola regresion para todas las series) con las variables de features.tabla."""
    def fn(entreno, fechas, info, ctx):
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        filas = F.filas_entrenamiento(entreno)
        X = F.tabla(entreno, filas, info, ctx.get("centros"))
        y = filas["y"].to_numpy()
        pasos = [SimpleImputer(strategy="constant", fill_value=-1)]
        if escalar:
            pasos.append(StandardScaler())
        modelo = make_pipeline(*pasos, crear(ctx))
        modelo.fit(X, y)
        ids = np.sort(entreno["unique_id"].unique())
        objetivo = pd.DataFrame({"unique_id": np.repeat(ids, len(fechas)),
                                 "ds": np.tile(pd.to_datetime(fechas), len(ids))})
        pred = modelo.predict(F.tabla(entreno, objetivo, info, ctx.get("centros")))
        ctx.setdefault("_modelos_ajustados", {})[ctx.get("_nombre")] = (modelo, list(X.columns))
        return objetivo.assign(yhat=np.clip(pred, 0, None))
    return fn


def _ridge(ctx):
    from sklearn.linear_model import Ridge
    return Ridge(alpha=1.0)


def _poisson(ctx):
    from sklearn.linear_model import PoissonRegressor
    return PoissonRegressor(alpha=1e-3, max_iter=500)


def _rf(ctx):
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(n_estimators=150, min_samples_leaf=5, max_samples=0.5, n_jobs=-1,
                                 random_state=ctx.get("semilla", 42))


def _hgb(ctx):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05,
                                         random_state=ctx.get("semilla", 42))


def _xgb(ctx):
    from xgboost import XGBRegressor
    return XGBRegressor(objective="reg:tweedie", tweedie_variance_power=1.3, n_estimators=400, learning_rate=0.05,
                        max_depth=6, subsample=0.8, colsample_bytree=0.8, n_jobs=ctx.get("n_jobs", -1),
                        random_state=ctx.get("semilla", 42), verbosity=0)


def _lgbm(ctx):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, n_estimators=400, learning_rate=0.05,
                         num_leaves=31, min_child_samples=20, subsample=0.8, subsample_freq=1,
                         colsample_bytree=0.8, random_state=ctx.get("semilla", 42), verbose=-1)


def _catboost(ctx):
    from catboost import CatBoostRegressor
    return CatBoostRegressor(loss_function="Tweedie:variance_power=1.3", iterations=400, learning_rate=0.08,
                             depth=6, random_seed=ctx.get("semilla", 42), verbose=0, allow_writing_files=False,
                             thread_count=ctx.get("n_jobs", -1))


def _mlp(ctx):
    from sklearn.neural_network import MLPRegressor
    return MLPRegressor(hidden_layer_sizes=(64, 32), early_stopping=True, max_iter=300, learning_rate_init=1e-3,
                        random_state=ctx.get("semilla", 42))


# ---------------------------------------------------------------------------------------------------- neuralforecast
def _neural(nombre_clase, **kw):
    def fn(entreno, fechas, info, ctx):
        import logging
        logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
        logging.getLogger("lightning").setLevel(logging.ERROR)
        import neuralforecast.models as nm
        from neuralforecast import NeuralForecast
        h = len(fechas)
        clase = getattr(nm, nombre_clase)
        modelo = clase(h=h, input_size=28, max_steps=ctx.get("pasos_dl", 300), random_seed=ctx.get("semilla", 42),
                       scaler_type="robust", accelerator="cpu", enable_progress_bar=False, logger=False,
                       enable_model_summary=False, **kw)
        nf = NeuralForecast(models=[modelo], freq="D")
        nf.fit(df=entreno[["unique_id", "ds", "y"]])
        pred = nf.predict()
        pred = pred.reset_index() if "unique_id" not in pred.columns else pred
        col = [c for c in pred.columns if c not in ("unique_id", "ds")][0]
        return pred.rename(columns={col: "yhat"})[["unique_id", "ds", "yhat"]].assign(
            yhat=lambda d: d["yhat"].clip(lower=0).fillna(0))
    return fn


# ---------------------------------------------------------------------------------------------------- fundacional
def chronos_bolt(entreno, fechas, info, ctx):
    """Chronos-Bolt (Amazon), modelo fundacional preentrenado, sin entrenar con nuestros datos (zero-shot).
    Descarga el modelo de Hugging Face la primera vez (CHRONOS_MODEL, por defecto amazon/chronos-bolt-small)."""
    import torch
    from chronos import BaseChronosPipeline
    nombre = os.environ.get("CHRONOS_MODEL", "amazon/chronos-bolt-small")
    pipe = BaseChronosPipeline.from_pretrained(nombre, device_map="cpu", torch_dtype=torch.float32)
    ids, _d, y = _matriz(entreno)
    contexto = y[:, -int(ctx.get("contexto_chronos", 112)):]
    out = []
    for i in range(0, len(contexto), 256):
        lote = torch.tensor(contexto[i:i + 256], dtype=torch.float32)
        _q, media = pipe.predict_quantiles(context=lote, prediction_length=len(fechas), quantile_levels=[0.5])
        out.append(media.numpy())
    return _salida(ids, fechas, np.vstack(out))


# ---------------------------------------------------------------------------------------------------- registro
SKL = ("sklearn",)
PIP_SKL = ("scikit-learn", "scipy", "joblib", "threadpoolctl")
PIP_SF = ("statsforecast", "numba", "llvmlite", "coreforecast", "utilsforecast", "statsmodels")
PIP_NF = ("neuralforecast", "torch", "pytorch-lightning", "lightning-utilities", "torchmetrics", "ray", "optuna",
          "coreforecast", "utilsforecast")

MODELOS = [
    Modelo("naive", "baseline", "propio (numpy)", (), (), naive, "Repite el ultimo dia observado."),
    Modelo("estacional_7", "baseline", "propio (numpy)", (), (), estacional_7,
           "Mismo dia de la semana anterior (referencia para comparar: MASE y la regla de eleccion)."),
    Modelo("media_movil_28", "baseline", "propio (numpy)", (), (), media_movil_28, "Media de los ultimos 28 dias."),
    Modelo("media_dia_semana_8", "baseline", "propio (numpy)", (), (), media_dia_semana_8,
           "Media del mismo dia de la semana en las ultimas 8 semanas."),
    Modelo("croston", "intermitente", "statsforecast", ("statsforecast",), PIP_SF,
           _statsforecast(_sf("CrostonClassic")), "Croston clasico para demanda intermitente."),
    Modelo("croston_sba", "intermitente", "statsforecast", ("statsforecast",), PIP_SF,
           _statsforecast(_sf("CrostonSBA")), "Croston con correccion de sesgo de Syntetos-Boylan."),
    Modelo("tsb", "intermitente", "statsforecast", ("statsforecast",), PIP_SF,
           _statsforecast(_sf("TSB", alpha_d=0.2, alpha_p=0.2)), "Teunter-Syntetos-Babai (probabilidad de venta)."),
    Modelo("adida", "intermitente", "statsforecast", ("statsforecast",), PIP_SF, _statsforecast(_sf("ADIDA")),
           "Agregacion temporal para demanda intermitente."),
    Modelo("auto_ets", "estadistico", "statsforecast", ("statsforecast",), PIP_SF,
           _statsforecast(_sf("AutoETS", season_length=7)), "Suavizado exponencial con estacionalidad semanal."),
    Modelo("auto_arima", "estadistico", "statsforecast", ("statsforecast",), PIP_SF,
           _statsforecast(_sf("AutoARIMA", season_length=7)), "ARIMA estacional elegido automaticamente."),
    Modelo("prophet", "estadistico", "prophet", ("prophet",), ("prophet", "cmdstanpy", "holidays", "stanio"),
           prophet, "Tendencia + estacionalidad semanal + feriados de Ecuador (una regresion por serie).",
           max_series=int(os.environ.get("PROPHET_MAX_SERIES", "800"))),
    Modelo("ridge", "ml_lineal", "scikit-learn", SKL, PIP_SKL, _tabular(_ridge, escalar=True),
           "Regresion lineal regularizada (global)."),
    Modelo("poisson_glm", "ml_lineal", "scikit-learn", SKL, PIP_SKL, _tabular(_poisson, escalar=True),
           "Regresion de Poisson (conteos)."),
    Modelo("random_forest", "ml_arboles", "scikit-learn", SKL, PIP_SKL, _tabular(_rf), "Bosque aleatorio (global)."),
    Modelo("hist_gb_poisson", "ml_arboles", "scikit-learn", SKL, PIP_SKL, _tabular(_hgb),
           "Gradient boosting por histogramas con perdida de Poisson."),
    Modelo("xgboost_tweedie", "ml_arboles", "xgboost", ("xgboost",), ("xgboost-cpu", "xgboost"), _tabular(_xgb),
           "XGBoost con perdida Tweedie (conteos con muchos ceros)."),
    Modelo("lightgbm_tweedie", "ml_arboles", "lightgbm", ("lightgbm",), ("lightgbm",), _tabular(_lgbm),
           "LightGBM con perdida Tweedie (el enfoque ganador del M5)."),
    Modelo("catboost_tweedie", "ml_arboles", "catboost", ("catboost",), ("catboost",), _tabular(_catboost),
           "CatBoost con perdida Tweedie."),
    Modelo("mlp", "deep_learning", "scikit-learn", SKL, PIP_SKL, _tabular(_mlp, escalar=True),
           "Red neuronal densa (perceptron multicapa) sobre las mismas variables."),
    Modelo("lstm", "deep_learning", "neuralforecast", ("neuralforecast",), PIP_NF,
           _neural("LSTM", encoder_hidden_size=32, decoder_hidden_size=32), "Red recurrente LSTM (PyTorch)."),
    Modelo("nbeats", "deep_learning", "neuralforecast", ("neuralforecast",), PIP_NF, _neural("NBEATS"),
           "N-BEATS: bloques densos con descomposicion en tendencia y estacionalidad."),
    Modelo("nhits", "deep_learning", "neuralforecast", ("neuralforecast",), PIP_NF, _neural("NHITS"),
           "N-HiTS: N-BEATS jerarquico por frecuencias."),
    Modelo("tft", "deep_learning", "neuralforecast", ("neuralforecast",), PIP_NF, _neural("TFT", hidden_size=32),
           "Temporal Fusion Transformer (atencion)."),
    Modelo("chronos_bolt", "fundacional", "chronos-forecasting", ("chronos", "torch"),
           ("chronos-forecasting", "torch", "transformers", "accelerate"), chronos_bolt,
           "Modelo fundacional preentrenado (zero-shot, sin entrenar con estos datos)."),
]
POR_NOMBRE = {m.nombre: m for m in MODELOS}
REFERENCIA = "estacional_7"


def peso_mb(distribuciones):
    """Megabytes instalados de los paquetes (suma de sus archivos). None si ninguno esta instalado."""
    from importlib import metadata
    total, alguno = 0, False
    for nombre in distribuciones:
        try:
            dist = metadata.distribution(nombre)
        except metadata.PackageNotFoundError:
            continue
        alguno = True
        for f in dist.files or []:
            try:
                total += f.locate().stat().st_size
            except OSError:
                pass
    return round(total / 1e6, 1) if alguno else 0.0
