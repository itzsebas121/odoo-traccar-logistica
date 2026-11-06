import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)

DEPOT = {"lat": -1.24, "lon": -78.61}


def stops(n, demand=1):
    return [{"id": 100 + i, "lat": -1.24 - 0.005 * i, "lon": -78.61 + 0.004 * (i % 3),
             "demand": demand} for i in range(1, n + 1)]


def body(n, caps, demand=1, **kw):
    d = {"depot": DEPOT, "stops": stops(n, demand),
         "vehicles": [{"id": 7 + i, "capacity": c} for i, c in enumerate(caps)],
         "time_limit_s": 1}
    d.update(kw)
    return d


def test_optimize_respeta_capacidad():
    r = client.post("/optimize", json=body(6, [3, 3]))
    assert r.status_code == 200
    data = r.json()
    assigned = [s["id"] for rt in data["routes"] for s in rt["stops"]]
    assert sorted(assigned) == [101, 102, 103, 104, 105, 106]
    assert data["unassigned"] == []
    assert all(rt["load"] <= 3 for rt in data["routes"])
    assert data["optimization_version"]


def test_optimize_sobre_capacidad():
    r = client.post("/optimize", json=body(7, [3, 3]))
    assert r.status_code == 200
    data = r.json()
    assert len(data["unassigned"]) == 1
    assert data["unassigned"][0]["reason"] == "sin_capacidad"
    assert sum(len(rt["stops"]) for rt in data["routes"]) == 6


def test_sin_capacidad_cuando_no_cabe_en_el_residual():
    # Demandas 2,2,2 y capacidades 3,3: la capacidad total (6) alcanza, pero tras
    # cargar una parada en cada vehiculo el residual es 1 y la tercera (2) no cabe.
    r = client.post("/optimize", json=body(3, [3, 3], demand=2))
    assert r.status_code == 200
    data = r.json()
    assert len(data["unassigned"]) == 1
    assert data["unassigned"][0]["reason"] == "sin_capacidad"
    assert sum(len(rt["stops"]) for rt in data["routes"]) == 2
    assert all(rt["load"] <= 3 for rt in data["routes"])


def test_razon_sin_asignar():
    from app.optimizer import unassigned_reason

    assert unassigned_reason(2, [1, 1]) == "sin_capacidad"  # no cabe en ningun vehiculo
    assert unassigned_reason(1, [0, 0]) == "sin_capacidad"
    assert unassigned_reason(2, [1, 2]) == "sin_ruta"       # cabe en el segundo
    assert unassigned_reason(1, [1]) == "sin_ruta"          # cabe justo
    assert unassigned_reason(0, [0]) == "sin_ruta"          # demanda 0 siempre cabe


def test_optimize_sin_vehiculos_422():
    assert client.post("/optimize", json=body(2, [])).status_code == 422


def test_optimize_demanda_negativa_422():
    b = body(2, [3])
    b["stops"][0]["demand"] = -1
    assert client.post("/optimize", json=b).status_code == 422


def test_secuencia_base_1_sin_deposito():
    b = body(4, [10])
    data = client.post("/optimize", json=b).json()
    assert len(data["routes"]) == 1
    ruta = data["routes"][0]
    ids = [s["id"] for s in ruta["stops"]]
    # el deposito no se emite como parada: salen exactamente las paradas pedidas, una vez cada una
    assert sorted(ids) == sorted(s["id"] for s in b["stops"])
    assert [s["sequence"] for s in ruta["stops"]] == [1, 2, 3, 4]
    assert ruta["distance_km"] > 0


def test_distancia_de_una_parada_coincide_con_la_matriz():
    b = body(1, [5])
    parada = b["stops"][0]
    m = client.post("/matrix", json={"points": [DEPOT, parada]}).json()
    ruta = client.post("/optimize", json=b).json()["routes"][0]
    # deposito -> parada -> deposito
    assert ruta["distance_km"] == pytest.approx((m["distance_m"][0][1] + m["distance_m"][1][0]) / 1000,
                                                abs=0.001)
    assert ruta["duration_min"] == pytest.approx((m["duration_s"][0][1] + m["duration_s"][1][0]) / 60,
                                                 abs=0.01)
    assert ruta["load"] == 1


