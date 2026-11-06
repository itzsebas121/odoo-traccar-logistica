"""Entrenamiento: python -m mlsvc.train --source csv:<ruta> | simulate | dwh"""
import argparse
import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score)
from sklearn.pipeline import Pipeline

from .features import build_features, make_preprocessor

COLUMNAS = ["vehiculo_codigo", "fecha_hora", "zona_origen", "zona_destino", "procedencia"]
SEED = 42


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    falta = set(COLUMNAS) - set(df.columns)
    if falta:
        raise ValueError(f"Faltan columnas: {sorted(falta)}")
    df = df[COLUMNAS].dropna().copy()
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], utc=True)
    return df.sort_values("fecha_hora", kind="stable").reset_index(drop=True)


def split_temporal(df: pd.DataFrame, frac=0.8):
    df = _normalizar(df)
    corte = df["fecha_hora"].iloc[int(len(df) * frac)]
    return df[df["fecha_hora"] < corte], df[df["fecha_hora"] >= corte]


def _xy(d):
    return build_features(d["vehiculo_codigo"], d["fecha_hora"], d["zona_origen"]), d["zona_destino"]


def _pipe(clf):
    return Pipeline([("prep", make_preprocessor()), ("clf", clf)])


def entrenar(df: pd.DataFrame, model_dir) -> dict:
    model_dir = pathlib.Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    df = _normalizar(df)
    tr, te = split_temporal(df)
    Xtr, ytr = _xy(tr)
    Xte, yte = _xy(te)
    modelo = _pipe(RandomForestClassifier(n_estimators=200, random_state=SEED, n_jobs=-1)).fit(Xtr, ytr)
    base = _pipe(DummyClassifier(strategy="most_frequent")).fit(Xtr, ytr)
    pred, pred_b = modelo.predict(Xte), base.predict(Xte)
    labels = sorted(set(ytr) | set(yte))
    kw = dict(average="macro", zero_division=0)
    csv = df.assign(fecha_hora=df["fecha_hora"].astype(str)).to_csv(index=False)
    digest = hashlib.sha1(csv.encode()).hexdigest()[:10]
    metrics = {
        "accuracy": float(accuracy_score(yte, pred)),
        "precision_macro": float(precision_score(yte, pred, **kw)),
        "recall_macro": float(recall_score(yte, pred, **kw)),
        "f1_macro": float(f1_score(yte, pred, **kw)),
        "confusion_matrix": confusion_matrix(yte, pred, labels=labels).tolist(),
        "labels": labels,
        "baseline_accuracy": float(accuracy_score(yte, pred_b)),
        "baseline_f1": float(f1_score(yte, pred_b, **kw)),
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "split_date": te["fecha_hora"].min().isoformat(),
        "procedencia_counts": {k: int(v) for k, v in df["procedencia"].value_counts().items()},
        "model_version": f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{digest}",
    }
    joblib.dump({"pipeline": modelo, "model_version": metrics["model_version"]}, model_dir / "model.joblib")
    (model_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    return metrics


def cargar_fuente(source: str, data_dir) -> pd.DataFrame:
    if source.startswith("csv:"):
        return pd.read_csv(source[4:])
    if source == "simulate":
        from .simulate import generar
        df = generar()
        data_dir = pathlib.Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(data_dir / "viajes_simulados.csv", index=False)
        return df
    if source == "dwh":
        import psycopg2
        dsn = os.environ.get("DWH_DSN")
        if not dsn:
            raise SystemExit("DWH_DSN no esta definido")
        with psycopg2.connect(dsn) as con:
            return pd.read_sql_query(f"SELECT {', '.join(COLUMNAS)} FROM v_viajes_entrenamiento", con)
    raise SystemExit(f"Fuente desconocida: {source} (use csv:<ruta>, simulate o dwh)")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="simulate")
    p.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", "models"))
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"))
    a = p.parse_args(argv)
    m = entrenar(cargar_fuente(a.source, a.data_dir), a.model_dir)
    print(json.dumps({k: m[k] for k in ("accuracy", "baseline_accuracy", "n_train", "n_test", "model_version")}))


if __name__ == "__main__":
    main()
