"""Pronostico de demanda en el SERVIDOR con el modelo entrenado en local: no entrena nada.

    python -m mlsvc.demanda.predecir [--source dwh] [--model-dir models] [--analisis-dir analisis] [--sin-dwh]

1. Carga models/demanda.joblib (lo genera `mlsvc.demanda.train` en local y se sube con el repo). Si las versiones
   de las librerias no coinciden con las del entrenamiento, se detiene: un estimador guardado con otra version de
   scikit-learn o lightgbm no carga bien.
2. Lee las ventas del DWH de este servidor (rol dwh_ro) y traduce cada producto al del modelo por su id de Odoo
   (el producto_sk del DWH local y el del servidor no tienen por que coincidir). Asigna cada venta a una unidad
   espacial con el asignador guardado y arma las series conocidas por el modelo.
3. Pronostica los 7 dias siguientes al ultimo dia con ventas: estimador.predict sobre las variables (rezagos,
   calendario, ubicacion) o, si el elegido es un baseline, su regla. Las bandas p10/p90 son las del entrenamiento.
   Ademas, un backtest de los ultimos 7 dias con el mismo estimador (sin reentrenar) para el grafico real vs
   pronostico.
4. Escribe models/demanda_prediccion.joblib (lo sirve /demanda/predict) y, si DWH_ML_PASSWORD esta definida,
   ml_pronostico_demanda, ml_unidad_espacial y la comparativa (analisis/comparativa_modelos.json) en
   ml_evaluacion_modelos si esa corrida no esta: asi el BI del servidor la ve sin correr el benchmark.
"""
import argparse
import json
import os
import pathlib
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from . import HORIZONTE, datos, panel
from . import features as F
from .modelos import POR_NOMBRE
from .train import _atomico, guardar_dwh, versiones


class VersionIncompatible(RuntimeError):
    """El modelo se guardo con otras versiones de las librerias."""


def comprobar_versiones(paquete, actuales=None):
    """Lista de diferencias 'lib: entrenado X, instalado Y' (vacia si todo coincide)."""
    actuales = actuales or versiones()
    guardadas = paquete.get("versiones") or {}
    return ["%s: entrenado %s, instalado %s" % (lib, v, actuales.get(lib))
            for lib, v in guardadas.items() if lib != "python" and v is not None and actuales.get(lib) != v]


def _traducir(ventas, paquete):
    """Ventas del servidor con producto_sk del modelo (por producto_id_odoo). Devuelve (ventas, {sk_modelo: sk_srv},
    productos del servidor sin historial en el modelo)."""
    prods = paquete["productos"][["producto_sk", "producto_id_odoo"]].rename(columns={"producto_sk": "sk_modelo"})
    v = ventas.merge(prods, on="producto_id_odoo", how="left")
    desconocidos = sorted(v.loc[v["sk_modelo"].isna(), "producto_id_odoo"].unique().tolist())
    v = v[v["sk_modelo"].notna()].copy()
    a_servidor = (v.groupby("sk_modelo")["producto_sk"].first().astype(int).to_dict())
    v["producto_sk"] = v["sk_modelo"].astype(int)
    return v.drop(columns="sk_modelo"), {int(k): int(x) for k, x in a_servidor.items()}, desconocidos


def _panel(v, unidad, info, fin=None):
    """Panel diario (unique_id, ds, y) de las series que conoce el modelo, relleno con ceros hasta `fin`."""
    v = v.assign(unidad_id=np.asarray(unidad, dtype=object).astype(str))
    v["unique_id"] = v["producto_sk"].astype(str) + "|" + v["unidad_id"]
    diario = v.groupby(["unique_id", "fecha_local"], as_index=False)["cantidad"].sum()
    fin = pd.Timestamp(fin) if fin is not None else v["fecha_local"].max()
    dias = pd.date_range(v["fecha_local"].min(), fin, freq="D")
    ids = np.sort(info["unique_id"].unique())
    completo = pd.MultiIndex.from_product([ids, dias], names=["unique_id", "ds"]).to_frame(index=False)
    pnl = completo.merge(diario.rename(columns={"fecha_local": "ds", "cantidad": "y"}), how="left",
                         on=["unique_id", "ds"])
    pnl["y"] = pnl["y"].fillna(0.0).astype(float)
    nuevas = int(len(set(diario["unique_id"]) - set(ids)))
    return pnl.sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True), nuevas


