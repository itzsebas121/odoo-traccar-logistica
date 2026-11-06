import pytest
from fastapi.testclient import TestClient
from mlsvc.serve import create_app
from mlsvc.simulate import generar
from mlsvc.train import entrenar

BODY = {"vehicle_code": "VEH-01", "reference_datetime": "2026-03-02T14:00:00Z", "origin_zone": "centro"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("models")
    entrenar(generar(dias=90, seed=1), d)
    return TestClient(create_app(d))


def test_predict_probabilidades(client):
    r = client.post("/predict", json=BODY)
    assert r.status_code == 200
    j = r.json()
    assert abs(sum(j["probabilities"].values()) - 1) < 1e-6
    assert j["predicted_zone"] == max(j["probabilities"], key=j["probabilities"].get)
    assert len(j["alternatives"]) == 3
    assert j["predicted_zone"] not in [a["zone"] for a in j["alternatives"]]
    assert j["model_version"]
    alt = [a["probability"] for a in j["alternatives"]]
    assert alt == sorted(alt, reverse=True)


def test_predict_sin_modelo_503(tmp_path):
    c = TestClient(create_app(tmp_path))
    assert c.get("/health").json() == {"status": "ok", "model_loaded": False}
    assert c.post("/predict", json=BODY).status_code == 503


def test_zona_invalida_422(client):
    assert client.post("/predict", json={**BODY, "origin_zone": "marte"}).status_code == 422


def test_predict_recarga_tras_reentrenar(tmp_path):
    entrenar(generar(dias=60, seed=1), tmp_path)
    c = TestClient(create_app(tmp_path))
    v1 = c.post("/predict", json=BODY).json()["model_version"]
    entrenar(generar(dias=60, seed=2), tmp_path)  # reentrena con el servicio ya arrancado
    v2 = c.post("/predict", json=BODY).json()["model_version"]
    assert v2 != v1
    assert v2 == c.get("/metrics").json()["model_version"]


def test_metrics_y_health(client):
    assert client.get("/health").json()["model_loaded"] is True
    assert "baseline_accuracy" in client.get("/metrics").json()
