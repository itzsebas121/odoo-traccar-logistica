import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mlsvc.demanda import HORIZONTE, benchmark, datos, espacial, features, metricas, panel
from mlsvc.demanda.modelos import POR_NOMBRE, Modelo
from mlsvc.demanda.train import entrenar
from mlsvc.serve import create_app

RAPIDOS = ["naive", "estacional_7", "media_movil_28", "media_dia_semana_8", "ridge", "hist_gb_poisson", "mlp"]


@pytest.fixture(scope="module")
def ventas():
    return datos.normalizar(datos.sintetico(dias=120, semilla=3, productos=4))


@pytest.fixture(scope="module")
def pnl(ventas):
    a = espacial.Asignador("zona").ajustar(ventas["lat_aprox"], ventas["lon_aprox"], ventas["zona"])
    return panel.construir(ventas, a.asignar(ventas["lat_aprox"], ventas["lon_aprox"], ventas["zona"]))


# ---------------------------------------------------------------- panel y cortes
def test_panel_relleno_con_ceros(pnl):
    p, info = pnl
    dias = p["ds"].nunique()
    assert (p.groupby("unique_id").size() == dias).all()
    assert (p["y"] >= 0).all() and (p["y"] == 0).any()
    assert len(info) == p["unique_id"].nunique()


def test_cortes_consecutivos_al_final(pnl):
    p, _ = pnl
    c = panel.cortes(p, 3)
    assert [(b - a).days for a, b in zip(c, c[1:])] == [HORIZONTE, HORIZONTE]
    assert c[-1] + pd.Timedelta(days=HORIZONTE - 1) == p["ds"].max()
    entreno, prueba = panel.partir(p, c[0])
    assert entreno["ds"].max() < prueba["ds"].min()


def test_features_sin_fuga_del_futuro(pnl):
    """Cambiar la demanda del horizonte no cambia las variables de esos dias (rezagos >= horizonte)."""
    p, info = pnl
    inicio = panel.cortes(p, 1)[0]
    entreno, prueba = panel.partir(p, inicio)
    X1 = features.tabla(entreno, prueba, info)
    alterado = p.copy()
    alterado.loc[alterado["ds"] >= inicio, "y"] += 1000
    entreno2, prueba2 = panel.partir(alterado, inicio)
    X2 = features.tabla(entreno2, prueba2, info)
    pd.testing.assert_frame_equal(X1, X2)
    # en entrenamiento, el rezago 7 de un dia es la venta de 7 dias antes
    filas = features.filas_entrenamiento(entreno).iloc[:50]
    X = features.tabla(entreno, filas, info)
    esperado = [entreno.set_index(["unique_id", "ds"])["y"].get((u, d - pd.Timedelta(days=7)), np.nan)
                for u, d in zip(filas["unique_id"], filas["ds"])]
    np.testing.assert_allclose(X["lag7"].to_numpy(), esperado)


def test_calendario_ecuador():
    cal = features.calendario(pd.to_datetime(["2026-11-02", "2026-11-01", "2026-11-15", "2026-11-30"]))
    assert list(cal["feriado"]) == [1, 0, 0, 0]          # Dia de Difuntos
    assert list(cal["vispera"])[1] == 1
    assert list(cal["dia_pago"]) == [0, 1, 1, 1]


# ---------------------------------------------------------------- espacial
def test_h3_y_clusters_asignan_coordenadas_nuevas(ventas):
    for tipo in ("h3:8", "kmeans", "dbscan", "zona"):
        a = espacial.Asignador(tipo).ajustar(ventas["lat_aprox"], ventas["lon_aprox"], ventas["zona"])
        u = a.asignar(ventas["lat_aprox"], ventas["lon_aprox"], ventas["zona"])
        assert len(set(u)) >= 2, tipo
        nuevo = a.asignar([-1.2401], [-78.6201])[0]
        assert nuevo != espacial.SIN_UBICACION, tipo
        geo = a.unidades(ventas["lat_aprox"], ventas["lon_aprox"], u)
        assert all(json.loads(g["geojson"])["type"] == "Polygon" for g in geo if g["geojson"])
    assert espacial.Asignador("kmeans").ajustar(ventas["lat_aprox"], ventas["lon_aprox"], ventas["zona"]).describir()["k"] >= 2


