"""Tabla comparativa de modelos de pronostico de demanda por ubicacion.

    python -m mlsvc.demanda.benchmark --source dwh|sintetico|csv:<ruta>
           [--unidades h3:8,kmeans,dbscan,zona] [--modelos todos|a,b,c] [--cortes 3] [--procedencias auto]

Para cada procedencia (REAL, SIMULADO y TODAS si hay de las dos) y cada unidad espacial arma las series
producto x unidad, hace un backtest con origen movil (N cortes de 7 dias al final, nunca particion aleatoria) y
mide cada modelo con las mismas series y los mismos cortes. Salidas:
  - analisis/comparativa_modelos.md   tabla ordenada por WAPE, explicacion y modelo elegido
  - analisis/comparativa_modelos.csv  y .json (mismas filas)
  - tablas ml_evaluacion_modelos y ml_unidad_espacial del DWH (si DWH_ML_PASSWORD esta definida)

Regla de eleccion: la metrica principal es el WAPE 7d (error sobre el total de los 7 dias de cada serie; el WAPE
diario se informa tambien). Entre los modelos que terminaron bien y le ganan al estacional ingenuo (WAPE 7d menor que
el de estacional_7 en la misma unidad y procedencia; los baselines no son elegibles), el de menor WAPE 7d. Si otro queda a menos de 2 % relativo
de ese WAPE y es mas rapido (entrenar + predecir), gana el mas rapido. La unidad espacial elegida es la del mejor modelo
entre las unidades basadas en coordenadas (h3, kmeans, dbscan); la zona queda como referencia.
"""
import argparse
import json
import os
import pathlib
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import HORIZONTE, datos, espacial, metricas, panel
from .modelos import MODELOS, POR_NOMBRE, REFERENCIA, peso_mb

UNIDADES_DEF = "h3:7,h3:8,h3:9,kmeans,dbscan,zona"
MIN_DIAS = 8 * 7          # historia minima para evaluar una procedencia (rezagos de 28 dias + 3 cortes)
TOLERANCIA = 0.02
COLUMNAS = ["corrida_id", "modelo", "familia", "libreria", "unidad_espacial", "procedencia", "estado", "detalle",
            "cortes", "horizonte_dias", "series", "mae", "rmse", "wape", "wape_7d", "mase", "sesgo", "seg_entrenar",
            "seg_predecir", "mb_dependencias", "puesto", "elegido"]


def evaluar_modelo(modelo, pnl, info, cortes, ctx):
    """Backtest de un modelo: (metricas, predicciones del ultimo corte, segundos)."""
    reales, preds, t_total = [], [], 0.0
    sem_real, sem_pred = [], []
    ultimo = None
    for inicio in cortes:
        entreno, prueba = panel.partir(pnl, inicio)
        fechas = pd.date_range(inicio, periods=HORIZONTE, freq="D")
        ctx["_nombre"] = modelo.nombre
        t0 = time.perf_counter()
        p = modelo.fn(entreno, fechas, info, ctx)
        t_total += time.perf_counter() - t0
        m = prueba.merge(p, on=["unique_id", "ds"], how="left").fillna({"yhat": 0.0})
        tot = m.groupby("unique_id")[["y", "yhat"]].sum()
        sem_real.append(tot["y"].to_numpy())
        sem_pred.append(tot["yhat"].to_numpy())
        reales.append(m["y"].to_numpy())
        preds.append(m["yhat"].to_numpy())
        ultimo = m
    escala = metricas.escala_mase(panel.partir(pnl, cortes[0])[0])
    met = metricas.calcular(np.concatenate(reales), np.concatenate(preds), escala)
    met["wape_7d"] = metricas.wape_semanal(np.concatenate(sem_real), np.concatenate(sem_pred))
    return met, ultimo, t_total


def _procedencias(ventas, pedidas):
    disponibles = sorted(ventas["procedencia"].unique())
    if pedidas != "auto":
        return [p.strip().upper() for p in pedidas.split(",")]
    out = list(disponibles)
    if len(disponibles) > 1:
        out.append("TODAS")
    return out


def _filtrar(ventas, procedencia):
    return ventas if procedencia == "TODAS" else ventas[ventas["procedencia"] == procedencia]


