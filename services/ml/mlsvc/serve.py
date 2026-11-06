import json
import os
import pathlib
from datetime import datetime

import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from . import ZONAS
from .features import build_features


class PredictIn(BaseModel):
    vehicle_code: str
    reference_datetime: datetime
    origin_zone: str

    @field_validator("origin_zone")
    @classmethod
    def _zona(cls, v):
        if v not in ZONAS:
            raise ValueError(f"origin_zone invalida; use una de {ZONAS}")
        return v


def create_app(model_dir=None) -> FastAPI:
    mdir = pathlib.Path(model_dir or os.environ.get("MODEL_DIR", "models"))
    app = FastAPI(title="Prediccion de destinos")
    model_file = mdir / "model.joblib"
    state = {"model": None, "firma": None}

    def cargar():
        # Recarga model.joblib cuando cambia su firma (mtime, tamano): un reentrenamiento
        # con el servicio ya arrancado se refleja en /predict sin reiniciar. Un stat por llamada.
        try:
            st = model_file.stat()
        except FileNotFoundError:
            return state["model"]
        firma = (st.st_mtime_ns, st.st_size)
        if firma != state["firma"]:
            state["model"] = joblib.load(model_file)
            state["firma"] = firma
        return state["model"]

    cargar()

    @app.get("/health")
    def health():
        return {"status": "ok", "model_loaded": cargar() is not None}

    @app.post("/predict")
    def predict(body: PredictIn):
        m = cargar()
        if m is None:
            raise HTTPException(503, "No hay modelo entrenado")
        pipe = m["pipeline"]
        # Un reference_datetime sin zona horaria (naive) se interpreta como UTC (R7).
        X = build_features([body.vehicle_code], [body.reference_datetime.isoformat()], [body.origin_zone])
        proba = pipe.predict_proba(X)[0]
        pares = sorted(zip(pipe.classes_, (float(p) for p in proba)), key=lambda t: -t[1])
        return {
            "predicted_zone": pares[0][0],
            "probabilities": {z: p for z, p in pares},
            "alternatives": [{"zone": z, "probability": p} for z, p in pares[1:4]],
            "model_version": m["model_version"],
        }

    @app.get("/metrics")
    def metrics():
        f = mdir / "metrics.json"
        if not f.exists():
            raise HTTPException(503, "No hay modelo entrenado")
        return json.loads(f.read_text())

    return app


app = create_app()