def test_sin_coordenadas_va_a_su_unidad():
    a = espacial.Asignador("h3:8").ajustar([-1.24], [-78.62], ["centro"])
    assert a.asignar([np.nan], [np.nan])[0] == espacial.SIN_UBICACION


# ---------------------------------------------------------------- metricas y benchmark
def test_metricas():
    m = metricas.calcular([0, 2, 2], [1, 2, 1], escala=0.5)
    assert m["mae"] == pytest.approx(2 / 3) and m["wape"] == pytest.approx(0.5)
    assert m["sesgo"] == 0 and m["mase"] == pytest.approx(4 / 3)


def test_benchmark_compara_y_elige(ventas, tmp_path):
    res = benchmark.correr(ventas, ["zona", "kmeans"], RAPIDOS, n_cortes=2, registro=lambda *_: None)
    t = res["tabla"]
    assert set(t["modelo"]) == set(RAPIDOS)
    assert (t["estado"] == "ok").all(), t[t["estado"] != "ok"][["modelo", "detalle"]]
    km = t[t["unidad_espacial"] == "kmeans"]
    mejor_baseline = km[km["familia"] == "baseline"]["wape_7d"].min()
    el = res["elegido"]
    assert el is not None and el["unidad_espacial"] == "kmeans"      # zona solo es referencia
    assert el["wape_7d"] <= mejor_baseline                           # nunca peor que el mejor baseline
    assert t["elegido"].sum() == 1 and el["regla"] == res["motivo"]
    assert t.loc[t["estado"] == "ok", ["wape_7d_zona", "wape_7d_total", "mejora_pct"]].notna().all().all()
    # agregar no puede empeorar el error: total <= zona <= serie
    ok = t[t["estado"] == "ok"]
    assert (ok["wape_7d_total"] <= ok["wape_7d_zona"] + 1e-9).all()
    assert (ok["wape_7d_zona"] <= ok["wape_7d"] + 1e-9).all()
    benchmark.guardar_archivos(res, tmp_path)
    md = (tmp_path / "comparativa_modelos.md").read_text(encoding="utf-8")
    assert "Modelo elegido" in md and el["modelo"] in md
    texto = (tmp_path / "comparativa_modelos.json").read_text(encoding="utf-8")
    assert json.loads(texto, parse_constant=_sin_constantes)["elegido"]["modelo"] == el["modelo"]   # JSON estricto


def _sin_constantes(nombre):
    raise ValueError("JSON no estricto: aparece %s" % nombre)


def test_sin_nan_ni_infinitos_en_el_json():
    doc = {"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": np.float64("nan")}, "e": "x"}
    limpio = benchmark._sin_nan(doc)
    assert limpio == {"a": None, "b": [1.0, None], "c": {"d": None}, "e": "x"}
    json.dumps(limpio, allow_nan=False)                 # no lanza


def _tabla(filas):
    base = dict(corrida_id="c", procedencia="REAL", estado="ok", seg_entrenar=1.0, seg_predecir=0.0, series=10,
                wape_7d_zona=None, sesgo=0.0)
    cols = benchmark.COLUMNAS
    return pd.DataFrame([dict(base, **f) for f in filas]).reindex(columns=cols)


def test_elegir_compara_con_el_mejor_baseline():
    t = _tabla([
        dict(modelo="estacional_7", familia="baseline", unidad_espacial="kmeans", wape_7d=1.00),
        dict(modelo="media_dia_semana_8", familia="baseline", unidad_espacial="kmeans", wape_7d=0.52),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="kmeans", wape_7d=0.517)])
    tabla, final, motivo = benchmark.elegir(t, mejora_min=0.03)
    # lgbm le gana a estacional_7 pero no mejora 3 % al mejor baseline: se elige el baseline
    assert final["modelo"] == "media_dia_semana_8" and "baseline" in motivo
    assert tabla.set_index("modelo").loc["lgbm", "mejora_pct"] == pytest.approx(0.58, abs=0.01)