def elegir(tabla):
    """Marca puesto (por WAPE dentro de unidad y procedencia) y el modelo elegido por la regla del modulo."""
    tabla = tabla.copy()
    tabla["puesto"] = None
    tabla["elegido"] = False
    ok = tabla["estado"] == "ok"
    for (u, p), g in tabla[ok].groupby(["unidad_espacial", "procedencia"]):
        orden = g.sort_values("wape_7d").index
        tabla.loc[orden, "puesto"] = range(1, len(orden) + 1)
    candidatos = []
    for (u, p), g in tabla[ok].groupby(["unidad_espacial", "procedencia"]):
        ref = g.loc[g["modelo"] == REFERENCIA, "wape_7d"]
        tope = float(ref.iloc[0]) if len(ref) else np.inf
        g = g[(g["wape_7d"] < tope) & (g["familia"] != "baseline")]     # los baselines son referencia, no se despliegan
        if len(g):
            mejor = g["wape_7d"].min()
            cerca = g[g["wape_7d"] <= mejor * (1 + TOLERANCIA)]
            fila = cerca.assign(t=cerca["seg_entrenar"] + cerca["seg_predecir"]).sort_values(["t", "wape_7d"]).iloc[0]
            candidatos.append(fila)
    if not candidatos:
        return tabla, None
    cand = pd.DataFrame(candidatos)
    # Procedencia de la eleccion: REAL si se pudo evaluar; si no, TODAS; si no, SIMULADO.
    for proc in ("REAL", "TODAS", "SIMULADO"):
        c = cand[cand["procedencia"] == proc]
        if len(c):
            cand = c
            break
    geo = cand[~cand["unidad_espacial"].eq("zona")]
    final = (geo if len(geo) else cand).sort_values("wape_7d").iloc[0]
    tabla.loc[final.name, "elegido"] = True
    return tabla, final


def correr(ventas, unidades, nombres_modelos, n_cortes=3, procedencias="auto", ctx=None, registro=print):
    ctx = dict(ctx or {})
    ctx.setdefault("semilla", 42)
    ctx.setdefault("pasos_dl", int(os.environ.get("BENCH_PASOS_DL", "300")))
    corrida = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filas, unidades_geo, predicciones = [], [], {}
    modelos = MODELOS if nombres_modelos in (None, "todos") else [POR_NOMBRE[n] for n in nombres_modelos]
    pesos = {m.nombre: peso_mb(m.distribuciones) for m in modelos}
    for proc in _procedencias(ventas, procedencias):
        v = _filtrar(ventas, proc)
        dias = (v["fecha_local"].max() - v["fecha_local"].min()).days + 1 if len(v) else 0
        if dias < MIN_DIAS + n_cortes * HORIZONTE:
            registro("benchmark: %s tiene %d dias de ventas (< %d): no se evalua" % (
                proc, dias, MIN_DIAS + n_cortes * HORIZONTE))
            continue
        for tipo in unidades:
            base = dict(corrida_id=corrida, unidad_espacial=tipo, procedencia=proc, cortes=n_cortes,
                        horizonte_dias=HORIZONTE)
            if not espacial.disponible(tipo):
                for m in modelos:
                    filas.append(dict(base, modelo=m.nombre, familia=m.familia, libreria=m.libreria,
                                      estado="omitido", detalle="unidad %s: libreria h3 no instalada" % tipo))
                continue
            asign = espacial.Asignador(tipo).ajustar(v["lat_aprox"], v["lon_aprox"], v["zona"])
            unidad = asign.asignar(v["lat_aprox"], v["lon_aprox"], v["zona"])
            pnl, info = panel.construir(v, unidad)
            geo = asign.unidades(v["lat_aprox"], v["lon_aprox"], unidad)
            for g in geo:
                unidades_geo.append(dict(g, tipo=tipo))
            ctx["centros"] = {g["unidad_id"]: (g["centro_lat"], g["centro_lon"]) for g in geo}
            cortes = panel.cortes(pnl, n_cortes)
            n_series = int(info.shape[0])
            registro("benchmark: %s / %s: %d series, %d dias, unidad %s" % (
                proc, tipo, n_series, pnl["ds"].nunique(), json.dumps(asign.describir())))
            for m in modelos:
                fila = dict(base, modelo=m.nombre, familia=m.familia, libreria=m.libreria, series=n_series,
                            mb_dependencias=pesos[m.nombre])
                if not m.disponible():
                    fila.update(estado="omitido", detalle="libreria no instalada (%s)" % ", ".join(m.modulos))
                elif m.max_series and n_series > m.max_series:
                    fila.update(estado="omitido", detalle="%d series > limite %d (modelo por serie, lento)" % (
                        n_series, m.max_series))
                else:
                    try:
                        met, ultimo, seg = evaluar_modelo(m, pnl, info, cortes, ctx)
                        fila.update(met, estado="ok", seg_entrenar=round(seg, 3), seg_predecir=0.0)
                        predicciones[(m.nombre, tipo, proc)] = ultimo
                        registro("  %-20s WAPE7d=%.3f WAPE=%.3f MAE=%.3f MASE=%.3f (%.1f s)" % (
                            m.nombre, met["wape_7d"], met["wape"], met["mae"], met["mase"], seg))
                    except Exception as exc:     # un modelo que falla no detiene la comparativa
                        fila.update(estado="error", detalle=("%s: %s" % (type(exc).__name__, exc))[:500])
                        registro("  %-20s ERROR %s" % (m.nombre, fila["detalle"]))
                        if os.environ.get("BENCH_DEBUG"):
                            traceback.print_exc()
                filas.append(fila)
    tabla = pd.DataFrame(filas).reindex(columns=COLUMNAS)
    tabla, final = elegir(tabla)
    return {"corrida_id": corrida, "tabla": tabla, "elegido": None if final is None else final.to_dict(),
            "unidades": pd.DataFrame(unidades_geo), "predicciones": predicciones}


