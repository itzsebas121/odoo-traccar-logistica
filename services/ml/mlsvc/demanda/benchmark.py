"""Tabla comparativa de modelos de pronostico de demanda por ubicacion.

    python -m mlsvc.demanda.benchmark --source dwh|sintetico|csv:<ruta>
           [--unidades h3:8,kmeans,dbscan,zona] [--modelos todos|a,b,c] [--cortes 3] [--procedencias auto]

Para cada procedencia (REAL, SIMULADO y TODAS si hay de las dos) y cada unidad espacial arma las series
producto x unidad, hace un backtest con origen movil (N cortes de 7 dias al final, nunca particion aleatoria) y
mide cada modelo con las mismas series y los mismos cortes. Salidas:
  - analisis/comparativa_modelos.md   tabla ordenada por WAPE, explicacion y modelo elegido
  - analisis/comparativa_modelos.csv  y .json (mismas filas)
  - tablas ml_evaluacion_modelos y ml_unidad_espacial del DWH (si DWH_ML_PASSWORD esta definida)

Regla de eleccion (por unidad espacial y procedencia):
  1. Metrica: WAPE 7d (error sobre el total de los 7 dias de cada serie). El WAPE diario se informa pero no decide: un
     modelo que predice casi cero gana en WAPE diario con conteos ralos.
  2. Referencia: el MEJOR baseline del grupo (no solo estacional_7). mejora_pct = cuanto baja el WAPE 7d frente a el.
  3. Candidatos: modelos no baseline que terminaron bien, con |sesgo| <= SESGO_MAX y mejora_pct >= MEJORA_MIN, y que
     se puedan servir sin reentrenar (modelos tabulares globales: el servidor solo predice, ver predecir.py).
     El de menor WAPE 7d; si otro queda a menos de TOLERANCIA relativo y es mas rapido, el mas rapido.
     Si ninguno cumple, se elige el mejor baseline (y el informe lo dice).
  4. Unidad espacial: entre las basadas en coordenadas (h3, kmeans, dbscan), la de menor WAPE 7d a nivel ZONA (sus
     predicciones sumadas a producto x zona, comun a todas las unidades); a menos de TOLERANCIA, la de mas series
     (mas detalle espacial). La zona del DWH queda como referencia.
  5. Procedencia: REAL si se pudo evaluar; si no, TODAS; si no, SIMULADO.
"""
import argparse
import json
import math
import os
import pathlib
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import HORIZONTE, datos, espacial, metricas, panel
from .modelos import MODELOS, POR_NOMBRE, peso_mb, servible

UNIDADES_DEF = "h3:7,h3:8,h3:9,kmeans,dbscan,zona"
MIN_DIAS = 8 * 7          # historia minima para evaluar una procedencia (rezagos de 28 dias + 3 cortes)
TOLERANCIA = 0.02
MEJORA_MIN = float(os.environ.get("BENCH_MEJORA_MIN", "0.03"))   # mejora relativa minima sobre el mejor baseline
SESGO_MAX = float(os.environ.get("BENCH_SESGO_MAX", "0.5"))      # |sesgo| maximo de un modelo elegible
COLUMNAS = ["corrida_id", "modelo", "familia", "libreria", "unidad_espacial", "procedencia", "estado", "detalle",
            "cortes", "horizonte_dias", "series", "mae", "rmse", "wape", "wape_7d", "wape_7d_zona", "wape_7d_total",
            "mejora_pct", "mase", "sesgo", "seg_entrenar", "seg_predecir", "mb_dependencias", "puesto", "elegido"]


def evaluar_modelo(modelo, pnl, info, cortes, ctx, zona_de_unidad=None):
    """Backtest de un modelo: (metricas, predicciones del ultimo corte, segundos).
    zona_de_unidad: {unidad_id: zona} para medir el WAPE 7d a nivel producto x zona."""
    reales, preds, t_total = [], [], 0.0
    sem_real, sem_pred, semanas = [], [], []
    claves = info[["unique_id", "producto_sk", "unidad_id"]].copy()
    claves["zona"] = claves["unidad_id"].map(zona_de_unidad or {}).fillna(claves["unidad_id"])
    ultimo = None
    for i, inicio in enumerate(cortes):
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
        semanas.append(tot.reset_index().merge(claves, on="unique_id", how="left").assign(corte=i))
        reales.append(m["y"].to_numpy())
        preds.append(m["yhat"].to_numpy())
        ultimo = m
    escala = metricas.escala_mase(panel.partir(pnl, cortes[0])[0])
    met = metricas.calcular(np.concatenate(reales), np.concatenate(preds), escala)
    met["wape_7d"] = metricas.wape_semanal(np.concatenate(sem_real), np.concatenate(sem_pred))
    sem = pd.concat(semanas, ignore_index=True)
    met["wape_7d_zona"] = metricas.wape_agregado(sem, ["corte", "producto_sk", "zona"])
    met["wape_7d_total"] = metricas.wape_agregado(sem, ["corte", "producto_sk"])
    return met, ultimo, t_total