def test_elegir_excluye_modelos_con_mucho_sesgo():
    t = _tabla([
        dict(modelo="naive", familia="baseline", unidad_espacial="kmeans", wape_7d=1.0),
        dict(modelo="casi_cero", familia="deep_learning", unidad_espacial="kmeans", wape_7d=0.6, sesgo=-0.9),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="kmeans", wape_7d=0.8, sesgo=-0.1)])
    _, final, motivo = benchmark.elegir(t)
    assert final["modelo"] == "lgbm" and "20.0 %" in motivo


def test_elegir_unidad_por_error_a_nivel_zona():
    """h3 tiene peor WAPE 7d por serie (mas fina) pero mejor al sumar a zona: gana h3."""
    t = _tabla([
        dict(modelo="naive", familia="baseline", unidad_espacial="h3:8", wape_7d=1.2, wape_7d_zona=0.9, series=40),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="h3:8", wape_7d=0.9, wape_7d_zona=0.40, series=40),
        dict(modelo="naive", familia="baseline", unidad_espacial="dbscan", wape_7d=0.9, wape_7d_zona=0.8, series=10),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="dbscan", wape_7d=0.5, wape_7d_zona=0.45,
             series=10),
        dict(modelo="naive", familia="baseline", unidad_espacial="zona", wape_7d=0.5, wape_7d_zona=0.5, series=4),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="zona", wape_7d=0.3, wape_7d_zona=0.3, series=4)])
    _, final, _ = benchmark.elegir(t)
    assert (final["modelo"], final["unidad_espacial"]) == ("lgbm", "h3:8")


def test_elegir_empate_a_nivel_zona_prefiere_mas_series():
    t = _tabla([
        dict(modelo="naive", familia="baseline", unidad_espacial="kmeans", wape_7d=1.0, wape_7d_zona=0.9, series=8),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="kmeans", wape_7d=0.6, wape_7d_zona=0.500,
             series=8),
        dict(modelo="naive", familia="baseline", unidad_espacial="dbscan", wape_7d=1.0, wape_7d_zona=0.9, series=30),
        dict(modelo="lgbm", familia="ml_arboles", unidad_espacial="dbscan", wape_7d=0.7, wape_7d_zona=0.505,
             series=30)])
    _, final, _ = benchmark.elegir(t)
    assert final["unidad_espacial"] == "dbscan"


def test_modelo_sin_libreria_se_omite(ventas, monkeypatch):
    falso = Modelo("falso", "ml_arboles", "no-existe", ("modulo_que_no_existe_xyz",), (), lambda *a: None)
    monkeypatch.setitem(POR_NOMBRE, "falso", falso)
    res = benchmark.correr(ventas, ["zona"], ["naive", "falso"], n_cortes=2, registro=lambda *_: None)
    fila = res["tabla"].set_index("modelo").loc["falso"]
    assert fila["estado"] == "omitido" and "no instalada" in fila["detalle"]


def test_modelo_que_falla_no_detiene(ventas, monkeypatch):
    def roto(*a):
        raise RuntimeError("fallo de prueba")
    monkeypatch.setitem(POR_NOMBRE, "roto", Modelo("roto", "x", "x", (), (), roto))
    res = benchmark.correr(ventas, ["zona"], ["naive", "roto"], n_cortes=2, registro=lambda *_: None)
    t = res["tabla"].set_index("modelo")
    assert t.loc["roto", "estado"] == "error" and t.loc["naive", "estado"] == "ok"


