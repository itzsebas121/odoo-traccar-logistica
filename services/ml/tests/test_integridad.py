from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mlsvc import integridad
from mlsvc.serve import create_app
from mlsvc.simulate import generar
from mlsvc.train import entrenar

MODELOS = Path(__file__).resolve().parents[1] / "models"
BODY = {"vehicle_code": "VEH-01", "reference_datetime": "2026-03-02T14:00:00Z", "origin_zone": "centro"}


def _archivo(carpeta, nombre="m.joblib", contenido=b"datos"):
    ruta = carpeta / nombre
    ruta.write_bytes(contenido)
    return ruta


def test_registrar_y_verificar(tmp_path):
    ruta = _archivo(tmp_path)
    integridad.registrar(ruta)
    integridad.verificar(ruta)                       # no lanza


def test_archivo_sin_hash_no_se_carga(tmp_path):
    ruta = _archivo(tmp_path)
    with pytest.raises(integridad.ModeloNoVerificado, match="no tiene hash"):
        integridad.verificar(ruta)


def test_archivo_alterado_no_se_carga(tmp_path):
    ruta = _archivo(tmp_path)
    integridad.registrar(ruta)
    ruta.write_bytes(b"datos cambiados")
    with pytest.raises(integridad.ModeloNoVerificado, match="no coincide"):
        integridad.verificar(ruta)


def test_registrar_de_nuevo_actualiza_sin_duplicar(tmp_path):
    ruta = _archivo(tmp_path)
    integridad.registrar(ruta)
    ruta.write_bytes(b"otro")
    integridad.registrar(ruta)
    lineas = (tmp_path / integridad.MANIFIESTO).read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1 and lineas[0].endswith("  m.joblib")
    integridad.verificar(ruta)


def test_registrar_conserva_los_demas_archivos(tmp_path):
    a = _archivo(tmp_path, "a.joblib", b"a")
    b = _archivo(tmp_path, "b.joblib", b"b")
    integridad.registrar(a)
    integridad.registrar(b)
    integridad.verificar(a)
    integridad.verificar(b)


def test_modelos_del_repo_estan_registrados_y_sin_cambios():
    for nombre in ("model.joblib", "demanda.joblib"):
        integridad.verificar(MODELOS / nombre)


def test_entrenar_registra_el_modelo(tmp_path):
    entrenar(generar(dias=60, seed=1), tmp_path)
    integridad.verificar(tmp_path / "model.joblib")


def test_servidor_no_carga_modelo_alterado(tmp_path):
    entrenar(generar(dias=60, seed=1), tmp_path)
    with open(tmp_path / "model.joblib", "ab") as f:
        f.write(b"x")
    c = TestClient(create_app(tmp_path))
    assert c.get("/health").json()["model_loaded"] is False
    r = c.post("/predict", json=BODY)
    assert r.status_code == 503 and "no coincide" in r.json()["detail"]
