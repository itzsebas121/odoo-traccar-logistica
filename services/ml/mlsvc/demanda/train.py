"""Entrena el modelo de demanda elegido y publica el pronostico de los proximos dias.

    python -m mlsvc.demanda.train --source dwh [--modelo X] [--unidad h3:8] [--procedencia TODAS]

Sin --modelo/--unidad/--procedencia usa el ganador de analisis/comparativa_modelos.json (benchmark). Si no hay
comparativa, usa lightgbm_tweedie con h3:8 (el ganador esperado segun la literatura y el benchmark de referencia).

1. Backtest del ultimo corte de 7 dias: errores por dia del horizonte -> bandas p10/p90 del pronostico.
2. Reentrena con todo el historico y pronostica los 7 dias siguientes al ultimo dia con ventas.
3. Guarda models/demanda.joblib y models/demanda_metrics.json de forma atomica (temporal + os.replace) y, si
   DWH_ML_PASSWORD esta definida, escribe ml_pronostico_demanda (pronostico y backtest) y ml_unidad_espacial.
"""
import argparse
import hashlib
import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from . import HORIZONTE, datos, espacial, metricas, panel
from .modelos import POR_NOMBRE

POR_DEFECTO = {"modelo": "lightgbm_tweedie", "unidad_espacial": "h3:8", "procedencia": "TODAS"}


def _atomico(ruta, escribir):
    ruta = pathlib.Path(ruta)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=ruta.name + ".")
    os.close(fd)
    try:
        escribir(tmp)
        os.replace(tmp, ruta)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def eleccion(analisis_dir):
    f = pathlib.Path(analisis_dir) / "comparativa_modelos.json"
    if f.exists():
        el = json.loads(f.read_text(encoding="utf-8")).get("elegido")
        if el:
            return {k: el[k] for k in POR_DEFECTO}
    return dict(POR_DEFECTO)


def entrenar(ventas, modelo, unidad, procedencia, model_dir, ctx=None):
    ctx = dict(ctx or {}, semilla=42)
    m = POR_NOMBRE[modelo]
    if not m.disponible():
        raise SystemExit("El modelo %s necesita %s, que no esta instalado en esta imagen." % (
            modelo, ", ".join(m.modulos)))
    v = ventas if procedencia == "TODAS" else ventas[ventas["procedencia"] == procedencia]
    if v.empty:
        raise SystemExit("No hay ventas con procedencia %s" % procedencia)
    asign = espacial.Asignador(unidad).ajustar(v["lat_aprox"], v["lon_aprox"], v["zona"])
    u = asign.asignar(v["lat_aprox"], v["lon_aprox"], v["zona"])
    pnl, info = panel.construir(v, u)
    geo = asign.unidades(v["lat_aprox"], v["lon_aprox"], u)
    ctx["centros"] = {g["unidad_id"]: (g["centro_lat"], g["centro_lon"]) for g in geo}

    # 1. backtest del ultimo corte
    inicio = panel.cortes(pnl, 1)[0]
    entreno, prueba = panel.partir(pnl, inicio)
    fechas_bt = pd.date_range(inicio, periods=HORIZONTE, freq="D")
    bt = prueba.merge(m.fn(entreno, fechas_bt, info, ctx), on=["unique_id", "ds"], how="left").fillna({"yhat": 0.0})
    bt["paso"] = (bt["ds"] - inicio).dt.days
    resid = bt["y"] - bt["yhat"]
    bandas = {int(k): (float(np.quantile(r, 0.1)), float(np.quantile(r, 0.9))) for k, r in resid.groupby(bt["paso"])}
    met = metricas.calcular(bt["y"], bt["yhat"], metricas.escala_mase(entreno))

    # 2. modelo con todo el historico
    fechas = panel.futuro(pnl)
    pron = m.fn(pnl, fechas, info, ctx)
    pron["paso"] = (pron["ds"] - fechas[0]).dt.days
    pron["p10"] = np.clip(pron["yhat"] + pron["paso"].map(lambda k: bandas.get(k, (0, 0))[0]), 0, None)
    pron["p90"] = np.clip(pron["yhat"] + pron["paso"].map(lambda k: bandas.get(k, (0, 0))[1]), 0, None)
    pron["p90"] = np.maximum(pron["p90"], pron["yhat"])
    pron["p10"] = np.minimum(pron["p10"], pron["yhat"])
    pron = pron.merge(info, on="unique_id", how="left")
    bt = bt.merge(info, on="unique_id", how="left")

    huella = hashlib.sha1(pd.util.hash_pandas_object(pnl[["unique_id", "y"]], index=False).values.tobytes()).hexdigest()
    version = "%s-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), modelo, huella[:8])
    productos = (v.groupby("producto_sk").agg(producto=("producto", "first"), producto_id_odoo=("producto_id_odoo", "first"),
                                              categoria=("categoria", "first")).reset_index())
    metrics = dict(met, modelo=modelo, familia=m.familia, libreria=m.libreria, unidad_espacial=unidad,
                   procedencia=procedencia, model_version=version, horizonte_dias=HORIZONTE,
                   corte_backtest=str(inicio.date()), ultimo_dia=str(pnl["ds"].max().date()),
                   series=int(info.shape[0]), unidades=len(geo), lineas_venta=int(len(v)),
                   espacial=asign.describir(), bandas_p10_p90=bandas)
    paquete = {"model_version": version, "modelo": modelo, "unidad": unidad, "procedencia": procedencia,
               "asignador": asign, "pronostico": pron, "backtest": bt, "productos": productos,
               "unidades": geo, "metrics": metrics}
    model_dir = pathlib.Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    _atomico(model_dir / "demanda.joblib", lambda t: joblib.dump(paquete, t))
    _atomico(model_dir / "demanda_metrics.json",
             lambda t: pathlib.Path(t).write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str),
                                                  encoding="utf-8"))
    return paquete