# ---------------------------------------------------------------- entrenamiento y API
@pytest.fixture(scope="module")
def entrenado(ventas, tmp_path_factory):
    d = tmp_path_factory.mktemp("modelos")
    paq = entrenar(ventas, "hist_gb_poisson", "h3:8", "TODAS", d)
    return d, paq


def test_entrenar_guarda_pronostico(entrenado):
    d, paq = entrenado
    assert (d / "demanda.joblib").exists() and (d / "demanda_metrics.json").exists()
    pron = paq["pronostico"]
    assert pron["ds"].nunique() == HORIZONTE
    assert (pron["p10"] <= pron["yhat"]).all() and (pron["yhat"] <= pron["p90"]).all()
    assert paq["metrics"]["wape"] > 0


def test_api_demanda(entrenado):
    d, paq = entrenado
    c = TestClient(create_app(d, d))
    assert c.get("/demanda/health").json()["model_loaded"] is True
    r = c.post("/demanda/predict", json={"producto_sk": 1, "lat": -1.2401, "lon": -78.6201})
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["dias"]) == HORIZONTE and j["unidad_espacial"] == "h3:8"
    assert j["unidad_id"] and j["model_version"] == paq["model_version"]
    assert j["total_unidades"] == pytest.approx(sum(x["unidades"] for x in j["dias"]), abs=0.05)
    assert c.post("/demanda/predict", json={"producto_sk": 1}).status_code == 422
    assert c.post("/demanda/predict", json={"producto_sk": 999, "lat": -1.24, "lon": -78.62}).status_code == 404
    u = c.get("/demanda/unidades").json()
    assert u["type"] == "FeatureCollection" and u["features"]
    assert c.get("/demanda/metrics").json()["modelo"] == "hist_gb_poisson"


def test_api_demanda_sin_modelo_503(tmp_path):
    c = TestClient(create_app(tmp_path, tmp_path))
    assert c.post("/demanda/predict", json={"producto_sk": 1, "lat": -1.24, "lon": -78.62}).status_code == 503
    assert c.get("/demanda/comparativa").status_code == 503


def test_api_demanda_rechaza_archivo_alterado(entrenado, tmp_path):
    d, _ = entrenado
    copia = tmp_path / "modelos"
    shutil.copytree(d, copia)
    with open(copia / "demanda.joblib", "ab") as f:
        f.write(b"x")
    c = TestClient(create_app(copia, copia))
    r = c.post("/demanda/predict", json={"producto_sk": 1, "lat": -1.2401, "lon": -78.6201})
    assert r.status_code == 503 and "no coincide" in r.json()["detail"]
    assert c.get("/demanda/health").json()["status"] == "error"


def test_api_comparativa_con_el_archivo_del_repo(tmp_path):
    analisis = Path(__file__).resolve().parents[1] / "analisis"
    c = TestClient(create_app(tmp_path, analisis))
    r = c.get("/demanda/comparativa")
    assert r.status_code == 200, r.text
    assert r.json()["elegido"]["modelo"] == "media_dia_semana_8"


def test_elegir_solo_modelos_que_el_servidor_puede_usar_sin_entrenar():
    t = _tabla([
        dict(modelo="naive", familia="baseline", unidad_espacial="kmeans", wape_7d=1.0),
        dict(modelo="auto_ets", familia="estadistico", unidad_espacial="kmeans", wape_7d=0.5),
        dict(modelo="lightgbm_tweedie", familia="ml_arboles", unidad_espacial="kmeans", wape_7d=0.6)])
    _, final, _ = benchmark.elegir(t)
    assert final["modelo"] == "lightgbm_tweedie"


# ---------------------------------------------------------------- servidor: predecir sin entrenar
def _ventas_servidor(ventas, desfase=100):
    """Mismas ventas, pero el DWH del servidor numera los productos distinto (mismo id de Odoo)."""
    return ventas.assign(producto_sk=ventas["producto_sk"] + desfase)