def test_vehiculos_sin_paradas_no_aparecen():
    # 1 parada y 3 vehiculos: solo uno la atiende; los otros dos no aparecen en routes
    b = body(1, [10, 10, 10])
    data = client.post("/optimize", json=b).json()
    assert len(data["routes"]) == 1
    assert data["routes"][0]["vehicle_id"] in {v["id"] for v in b["vehicles"]}
    assert [s["id"] for s in data["routes"][0]["stops"]] == [101]
    # con mas vehiculos que paradas ninguna ruta emitida esta vacia ni repite vehiculo
    data = client.post("/optimize", json=body(2, [10, 10, 10])).json()
    assert data["routes"]
    assert all(len(rt["stops"]) >= 1 for rt in data["routes"])
    vehiculos = [rt["vehicle_id"] for rt in data["routes"]]
    assert len(vehiculos) == len(set(vehiculos))


# --- etiqueta de proveedor (D2) ---

def test_optimize_sin_paradas_etiqueta_haversine(monkeypatch):
    monkeypatch.delenv("ROUTING_OSRM_URL", raising=False)
    r = client.post("/optimize", json=body(0, [5]))
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "estimado_haversine"
    assert data["routes"] == [] and data["unassigned"] == []


def test_optimize_sin_paradas_etiqueta_osrm_sin_llamar(osrm_stub):
    server = osrm_stub(lambda path: {"code": "Ok"})
    data = client.post("/optimize", json=body(0, [5])).json()
    assert data["source"] == "osrm"  # el proveedor configurado
    assert server.hits == []         # y sin pedir ninguna matriz


def test_optimize_con_osrm_usa_distancias_de_osrm(osrm_stub):
    n = 4  # deposito + 3 paradas, todos los arcos a 1000 m
    tabla = [[0 if i == j else 1000 for j in range(n)] for i in range(n)]
    osrm_stub(lambda path: {"code": "Ok", "distances": tabla, "durations": tabla})
    data = client.post("/optimize", json=body(3, [10])).json()
    assert data["source"] == "osrm"
    assert data["routes"][0]["distance_km"] == 4.0  # 4 arcos: deposito, 3 paradas, deposito


def test_optimize_con_osrm_null_usa_estimacion(osrm_stub):
    n = 4  # deposito + 3 paradas; los pares inalcanzables vienen como null
    nulos = [[0 if i == j else None for j in range(n)] for i in range(n)]
    osrm_stub(lambda path: {"code": "Ok", "distances": nulos, "durations": nulos})
    data = client.post("/optimize", json=body(3, [10])).json()
    assert data["source"] == "estimado_haversine"
    assert data["routes"][0]["distance_km"] > 0  # el solver no vio arcos gratis


# --- tope de tamano y presupuesto de tiempo ---

def test_optimize_mas_de_200_paradas_422():
    r = client.post("/optimize", json=body(201, [300]))
    assert r.status_code == 422
    assert any("200" in e["msg"] for e in r.json()["detail"])


def test_optimize_200_paradas_ok(monkeypatch):
    monkeypatch.delenv("ROUTING_OSRM_URL", raising=False)
    r = client.post("/optimize", json=body(200, [200]))
    assert r.status_code == 200
    data = r.json()
    assert data["unassigned"] == []
    assert sum(len(rt["stops"]) for rt in data["routes"]) == 200


def test_solver_limit_mantiene_la_peticion_dentro_de_30s():
    assert main.solver_limit_s(5, 0.0) == 5.0  # si sobra tiempo se respeta lo pedido
    for pedido, transcurrido in [(30, 0.0), (30, 4.0), (30, 7.0), (30, 10.0), (5, 3.0)]:
        limite = main.solver_limit_s(pedido, transcurrido)
        assert 1.0 <= limite <= pedido
        assert transcurrido + limite <= main.TOTAL_BUDGET_S


def test_el_tiempo_de_la_matriz_se_descuenta_del_limite(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(main, "_now", lambda: clock["t"])

    class LentoProvider:
        label = "estimado_haversine"

        def matrix(self, points):
            clock["t"] += 10.0  # obtener la matriz consumio 10 s
            n = len(points)
            ceros = [[0] * n for _ in range(n)]
            return ceros, ceros, self.label

    visto = {}

    def optimize_falso(dist, dur, demands, capacities, limit):
        visto["limit"] = limit
        return [], []

    monkeypatch.setattr(main, "provider", lambda: LentoProvider())
    monkeypatch.setattr(main, "optimize", optimize_falso)
    r = client.post("/optimize", json=body(2, [5], time_limit_s=30))
    assert r.status_code == 200
    assert visto["limit"] == pytest.approx(30 - 10 - main.SAFETY_MARGIN_S)
