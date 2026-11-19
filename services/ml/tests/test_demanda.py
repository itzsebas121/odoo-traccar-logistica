import json

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
    ref = t[(t["modelo"] == "estacional_7") & (t["unidad_espacial"] == "kmeans")]["wape"].iloc[0]
    el = res["elegido"]
    assert el is not None and el["unidad_espacial"] == "kmeans"      # zona solo es referencia
    assert el["wape"] < ref                                          # le gana al estacional ingenuo
    assert t["elegido"].sum() == 1
    benchmark.guardar_archivos(res, tmp_path)
    md = (tmp_path / "comparativa_modelos.md").read_text(encoding="utf-8")
    assert "Modelo elegido" in md and el["modelo"] in md
    assert json.loads((tmp_path / "comparativa_modelos.json").read_text(encoding="utf-8"))["elegido"]["modelo"] == el["modelo"]


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