def test_paquete_trae_lo_necesario_para_predecir(entrenado):
    _, paq = entrenado
    assert paq["estimador"] is not None and paq["columnas"]
    assert set(paq["versiones"]) >= {"python", "scikit-learn", "lightgbm", "pandas", "numpy"}
    assert {"unique_id", "producto_sk", "unidad_id"} <= set(paq["info"].columns)


def test_predecir_no_entrena_y_traduce_productos(entrenado, ventas, monkeypatch):
    from mlsvc.demanda import predecir as P
    _, paq = entrenado

    def prohibido(*a, **k):
        raise AssertionError("el servidor no debe entrenar")
    monkeypatch.setattr(type(paq["estimador"]), "fit", prohibido)
    pred = P.predecir(paq, _ventas_servidor(ventas))
    pron = pred["pronostico"]
    assert pron["ds"].nunique() == HORIZONTE
    assert set(pron["producto_sk"]) <= set(ventas["producto_sk"] + 100)        # sk del DWH del servidor
    assert (pron["p10"] <= pron["yhat"] + 1e-9).all() and (pron["yhat"] <= pron["p90"] + 1e-9).all()
    # con los mismos datos, el mismo estimador da el mismo pronostico que se calculo al entrenar
    ref = paq["pronostico"].set_index(["unique_id", "ds"])["yhat"]
    got = pron.set_index(["unique_id", "ds"])["yhat"]
    assert np.allclose(got.loc[ref.index].to_numpy(), ref.to_numpy(), atol=1e-6)
    assert len(pred["backtest"]) and pred["backtest"]["y"].notna().all()
    assert pred["model_version"].startswith(paq["model_version"] + "+")


def test_predecir_rechaza_versiones_distintas(entrenado, ventas):
    from mlsvc.demanda import predecir as P
    _, paq = entrenado
    otro = dict(paq, versiones=dict(paq["versiones"], **{"scikit-learn": "0.0.1"}))
    with pytest.raises(P.VersionIncompatible, match="scikit-learn"):
        P.predecir(otro, ventas)


def test_api_usa_la_prediccion_del_servidor(entrenado, ventas, tmp_path):
    import shutil
    import joblib
    from mlsvc.demanda import predecir as P
    d, paq = entrenado
    # como en el servidor: el modelo viaja con su manifiesto (SHA256SUMS)
    shutil.copy(d / "demanda.joblib", tmp_path / "demanda.joblib")
    shutil.copy(d / "SHA256SUMS", tmp_path / "SHA256SUMS")
    c = TestClient(create_app(tmp_path, tmp_path))
    h = c.get("/demanda/health").json()
    assert h["status"] == "ok" and h["prediccion_servidor"] is None and "predecir" in h["aviso"]
    pred = P.predecir(paq, _ventas_servidor(ventas))
    joblib.dump(pred, tmp_path / "demanda_prediccion.joblib")
    h = c.get("/demanda/health").json()
    assert h["prediccion_servidor"]["model_version"] == pred["model_version"]
    r = c.post("/demanda/predict", json={"producto_sk": 101, "lat": -1.2401, "lon": -78.6201})
    assert r.status_code == 200, r.text
    assert r.json()["origen"] == "servidor" and r.json()["producto_sk"] == 1


def test_api_sin_modelo_avisa(tmp_path):
    c = TestClient(create_app(tmp_path, tmp_path))
    h = c.get("/demanda/health").json()
    assert h["model_loaded"] is False and "entrena en local" in h["aviso"]
    assert c.post("/demanda/predict", json={"producto_sk": 1, "lat": -1.24, "lon": -78.62}).status_code == 503


# ---------------------------------------------------------------- servidor: datos que el modelo no vio
def _ventas_nuevas(ventas):
    """Ventas del servidor: un producto que el modelo no conoce (id de Odoo nuevo) y una ubicacion lejana (~25 km)."""
    base = ventas[ventas["fecha_local"] >= ventas["fecha_local"].max() - pd.Timedelta(days=40)]
    nuevo = base[base["producto_sk"] == 1].assign(producto_sk=99, producto_id_odoo=9999, producto="Nuevo")
    lejos = base[base["producto_sk"] == 2].assign(lat_aprox=lambda d: d["lat_aprox"] - 0.23,
                                                  lon_aprox=lambda d: d["lon_aprox"] + 0.0001)
    return pd.concat([ventas, nuevo, lejos], ignore_index=True)