def _pronosticar(paquete, historia, fechas):
    """yhat para todas las series de `historia` en `fechas`, sin ajustar nada."""
    info = paquete["info"]
    if paquete.get("estimador") is not None:
        ids = np.sort(historia["unique_id"].unique())
        objetivo = pd.DataFrame({"unique_id": np.repeat(ids, len(fechas)),
                                 "ds": np.tile(pd.to_datetime(fechas), len(ids))})
        X = F.tabla(historia, objetivo, info, paquete.get("centros"))[paquete["columnas"]]
        return objetivo.assign(yhat=np.clip(paquete["estimador"].predict(X), 0, None))
    m = POR_NOMBRE.get(paquete["modelo"])
    if m is None or m.familia != "baseline":
        raise SystemExit("El paquete no trae estimador y %s no es un baseline: reentrene en local con un modelo "
                         "tabular o un baseline." % paquete["modelo"])
    return m.fn(historia, fechas, info, {"centros": paquete.get("centros"), "semilla": 42})


def _bandas(pron, bandas, inicio):
    pron = pron.copy()
    pron["paso"] = (pron["ds"] - inicio).dt.days
    lo = pron["paso"].map(lambda k: (bandas.get(k) or bandas.get(str(k)) or (0, 0))[0])
    hi = pron["paso"].map(lambda k: (bandas.get(k) or bandas.get(str(k)) or (0, 0))[1])
    pron["p10"] = np.minimum(np.clip(pron["yhat"] + lo, 0, None), pron["yhat"])
    pron["p90"] = np.maximum(np.clip(pron["yhat"] + hi, 0, None), pron["yhat"])
    return pron


def predecir(paquete, ventas, hoy=None):
    """Pronostico y backtest con los datos de este servidor. Devuelve el paquete de prediccion (dict)."""
    difs = comprobar_versiones(paquete)
    if difs:
        raise VersionIncompatible("El modelo se entreno con otras versiones: %s. Reentrene en local con la imagen "
                                  "del perfil benchmark (mismas versiones que produccion)." % "; ".join(difs))
    proc = paquete["procedencia"]
    v = ventas if proc == "TODAS" else ventas[ventas["procedencia"] == proc]
    if v.empty:
        v = ventas      # p. ej. el modelo se entreno con el historial del demo (SIMULADO) y aqui solo hay REAL
    v, a_servidor, desconocidos = _traducir(v, paquete)
    if v.empty:
        raise SystemExit("Ninguna venta del DWH corresponde a un producto conocido por el modelo.")
    unidad = paquete["asignador"].asignar(v["lat_aprox"], v["lon_aprox"], v["zona"])
    info = paquete["info"]
    pnl, nuevas = _panel(v, unidad, info, fin=hoy)

    fechas = panel.futuro(pnl)
    pron = _bandas(_pronosticar(paquete, pnl, fechas), paquete.get("bandas") or {}, fechas[0])
    inicio = pnl["ds"].max() - pd.Timedelta(days=HORIZONTE - 1)
    entreno, prueba = panel.partir(pnl, inicio)
    bt = prueba.merge(_pronosticar(paquete, entreno, pd.date_range(inicio, periods=HORIZONTE, freq="D")),
                      on=["unique_id", "ds"], how="left").fillna({"yhat": 0.0})

    def al_servidor(df):
        df = df.merge(info[["unique_id", "producto_sk", "unidad_id"]], on="unique_id", how="left")
        df["producto_sk"] = df["producto_sk"].map(a_servidor)       # sk del DWH de este servidor
        return df[df["producto_sk"].notna()].assign(producto_sk=lambda d: d["producto_sk"].astype(int))

    ultimo = pnl["ds"].max().date()
    return {
        "model_version": "%s+%s" % (paquete["model_version"], ultimo.strftime("%Y%m%d")),
        "model_version_entreno": paquete["model_version"], "modelo": paquete["modelo"], "unidad": paquete["unidad"],
        "generado_utc": datetime.now(timezone.utc).isoformat(), "ultimo_dia": str(ultimo),
        "pronostico": al_servidor(pron), "backtest": al_servidor(bt),
        "unidades": paquete["unidades"], "a_servidor": a_servidor,
        "resumen": {"series": int(info.shape[0]), "lineas_venta": int(len(v)),
                    "productos_sin_modelo": len(desconocidos), "series_nuevas_sin_modelo": nuevas,
                    "wape_backtest": float(np.abs(bt["yhat"] - bt["y"]).sum() / bt["y"].sum())
                    if bt["y"].sum() > 0 else None},
    }