def zonas_de_unidades(zonas, unidad):
    """{unidad_id: zona mas frecuente entre sus ventas}."""
    df = pd.DataFrame({"u": np.asarray(unidad, dtype=object).astype(str),
                       "z": pd.Series(zonas).fillna("(sin zona)").astype(str).to_numpy()})
    return df.groupby("u")["z"].agg(lambda s: s.value_counts().index[0]).to_dict()


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


def _mas_rapido(g):
    mejor = g["wape_7d"].min()
    cerca = g[g["wape_7d"] <= mejor * (1 + TOLERANCIA)]
    t = cerca["seg_entrenar"].fillna(0) + cerca["seg_predecir"].fillna(0)
    return cerca.assign(_t=t).sort_values(["_t", "wape_7d"]).index[0]


def elegir(tabla, mejora_min=None, sesgo_max=None):
    """Marca puesto (por WAPE 7d dentro de unidad y procedencia), mejora_pct y el elegido por la regla del modulo.
    Devuelve (tabla, fila elegida | None, motivo)."""
    mejora_min = MEJORA_MIN if mejora_min is None else mejora_min
    sesgo_max = SESGO_MAX if sesgo_max is None else sesgo_max
    tabla = tabla.copy()
    tabla["puesto"] = None
    tabla["elegido"] = False
    tabla["mejora_pct"] = np.nan
    ok = tabla["estado"] == "ok"
    candidatos = {}          # indice de la fila -> True si es un baseline (nadie lo supero en su grupo)
    for _, g in tabla[ok].groupby(["unidad_espacial", "procedencia"]):
        tabla.loc[g.sort_values("wape_7d").index, "puesto"] = range(1, len(g) + 1)
        base = g[g["familia"] == "baseline"]
        ref = float(base["wape_7d"].min()) if len(base) else np.nan
        if np.isfinite(ref) and ref > 0:
            tabla.loc[g.index, "mejora_pct"] = (100.0 * (ref - g["wape_7d"]) / ref).round(2)
        mejora = tabla.loc[g.index, "mejora_pct"]
        aptos = ((g["familia"] != "baseline") & (g["sesgo"].abs() <= sesgo_max)
                 & pd.Series([servible(n, f) for n, f in zip(g["modelo"], g["familia"])], index=g.index))
        if np.isfinite(ref):
            aptos &= mejora.fillna(-np.inf) >= 100.0 * mejora_min
        if aptos.any():
            candidatos[_mas_rapido(g[aptos])] = False
        elif len(base):
            candidatos[base.sort_values("wape_7d").index[0]] = True
    if not candidatos:
        return tabla, None, "Ningun modelo termino bien: no hay eleccion."
    cand = tabla.loc[list(candidatos)].assign(_baseline=[candidatos[i] for i in candidatos])
    for proc in ("REAL", "TODAS", "SIMULADO"):
        if (cand["procedencia"] == proc).any():
            cand = cand[cand["procedencia"] == proc]
            break
    if (~cand["_baseline"]).any():       # se prefieren las unidades donde un modelo supera al baseline
        cand = cand[~cand["_baseline"]]
    geo = cand[~cand["unidad_espacial"].eq("zona")]
    pool = geo if len(geo) else cand
    nivel = pool["wape_7d_zona"].astype(float).fillna(pool["wape_7d"].astype(float))
    cerca = pool[nivel <= nivel.min() * (1 + TOLERANCIA)]
    idx = cerca.assign(_n=nivel[cerca.index]).sort_values(["series", "_n"], ascending=[False, True]).index[0]
    tabla.loc[idx, "elegido"] = True
    final = tabla.loc[idx]
    if cand.loc[idx, "_baseline"]:
        motivo = ("Ningun modelo mejora al mejor baseline en al menos %.0f %% de WAPE 7d con |sesgo| <= %.2f: se "
                  "elige el baseline %s." % (100 * mejora_min, sesgo_max, final["modelo"]))
    else:
        motivo = ("%s mejora %.1f %% el WAPE 7d del mejor baseline de su unidad; unidad %s elegida por el WAPE 7d a "
                  "nivel zona (%.3f)." % (final["modelo"], float(final["mejora_pct"]), final["unidad_espacial"],
                                           float(nivel[idx])))
    return tabla, final, motivo


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
            zona_de = zonas_de_unidades(v["zona"].to_numpy(), unidad)
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
                        met, ultimo, seg = evaluar_modelo(m, pnl, info, cortes, ctx, zona_de)
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
    tabla, final, motivo = elegir(tabla)
    elegido = None if final is None else dict(final.to_dict(), regla=motivo)
    return {"corrida_id": corrida, "tabla": tabla, "elegido": elegido, "motivo": motivo,
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
              "**Métrica principal: WAPE 7d** (error absoluto del total de los 7 días de cada serie / unidades reales; "
              "menor es mejor). **7d zona / 7d total**: el mismo error tras sumar las predicciones a producto × zona del "
              "DWH y a producto; es el nivel común para comparar unidades espaciales de distinto tamaño. **Mejora %**: "
              "cuánto baja el WAPE 7d frente al mejor baseline de la misma unidad. WAPE día = el error día a día: **no "
              "decide**, porque un modelo que predice casi cero gana ahí con conteos ralos (se le ve en el sesgo, cerca "
              "de −1). MASE < 1: menos error que repetir la semana anterior. Sesgo > 0: sobreestima.", ""]
    if el:
        lineas += ["## Modelo elegido", "",
                   "**%s** (%s, librería %s) con unidad espacial **%s**, procedencia %s: WAPE 7d %s (zona %s, total "
                   "%s), mejora %s %% sobre el mejor baseline, WAPE diario %s, MAE %s, MASE %s, sesgo %s." % (
                       el["modelo"], el["familia"], el["libreria"], el["unidad_espacial"], el["procedencia"],
                       _fmt(el["wape_7d"]), _fmt(el.get("wape_7d_zona")), _fmt(el.get("wape_7d_total")),
                       _fmt(el.get("mejora_pct"), 1), _fmt(el["wape"]), _fmt(el["mae"]), _fmt(el["mase"]),
                       _fmt(el["sesgo"])), "",
                   "**Por qué:** %s" % res.get("motivo", ""), "",
                   "Regla: cada modelo se compara con el **mejor baseline** de su unidad y procedencia. Es elegible si "
                   "baja el WAPE 7d al menos %.0f %%, su |sesgo| es ≤ %.2f y se puede servir sin reentrenar (modelo "
                   "tabular global: el servidor solo predice); entre los elegibles gana el de menor "
                   "WAPE 7d (a menos de 2 %%, el más rápido). Si ninguno lo es, se elige el baseline. La unidad se "
                   "elige entre las basadas en coordenadas (H3, KMeans, DBSCAN) por el WAPE 7d a nivel zona (a menos "
                   "de 2 %%, la de más series); la zona del DWH es la referencia." % (100 * MEJORA_MIN, SESGO_MAX), ""]
    else:
        lineas += ["## Modelo elegido", "", res.get("motivo") or "No hay ganador.", ""]
    for (proc, unidad), g in t.groupby(["procedencia", "unidad_espacial"], sort=False):
        lineas += ["## %s · unidad %s" % (proc, unidad), "",
                   "| # | Modelo | Familia | Librería | WAPE 7d | 7d zona | 7d total | Mejora % | WAPE día | MAE | "
                   "RMSE | MASE | Sesgo | Seg. | MB deps | Estado |",
                   "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        g = g.assign(_o=g["wape_7d"].fillna(np.inf)).sort_values(["_o", "modelo"])
        for _, f in g.iterrows():
            marca = " ⭐" if f["elegido"] else ""
            estado = f["estado"] if f["estado"] == "ok" else "%s: %s" % (f["estado"], f["detalle"] or "")
            lineas.append("| %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                "" if pd.isna(f["puesto"]) else int(f["puesto"]), f["modelo"], marca, f["familia"], f["libreria"],
                _fmt(f["wape_7d"]), _fmt(f["wape_7d_zona"]), _fmt(f["wape_7d_total"]), _fmt(f["mejora_pct"], 1),
                _fmt(f["wape"]), _fmt(f["mae"]), _fmt(f["rmse"]), _fmt(f["mase"]), _fmt(f["sesgo"]),
                _fmt(f["seg_entrenar"], 1), _fmt(f["mb_dependencias"], 0), estado))
        lineas.append("")
    lineas += ["## Familias de modelos", ""] + ["- **%s**: %s" % (k, v) for k, v in FAMILIAS.items()] + [""]
    lineas += ["## Modelos", ""] + ["- `%s` (%s): %s" % (m.nombre, m.libreria, m.descripcion) for m in MODELOS] + [""]
    return "\n".join(lineas)


def _sin_nan(obj):
    """Copia de obj con NaN e infinitos como null: JSON estricto (FastAPI y otros lectores no aceptan NaN)."""
    if isinstance(obj, dict):
        return {k: _sin_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sin_nan(v) for v in obj]
    v = _nulo(obj)
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def guardar_archivos(res, carpeta):
    carpeta = pathlib.Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    t = res["tabla"]
    t.to_csv(carpeta / "comparativa_modelos.csv", index=False)
    doc = {"corrida_id": res["corrida_id"], "elegido": res["elegido"], "motivo": res.get("motivo"),
           "filas": json.loads(t.to_json(orient="records", force_ascii=False))}
    (carpeta / "comparativa_modelos.json").write_text(
        json.dumps(_sin_nan(doc), indent=2, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")
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
    from .modelos import dispositivo
    print("benchmark: modelos de PyTorch en %s" % dispositivo())
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
