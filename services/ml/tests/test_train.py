import json
import pandas as pd
import pytest
from mlsvc.simulate import generar
from mlsvc.train import entrenar, split_temporal

METRIC_KEYS = ["accuracy", "precision_macro", "recall_macro", "f1_macro", "confusion_matrix", "labels",
               "baseline_accuracy", "baseline_f1", "n_train", "n_test", "split_date",
               "procedencia_counts", "model_version"]


@pytest.fixture(scope="module")
def df():
    return generar(dias=90, seed=1)


def test_split_temporal(df):
    tr, te = split_temporal(df)
    assert tr["fecha_hora"].max() < te["fecha_hora"].min()
    assert len(tr) > len(te) > 0


def test_metricas_completas(df, tmp_path):
    m = entrenar(df, tmp_path)
    saved = json.loads((tmp_path / "metrics.json").read_text())
    assert (tmp_path / "model.joblib").exists()
    for k in METRIC_KEYS:
        assert k in saved
    n = len(saved["labels"])
    cm = saved["confusion_matrix"]
    assert len(cm) == n and all(len(r) == n for r in cm)
    assert m["model_version"] == saved["model_version"]


def test_supera_baseline_en_patron(df, tmp_path):
    m = entrenar(df, tmp_path)
    assert m["accuracy"] > m["baseline_accuracy"]


def test_procedencia_reportada(df, tmp_path):
    mixed = df.copy()
    mixed.loc[mixed.index[:50], "procedencia"] = "REAL"
    m = entrenar(mixed, tmp_path)
    assert m["procedencia_counts"]["REAL"] == 50
    assert m["procedencia_counts"]["SIMULADO"] == len(df) - 50
    assert set(generar(dias=5, seed=2)["procedencia"]) == {"SIMULADO"}
