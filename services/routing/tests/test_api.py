import math
import time

import pytest
from fastapi.testclient import TestClient

from app import distance
from app.main import app

client = TestClient(app)

A = {"lat": -1.24, "lon": -78.61}
B = {"lat": -1.27, "lon": -78.64}


def haversine_m(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def route_params():
    return {"origin_lat": A["lat"], "origin_lon": A["lon"],
            "dest_lat": B["lat"], "dest_lon": B["lon"]}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_matrix_estimado_sin_osrm(monkeypatch):
    monkeypatch.delenv("ROUTING_OSRM_URL", raising=False)
    r = client.post("/matrix", json={"points": [A, B]})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "estimado_haversine"
    expected = haversine_m(A, B) * 1.3
    assert abs(body["distance_m"][0][1] - expected) <= expected * 0.01
    assert body["distance_m"][0][0] == 0


def test_coordenadas_invalidas_422():
    r = client.post("/matrix", json={"points": [{"lat": 95, "lon": 0}, B]})
    assert r.status_code == 422


def test_route_fallback_linea_recta(monkeypatch):
    monkeypatch.delenv("ROUTING_OSRM_URL", raising=False)
    r = client.get("/route", params=route_params())
    assert r.status_code == 200
    body = r.json()
    assert len(body["geometry"]) == 2
    assert body["source"] == "estimado_haversine"
    assert body["distance_km"] > 0 and body["duration_min"] > 0


def test_osrm_caido_cae_a_estimacion(monkeypatch):
    monkeypatch.setenv("ROUTING_OSRM_URL", "http://127.0.0.1:9")
    r = client.post("/matrix", json={"points": [A, B]})
    assert r.status_code == 200
    assert r.json()["source"] == "estimado_haversine"
    r = client.get("/route", params=route_params())
    assert r.status_code == 200
    assert r.json()["source"] == "estimado_haversine"


# --- proveedor OSRM (contra un OSRM falso) ---

def test_osrm_ok_usa_osrm(osrm_stub):
    server = osrm_stub(lambda path: {"code": "Ok",
                                     "distances": [[0, 1234], [4321, 0]],
                                     "durations": [[0, 99], [88, 0]]})
    r = client.post("/matrix", json={"points": [A, B]})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "osrm"
    assert body["distance_m"] == [[0, 1234], [4321, 0]]
    assert body["duration_s"] == [[0, 99], [88, 0]]
    # OSRM espera lon,lat (no lat,lon)
    assert server.hits[0].startswith("/table/v1/driving/-78.61,-1.24;-78.64,-1.27")


@pytest.mark.parametrize("clave", ["distances", "durations"])
def test_osrm_con_null_cae_a_estimacion(osrm_stub, clave):
    # un null es un par inalcanzable: no puede tratarse como un arco gratis (0)
    payload = {"code": "Ok", "distances": [[0, 1000], [1000, 0]],
               "durations": [[0, 60], [60, 0]]}
    payload[clave] = [[0, None], [None, 0]]
    osrm_stub(lambda path: payload)
    r = client.post("/matrix", json={"points": [A, B]})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "estimado_haversine"
    assert body["distance_m"][0][1] > 0 and body["duration_s"][1][0] > 0


@pytest.mark.parametrize("clave", ["distances", "durations"])
@pytest.mark.parametrize("mala", [
    [[0, 1, 2], [1, 0, 3], [2, 3, 0]],  # 3x3 para 2 puntos
    [[0]],                              # demasiado chica
    [[0, 1], [1, 0], [2, 2]],           # filas de mas
    [[0, 1], [1]],                      # fila corta
])
def test_osrm_forma_invalida_cae_a_estimacion(osrm_stub, clave, mala):
    buena = [[0, 1000], [1000, 0]]
    payload = {"code": "Ok", "distances": buena, "durations": buena}
    payload[clave] = mala
    osrm_stub(lambda path: payload)
    r = client.post("/matrix", json={"points": [A, B]})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "estimado_haversine"
    assert len(body["distance_m"]) == 2 and len(body["duration_s"]) == 2


def test_osrm_lento_cae_a_estimacion_sin_esperar(monkeypatch, osrm_stub):
    monkeypatch.setattr(distance, "OSRM_TIMEOUT_S", 0.3)

    def lento(path):
        time.sleep(1.5)
        return {"code": "Ok"}

    osrm_stub(lento)
    t0 = time.monotonic()
    r = client.post("/matrix", json={"points": [A, B]})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200
    assert r.json()["source"] == "estimado_haversine"
    assert elapsed < 1.2  # corta en el timeout, no espera los 1,5 s de OSRM


def test_route_osrm_ok(osrm_stub):
    server = osrm_stub(lambda path: {"code": "Ok", "routes": [{
        "geometry": {"coordinates": [[-78.61, -1.24], [-78.62, -1.25], [-78.64, -1.27]]},
        "distance": 5000.0, "duration": 600.0}]})
    r = client.get("/route", params=route_params())
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "osrm"
    assert body["geometry"] == [[-1.24, -78.61], [-1.25, -78.62], [-1.27, -78.64]]
    assert body["distance_km"] == 5.0
    assert body["duration_min"] == 10.0
    assert server.hits[0].startswith("/route/v1/driving/-78.61,-1.24;-78.64,-1.27")


def test_route_osrm_sin_ruta_cae_a_estimacion(osrm_stub):
    osrm_stub(lambda path: {"code": "NoRoute"})
    r = client.get("/route", params=route_params())
    assert r.status_code == 200
    assert r.json()["source"] == "estimado_haversine"


# --- tope de tamano ---

def puntos(n):
    return [{"lat": -1.24 - 0.0001 * i, "lon": -78.61} for i in range(n)]


def test_matrix_mas_de_200_puntos_422():
    r = client.post("/matrix", json={"points": puntos(201)})
    assert r.status_code == 422
    assert any("200" in e["msg"] for e in r.json()["detail"])


def test_matrix_200_puntos_ok(monkeypatch):
    monkeypatch.delenv("ROUTING_OSRM_URL", raising=False)
    r = client.post("/matrix", json={"points": puntos(200)})
    assert r.status_code == 200
    assert len(r.json()["distance_m"]) == 200