@pytest.fixture(scope="module")
def entrenado_dbscan(ventas, tmp_path_factory):
    d = tmp_path_factory.mktemp("modelos_dbscan")
    return entrenar(ventas, "media_dia_semana_8", "dbscan", "TODAS", d)


def test_asignador_no_fuerza_puntos_lejanos_a_una_unidad_local(entrenado_dbscan, ventas):
    asign = entrenado_dbscan["asignador"]
    cerca = asign.asignar_con_limite(ventas["lat_aprox"].head(50), ventas["lon_aprox"].head(50))
    assert set(cerca) == set(asign.asignar(ventas["lat_aprox"].head(50), ventas["lon_aprox"].head(50)))
    lejos = asign.asignar_con_limite([-1.47, -1.4701, 0.5], [-78.62, -78.6201, -79.0])
    assert lejos[0] == lejos[1] and lejos[0].startswith("s") and lejos[2] != lejos[0]


def test_predecir_pronostica_productos_y_ubicaciones_nuevas(entrenado_dbscan, ventas):
    from mlsvc.demanda import predecir as P
    srv = _ventas_nuevas(ventas).assign(producto_sk=lambda d: d["producto_sk"] + 100)
    pred = P.predecir(entrenado_dbscan, srv)
    pron = pred["pronostico"]
    assert 199 in set(pron["producto_sk"])                               # producto nuevo, con su sk del servidor
    nuevas = [u for u in pred["unidades"] if str(u["unidad_id"]).startswith("s")]
    assert nuevas and pron["unidad_id"].isin([u["unidad_id"] for u in nuevas]).any()
    # la unidad nueva esta donde estan sus ventas (coordenadas exactas, no la unidad local mas cercana)
    assert all(abs(u["centro_lat"] - (-1.24 - 0.23)) < 0.05 for u in nuevas)
    assert pred["resumen"]["productos_nuevos"] == 1 and pred["resumen"]["unidades_nuevas"] >= 1


def test_predecir_desde_hoy_rellena_dias_sin_ventas(entrenado_dbscan, ventas):
    from mlsvc.demanda import predecir as P
    hoy = ventas["fecha_local"].max() + pd.Timedelta(days=10)
    pred = P.predecir(entrenado_dbscan, ventas, hoy=hoy)
    assert pred["pronostico"]["ds"].min() == hoy + pd.Timedelta(days=1)
    assert pred["ultimo_dia"] == str(hoy.date())


def test_predecir_sin_ventas_no_es_error(entrenado_dbscan, ventas):
    from mlsvc.demanda import predecir as P
    with pytest.raises(P.SinVentas):
        P.predecir(entrenado_dbscan, ventas.iloc[0:0])


def test_predecir_tabular_con_productos_nuevos(entrenado, ventas):
    from mlsvc.demanda import predecir as P
    _, paq = entrenado
    pred = P.predecir(paq, _ventas_nuevas(ventas))
    assert 99 in set(pred["pronostico"]["producto_sk"]) and pred["pronostico"]["yhat"].notna().all()


def test_programado_no_termina_por_un_fallo(monkeypatch):
    from mlsvc.demanda import predecir as P
    from mlsvc.demanda import programado
    monkeypatch.setattr(P, "main", lambda argv: (_ for _ in ()).throw(RuntimeError("sin DWH")))
    assert programado.ciclo() == 1
    monkeypatch.setattr(P, "main", lambda argv: (_ for _ in ()).throw(SystemExit("No hay modelo")))
    assert programado.ciclo() == 1
    monkeypatch.setattr(P, "main", lambda argv: 0)
    assert programado.ciclo() == 0