def guardar_dwh(paquete):
    from contextlib import closing
    from psycopg2.extras import execute_values
    tipo, ver, mod = paquete["unidad"], paquete["model_version"], paquete["modelo"]
    filas = []
    for tipo_reg, df, real in (("pronostico", paquete["pronostico"], False), ("backtest", paquete["backtest"], True)):
        for r in df.itertuples(index=False):
            filas.append((tipo_reg, r.ds.date(), int(r.producto_sk), tipo, str(r.unidad_id), round(float(r.yhat), 3),
                          round(float(r.y), 3) if real else None,
                          round(float(getattr(r, "p10", np.nan)), 3) if not real else None,
                          round(float(getattr(r, "p90", np.nan)), 3) if not real else None, mod, ver))
    with closing(datos.conectar(escritura=True)) as con, con, con.cursor() as cur:
        execute_values(cur, "INSERT INTO ml_pronostico_demanda (tipo_registro, fecha_objetivo, producto_sk, "
                            "tipo_unidad, unidad_id, unidades_pred, unidades_real, p10, p90, modelo, model_version) "
                            "VALUES %s ON CONFLICT DO NOTHING", filas, page_size=2000)
        cur.execute("DELETE FROM ml_unidad_espacial WHERE tipo = %s", (tipo,))
        execute_values(cur, "INSERT INTO ml_unidad_espacial (tipo, unidad_id, centro_lat, centro_lon, geojson, lineas) "
                            "VALUES %s", [(tipo, g["unidad_id"], g["centro_lat"], g["centro_lon"], g["geojson"],
                                           g["lineas"]) for g in paquete["unidades"]])
    return len(filas)


def main(argv=None):
    p = argparse.ArgumentParser(description="Entrena el modelo de demanda elegido y publica su pronostico")
    p.add_argument("--source", default="dwh")
    p.add_argument("--modelo")
    p.add_argument("--unidad")
    p.add_argument("--procedencia")
    p.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", "models"))
    p.add_argument("--analisis-dir", default=os.environ.get("ANALISIS_DIR", "analisis"))
    p.add_argument("--sin-dwh", action="store_true")
    a = p.parse_args(argv)
    el = eleccion(a.analisis_dir)
    modelo, unidad = a.modelo or el["modelo"], a.unidad or el["unidad_espacial"]
    procedencia = (a.procedencia or el["procedencia"]).upper()
    paq = entrenar(datos.cargar(a.source), modelo, unidad, procedencia, a.model_dir)
    m = paq["metrics"]
    print(json.dumps({k: m[k] for k in ("modelo", "unidad_espacial", "procedencia", "wape", "mae", "mase", "series",
                                        "model_version")}, ensure_ascii=False))
    if not a.sin_dwh and a.source == "dwh":
        if datos.puede_escribir():
            print("demanda: %d filas en ml_pronostico_demanda" % guardar_dwh(paq))
        else:
            print("demanda: DWH_ML_PASSWORD no definida; el pronostico no se guarda en el DWH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
