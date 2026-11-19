"""Series diarias de demanda (producto x unidad espacial) y cortes temporales del backtest.

Panel en formato largo (el de Nixtla): unique_id = "<producto_sk>|<unidad_id>", ds (dia local), y (unidades).
Los dias sin venta valen 0 entre el primer y el ultimo dia con datos del conjunto (no de cada serie)."""
import numpy as np
import pandas as pd

from . import HORIZONTE


def construir(ventas, unidad):
    """ventas normalizadas + array de unidad por fila -> (panel, info_series).
    info_series: unique_id, producto_sk, unidad_id, categoria, producto."""
    v = ventas.assign(unidad_id=np.asarray(unidad, dtype=object).astype(str))
    v["unique_id"] = v["producto_sk"].astype(str) + "|" + v["unidad_id"]
    diario = v.groupby(["unique_id", "fecha_local"], as_index=False)["cantidad"].sum()
    dias = pd.date_range(v["fecha_local"].min(), v["fecha_local"].max(), freq="D")
    ids = np.sort(diario["unique_id"].unique())
    completo = pd.MultiIndex.from_product([ids, dias], names=["unique_id", "ds"]).to_frame(index=False)
    panel = completo.merge(diario.rename(columns={"fecha_local": "ds", "cantidad": "y"}), how="left",
                           on=["unique_id", "ds"])
    panel["y"] = panel["y"].fillna(0.0).astype(float)
    info = (v.groupby("unique_id", as_index=False)
             .agg(producto_sk=("producto_sk", "first"), unidad_id=("unidad_id", "first"),
                  categoria=("categoria", "first"), producto=("producto", "first")))
    return panel.sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True), info


def cortes(panel, n=3, h=HORIZONTE):
    """Inicios de los n cortes de prueba consecutivos al final del panel (origen movil, sin solaparse):
    el corte i entrena con ds < inicio_i y prueba [inicio_i, inicio_i + h)."""
    fin = panel["ds"].max()
    return [fin - pd.Timedelta(days=h * (n - i) - 1) for i in range(n)]


def partir(panel, inicio, h=HORIZONTE):
    entreno = panel[panel["ds"] < inicio]
    prueba = panel[(panel["ds"] >= inicio) & (panel["ds"] < inicio + pd.Timedelta(days=h))]
    return entreno, prueba


def futuro(panel, h=HORIZONTE):
    """Fechas a pronosticar despues del ultimo dia del panel."""
    fin = panel["ds"].max()
    return pd.date_range(fin + pd.Timedelta(days=1), periods=h, freq="D")