# ---------------------------------------------------------------------------------------------------- salidas
FAMILIAS = {
    "baseline": "Reglas simples sin aprendizaje: el piso que cualquier modelo debe superar.",
    "intermitente": "Metodos clasicos para demanda con muchos dias en cero (Croston y variantes).",
    "estadistico": "Modelos de series de tiempo por serie: suavizado exponencial, ARIMA, Prophet.",
    "ml_lineal": "Regresiones globales (una para todas las series) con variables de calendario y rezagos.",
    "ml_arboles": "Ensambles de arboles globales; manejan bien ceros, no linealidades e interacciones.",
    "deep_learning": "Redes neuronales: MLP sobre las variables y redes de series (LSTM, N-BEATS, N-HiTS, TFT).",
    "fundacional": "Modelo preentrenado con millones de series (zero-shot): no se entrena con estos datos.",
}


def _fmt(v, d=3):
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else ("%.*f" % (d, v))


def informe_md(res):
    t = res["tabla"]
    el = res["elegido"]
    lineas = ["# Comparativa de modelos de pronóstico de demanda por ubicación", "",
              "Corrida `%s`. Backtest con origen móvil: %s cortes de %d días al final del histórico, mismas series "
              "(producto × unidad espacial) y mismos cortes para todos los modelos." % (
                  res["corrida_id"], int(t["cortes"].dropna().iloc[0]) if t["cortes"].notna().any() else "-",
                  HORIZONTE), "",
              "**Métrica principal: WAPE 7d** (error absoluto del total de los 7 días de cada serie / unidades reales; menor es "
              "mejor). WAPE = el mismo error medido día a día (más duro: el ruido diario de un conteo ralo no se "
              "compensa). MASE < 1: menos "
              "error que repetir la semana anterior. Sesgo > 0: sobreestima.", ""]
    if el:
        lineas += ["## Modelo elegido", "",
                   "**%s** (%s, librería %s) con unidad espacial **%s**, procedencia %s: WAPE 7d %s, WAPE diario %s, MAE %s, MASE %s." % (
                       el["modelo"], el["familia"], el["libreria"], el["unidad_espacial"], el["procedencia"],
                       _fmt(el["wape_7d"]), _fmt(el["wape"]), _fmt(el["mae"]), _fmt(el["mase"])), "",
                   "Regla: menor WAPE entre los modelos que le ganan al estacional ingenuo (`estacional_7`); si otro "
                   "queda a menos de 2 % del mejor y es más rápido, gana el más rápido. Los baselines son la referencia y no se eligen. La unidad se elige entre las "
                   "basadas en coordenadas (H3, KMeans, DBSCAN); la zona del DWH es la referencia.", ""]
    else:
        lineas += ["## Modelo elegido", "", "Ningún modelo superó al estacional ingenuo: no hay ganador.", ""]
    for (proc, unidad), g in t.groupby(["procedencia", "unidad_espacial"], sort=False):
        lineas += ["## %s · unidad %s" % (proc, unidad), "",
                   "| # | Modelo | Familia | Librería | WAPE 7d | WAPE día | MAE | RMSE | MASE | Sesgo | Seg. | MB deps | "
                   "Estado |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        g = g.assign(_o=g["wape_7d"].fillna(np.inf)).sort_values(["_o", "modelo"])
        for _, f in g.iterrows():
            marca = " ⭐" if f["elegido"] else ""
            estado = f["estado"] if f["estado"] == "ok" else "%s: %s" % (f["estado"], f["detalle"] or "")
            lineas.append("| %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                "" if pd.isna(f["puesto"]) else int(f["puesto"]), f["modelo"], marca, f["familia"], f["libreria"],
                _fmt(f["wape_7d"]), _fmt(f["wape"]), _fmt(f["mae"]), _fmt(f["rmse"]), _fmt(f["mase"]), _fmt(f["sesgo"]),
                _fmt(f["seg_entrenar"], 1), _fmt(f["mb_dependencias"], 0), estado))
        lineas.append("")
    lineas += ["## Familias de modelos", ""] + ["- **%s**: %s" % (k, v) for k, v in FAMILIAS.items()] + [""]
    lineas += ["## Modelos", ""] + ["- `%s` (%s): %s" % (m.nombre, m.libreria, m.descripcion) for m in MODELOS] + [""]
    return "\n".join(lineas)