def publicar_comparativa(analisis_dir):
    """Copia analisis/comparativa_modelos.json a ml_evaluacion_modelos si esa corrida no esta (rol dwh_ml)."""
    from contextlib import closing
    from psycopg2.extras import execute_values
    from .benchmark import COLUMNAS, _nulo
    f = pathlib.Path(analisis_dir) / "comparativa_modelos.json"
    if not f.exists():
        return 0
    doc = json.loads(f.read_text(encoding="utf-8"))
    filas = doc.get("filas") or []
    with closing(datos.conectar(escritura=True)) as con, con, con.cursor() as cur:
        cur.execute("SELECT 1 FROM ml_evaluacion_modelos WHERE corrida_id = %s LIMIT 1", (doc.get("corrida_id"),))
        if cur.fetchone():
            return 0
        execute_values(cur, "INSERT INTO ml_evaluacion_modelos (%s) VALUES %%s "
                            "ON CONFLICT (corrida_id, modelo, unidad_espacial, procedencia) DO NOTHING"
                       % ", ".join(COLUMNAS), [tuple(_nulo(r.get(c)) for c in COLUMNAS) for r in filas])
    return len(filas)


def main(argv=None):
    p = argparse.ArgumentParser(description="Pronostico de demanda con el modelo entrenado en local (sin entrenar)")
    p.add_argument("--source", default="dwh")
    p.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", "models"))
    p.add_argument("--analisis-dir", default=os.environ.get("ANALISIS_DIR", "analisis"))
    p.add_argument("--sin-dwh", action="store_true", help="no escribe en el DWH")
    a = p.parse_args(argv)
    ruta = pathlib.Path(a.model_dir) / "demanda.joblib"
    if not ruta.exists():
        raise SystemExit("No hay %s: entrene en local (mlsvc.demanda.train) y suba el archivo." % ruta)
    paquete = joblib.load(ruta)
    try:
        pred = predecir(paquete, datos.cargar(a.source))
    except VersionIncompatible as exc:
        raise SystemExit(str(exc))
    _atomico(pathlib.Path(a.model_dir) / "demanda_prediccion.joblib", lambda t: joblib.dump(pred, t))
    print("predecir: sin entrenar; modelo %s (%s), hasta %s: %s" % (
        pred["modelo"], pred["model_version_entreno"], pred["ultimo_dia"], json.dumps(pred["resumen"])))
    if not a.sin_dwh and a.source == "dwh":
        if datos.puede_escribir():
            print("predecir: %d filas en ml_pronostico_demanda" % guardar_dwh(pred))
            print("predecir: %d filas de la comparativa en ml_evaluacion_modelos" % publicar_comparativa(a.analisis_dir))
        else:
            print("predecir: DWH_ML_PASSWORD no definida; el pronostico no se guarda en el DWH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
