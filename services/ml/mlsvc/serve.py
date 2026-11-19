import json
import os
import pathlib
from datetime import datetime

import joblib
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

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


class DemandaIn(BaseModel):
    """Producto (id de Odoo o producto_sk del DWH) y ubicacion (lat/lon o unidad_id ya conocida)."""
    producto_id: Optional[int] = None
    producto_sk: Optional[int] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    unidad_id: Optional[str] = None
    horizonte: int = Field(7, ge=1, le=7)

    @model_validator(mode="after")
    def _completo(self):
        if self.producto_id is None and self.producto_sk is None:
            raise ValueError("indique producto_id (Odoo) o producto_sk (DWH)")
        if self.unidad_id is None and (self.lat is None or self.lon is None):
            raise ValueError("indique lat y lon, o unidad_id")
        return self


class _Recargable:
    """Recarga un joblib cuando cambia su firma (mtime, tamano): un reentrenamiento se ve sin reiniciar."""

    def __init__(self, ruta):
        self.ruta, self.obj, self.firma = ruta, None, None

    def __call__(self):
        try:
            st = self.ruta.stat()
        except FileNotFoundError:
            return self.obj
        firma = (st.st_mtime_ns, st.st_size)
        if firma != self.firma:
            self.obj = joblib.load(self.ruta)
            self.firma = firma
        return self.obj


def create_app(model_dir=None, analisis_dir=None) -> FastAPI:
    mdir = pathlib.Path(model_dir or os.environ.get("MODEL_DIR", "models"))
    adir = pathlib.Path(analisis_dir or os.environ.get("ANALISIS_DIR", "analisis"))
    demanda = _Recargable(mdir / "demanda.joblib")
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

    # ------------------------------------------------------------ pronostico de demanda por ubicacion
    def _paquete():
        paq = demanda()
        if paq is None:
            raise HTTPException(503, "No hay modelo de demanda entrenado (python -m mlsvc.demanda.train)")
        return paq

    @app.get("/demanda/health")
    def demanda_health():
        paq = demanda()
        return {"status": "ok", "model_loaded": paq is not None,
                "model_version": None if paq is None else paq["model_version"]}

    @app.post("/demanda/predict")
    def demanda_predict(body: DemandaIn):
        paq = _paquete()
        prods = paq["productos"]
        if body.producto_sk is not None:
            fila = prods[prods["producto_sk"] == body.producto_sk]
        else:
            fila = prods[prods["producto_id_odoo"] == body.producto_id]
        if fila.empty:
            raise HTTPException(404, "El producto no tiene ventas en el historico del modelo")
        fila = fila.iloc[0]
        if body.unidad_id is not None:
            unidad = body.unidad_id
        else:
            unidad = str(paq["asignador"].asignar([body.lat], [body.lon])[0])
        uid = "%s|%s" % (int(fila["producto_sk"]), unidad)
        pron = paq["pronostico"]
        serie = pron[pron["unique_id"] == uid].sort_values("ds").head(body.horizonte)
        sin_historial = serie.empty
        if sin_historial:          # el producto nunca se vendio en esa unidad: demanda esperada 0
            fechas = sorted(pron["ds"].unique())[:body.horizonte]
            dias = [{"fecha": str(pd_fecha(f)), "unidades": 0.0, "p10": 0.0, "p90": 0.0} for f in fechas]
        else:
            dias = [{"fecha": str(pd_fecha(r.ds)), "unidades": round(float(r.yhat), 2),
                     "p10": round(float(r.p10), 2), "p90": round(float(r.p90), 2)} for r in serie.itertuples()]
        centro = next((u for u in paq["unidades"] if u["unidad_id"] == unidad), None)
        return {
            "producto_sk": int(fila["producto_sk"]), "producto_id": int(fila["producto_id_odoo"]),
            "producto": fila["producto"], "categoria": fila["categoria"],
            "unidad_espacial": paq["unidad"], "unidad_id": unidad,
            "centro": None if centro is None else {"lat": centro["centro_lat"], "lon": centro["centro_lon"]},
            "sin_historial": sin_historial, "total_unidades": round(sum(d["unidades"] for d in dias), 2),
            "dias": dias, "modelo": paq["modelo"], "model_version": paq["model_version"],
        }

    @app.get("/demanda/metrics")
    def demanda_metrics():
        f = mdir / "demanda_metrics.json"
        if not f.exists():
            raise HTTPException(503, "No hay modelo de demanda entrenado")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/demanda/comparativa")
    def demanda_comparativa():
        f = adir / "comparativa_modelos.json"
        if not f.exists():
            raise HTTPException(503, "No hay comparativa: corra python -m mlsvc.demanda.benchmark")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/demanda/unidades")
    def demanda_unidades():
        paq = _paquete()
        return {"type": "FeatureCollection", "tipo": paq["unidad"], "features": [
            {"type": "Feature", "geometry": json.loads(u["geojson"]) if u["geojson"] else None,
             "properties": {"unidad_id": u["unidad_id"], "centro_lat": u["centro_lat"], "centro_lon": u["centro_lon"],
                            "lineas": u["lineas"]}} for u in paq["unidades"]]}

    return app


def pd_fecha(valor):
    import pandas as pd
    return pd.Timestamp(valor).date()


app = create_app()
