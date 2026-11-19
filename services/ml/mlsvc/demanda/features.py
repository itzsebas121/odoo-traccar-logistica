"""Variables de los modelos tabulares (ML y MLP), sin fuga del futuro.

Estrategia directa: todos los rezagos son >= HORIZONTE (7). Para cualquier dia del horizonte (corte + 0..6) los
valores de 7 o mas dias atras ya se conocen en el corte, asi que los 7 dias se pronostican de una vez y sin
recursion. Las medias de cada serie, producto y unidad son acumuladas y desplazadas el mismo horizonte: usan solo
lo que se sabia h dias antes de la fecha objetivo (en entrenamiento y en prediccion se calculan igual).

Calendario de Ecuador: dia de la semana (seno/coseno), dia del mes, dias de pago (quincena y fin de mes), feriado
nacional y vispera (libreria holidays, si esta instalada)."""
import numpy as np
import pandas as pd

from . import HORIZONTE

REZAGOS = (7, 14, 21, 28)
DIAS_PAGO = (1, 15, 16)
COLS_CATEGORICAS = ["cod_producto", "cod_unidad", "cod_categoria"]


def feriados_ec(anios):
    try:
        import holidays
    except ImportError:
        return set()
    return {pd.Timestamp(d) for d in holidays.country_holidays("EC", years=sorted(set(anios)))}


def calendario(ds):
    ds = pd.to_datetime(pd.Series(ds)).reset_index(drop=True)
    fer = feriados_ec(ds.dt.year.unique().tolist() + [int(ds.dt.year.max()) + 1])
    dow = ds.dt.dayofweek.to_numpy()
    fin_mes = (ds + pd.Timedelta(days=1)).dt.day.to_numpy() == 1
    return pd.DataFrame({
        "dow": dow,
        "dow_sin": np.sin(2 * np.pi * dow / 7),
        "dow_cos": np.cos(2 * np.pi * dow / 7),
        "dia_mes": ds.dt.day.to_numpy(),
        "mes": ds.dt.month.to_numpy(),
        "fin_de_semana": (dow >= 5).astype(int),
        "dia_pago": (np.isin(ds.dt.day.to_numpy(), DIAS_PAGO) | fin_mes).astype(int),
        "feriado": ds.isin(fer).astype(int).to_numpy(),
        "vispera": (ds + pd.Timedelta(days=1)).isin(fer).astype(int).to_numpy(),
    })


def _codigos(info):
    return {
        "cod_producto": {v: i for i, v in enumerate(sorted(info["producto_sk"].unique()))},
        "cod_unidad": {v: i for i, v in enumerate(sorted(info["unidad_id"].unique()))},
        "cod_categoria": {v: i for i, v in enumerate(sorted(info["categoria"].unique()))},
    }


def tabla(historia, objetivo, info, centros=None, h=HORIZONTE):
    """historia: panel (unique_id, ds, y) conocido; objetivo: (unique_id, ds) a describir (puede solaparse con la
    historia, en entrenamiento). Devuelve X alineado con `objetivo` (mismo orden)."""
    obj = objetivo[["unique_id", "ds"]].reset_index(drop=True).copy()
    obj["_orden"] = np.arange(len(obj))
    hist = historia[["unique_id", "ds", "y"]]
    todo = (pd.concat([hist, obj[["unique_id", "ds"]].assign(y=np.nan)], ignore_index=True)
              .drop_duplicates(["unique_id", "ds"], keep="first")
              .sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True))
    g = todo.groupby("unique_id", sort=False)["y"]
    for k in REZAGOS:
        todo["lag%d" % k] = g.shift(k)
    base = g.shift(h)
    todo["_base"] = base
    gb = todo.groupby("unique_id", sort=False)["_base"]
    todo["media7"] = gb.transform(lambda s: s.rolling(7, min_periods=1).mean())
    todo["media28"] = gb.transform(lambda s: s.rolling(28, min_periods=1).mean())
    todo["max28"] = gb.transform(lambda s: s.rolling(28, min_periods=1).max())
    todo["dias_venta28"] = gb.transform(lambda s: (s > 0).rolling(28, min_periods=1).sum())
    todo["media_serie"] = gb.transform(lambda s: s.expanding().mean())
    todo["mismo_dow4"] = todo[["lag7", "lag14", "lag21", "lag28"]].mean(axis=1)

    m = obj.merge(todo, on=["unique_id", "ds"], how="left").merge(info, on="unique_id", how="left")
    # Medias por producto y por unidad del dia (todas sus series), desplazadas h dias.
    for col, nombre in (("producto_sk", "media_producto"), ("unidad_id", "media_unidad")):
        t = todo.merge(info[["unique_id", col]], on="unique_id")
        dia = t.groupby([col, "ds"], as_index=False)["_base"].mean()
        dia[nombre] = dia.groupby(col)["_base"].transform(lambda s: s.rolling(28, min_periods=1).mean())
        m = m.merge(dia[[col, "ds", nombre]], on=[col, "ds"], how="left")
    cods = _codigos(info)
    for col, src in (("cod_producto", "producto_sk"), ("cod_unidad", "unidad_id"), ("cod_categoria", "categoria")):
        m[col] = m[src].map(cods[col]).fillna(-1).astype(int)
    if centros:
        m["lat_unidad"] = m["unidad_id"].map(lambda u: (centros.get(u) or (np.nan, np.nan))[0])
        m["lon_unidad"] = m["unidad_id"].map(lambda u: (centros.get(u) or (np.nan, np.nan))[1])
    else:
        m["lat_unidad"], m["lon_unidad"] = np.nan, np.nan
    m = m.sort_values("_orden").reset_index(drop=True)
    cal = calendario(m["ds"])
    X = pd.concat([m[["lag%d" % k for k in REZAGOS] + ["media7", "media28", "max28", "dias_venta28",
                                                       "media_serie", "mismo_dow4", "media_producto",
                                                       "media_unidad", "lat_unidad", "lon_unidad"]
                     + COLS_CATEGORICAS], cal], axis=1)
    return X


def filas_entrenamiento(entreno, minimo_historia=28):
    """Filas del panel de entrenamiento con historia suficiente para los rezagos."""
    inicio = entreno["ds"].min() + pd.Timedelta(days=minimo_historia)
    return entreno[entreno["ds"] >= inicio]