def guardar_archivos(res, carpeta):
    carpeta = pathlib.Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    t = res["tabla"]
    t.to_csv(carpeta / "comparativa_modelos.csv", index=False)
    doc = {"corrida_id": res["corrida_id"], "elegido": res["elegido"],
           "filas": json.loads(t.to_json(orient="records", force_ascii=False))}
    (carpeta / "comparativa_modelos.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str),
                                                      encoding="utf-8")
    (carpeta / "comparativa_modelos.md").write_text(informe_md(res), encoding="utf-8")
    return carpeta


def _nulo(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)) and np.isnan(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


def guardar_dwh(res):
    """Escribe la corrida en ml_evaluacion_modelos y reemplaza las unidades en ml_unidad_espacial (rol dwh_ml)."""
    from contextlib import closing
    from psycopg2.extras import execute_values
    t = res["tabla"]
    cols = [c for c in COLUMNAS]
    with closing(datos.conectar(escritura=True)) as con, con, con.cursor() as cur:
        execute_values(cur, "INSERT INTO ml_evaluacion_modelos (%s) VALUES %%s "
                            "ON CONFLICT (corrida_id, modelo, unidad_espacial, procedencia) DO NOTHING"
                       % ", ".join(cols), [tuple(_nulo(r[c]) for c in cols) for r in t.to_dict("records")])
        u = res["unidades"]
        if len(u):
            u = u.drop_duplicates(["tipo", "unidad_id"])
            cur.execute("DELETE FROM ml_unidad_espacial WHERE tipo = ANY(%s)", (sorted(u["tipo"].unique()),))
            execute_values(cur, "INSERT INTO ml_unidad_espacial (tipo, unidad_id, centro_lat, centro_lon, geojson, "
                                "lineas) VALUES %s",
                           [(r["tipo"], r["unidad_id"], _nulo(r["centro_lat"]), _nulo(r["centro_lon"]),
                             r["geojson"], int(r["lineas"])) for r in u.to_dict("records")])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", default="dwh")
    p.add_argument("--unidades", default=os.environ.get("BENCH_UNIDADES", UNIDADES_DEF))
    p.add_argument("--modelos", default="todos")
    p.add_argument("--cortes", type=int, default=3)
    p.add_argument("--procedencias", default="auto")
    p.add_argument("--salida", default=os.environ.get("ANALISIS_DIR", "analisis"))
    p.add_argument("--sin-dwh", action="store_true", help="no escribe en el DWH")
    a = p.parse_args(argv)
    ventas = datos.cargar(a.source)
    print("benchmark: %d lineas de venta, %s a %s, procedencias %s" % (
        len(ventas), ventas["fecha_local"].min().date(), ventas["fecha_local"].max().date(),
        dict(ventas["procedencia"].value_counts())))
    nombres = "todos" if a.modelos == "todos" else [n.strip() for n in a.modelos.split(",")]
    res = correr(ventas, [u.strip() for u in a.unidades.split(",") if u.strip()], nombres, a.cortes, a.procedencias)
    carpeta = guardar_archivos(res, a.salida)
    print("benchmark: tabla en %s" % (carpeta / "comparativa_modelos.md"))
    if not a.sin_dwh and a.source == "dwh":
        if datos.puede_escribir():
            guardar_dwh(res)
            print("benchmark: corrida %s guardada en ml_evaluacion_modelos" % res["corrida_id"])
        else:
            print("benchmark: DWH_ML_PASSWORD no definida; la tabla no se guarda en el DWH")
    el = res["elegido"]
    print("benchmark: elegido %s" % (json.dumps({k: _nulo(el[k]) for k in ("modelo", "unidad_espacial", "procedencia",
                                                                          "wape_7d", "wape", "mase")}) if el else "ninguno"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
