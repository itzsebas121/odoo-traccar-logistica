import os
import time
from typing import List, Optional

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field, field_validator

from .distance import DistanceProvider
from .optimizer import MAX_TIME_LIMIT_S, OPTIMIZATION_VERSION, optimize

app = FastAPI(title="Servicio de rutas")

MAX_POINTS = 200          # puntos por peticion en /matrix
MAX_STOPS = 200           # paradas por peticion en /optimize
TOTAL_BUDGET_S = 30.0     # tope de toda la peticion /optimize (matriz + solver)
SAFETY_MARGIN_S = 1.0     # holgura para armar el modelo y serializar la respuesta
MIN_SOLVER_S = 1.0
_now = time.monotonic


def provider():
    return DistanceProvider(os.environ.get("ROUTING_OSRM_URL") or None)


def solver_limit_s(requested_s, elapsed_s):
    """Tiempo para el solver: lo pedido, sin pasar de lo que queda del presupuesto de la
    peticion despues de lo que ya se gasto (p. ej. esperando a OSRM)."""
    remaining = TOTAL_BUDGET_S - SAFETY_MARGIN_S - elapsed_s
    return max(MIN_SOLVER_S, min(float(requested_s), remaining))


def _at_most(items, maximum, what):
    if len(items) > maximum:
        raise ValueError(f"se admiten como máximo {maximum} {what} por petición "
                         f"(recibidos {len(items)})")
    return items


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class MatrixIn(BaseModel):
    points: List[Point] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def _limit_points(cls, v):
        return _at_most(v, MAX_POINTS, "puntos")


class Stop(Point):
    id: int
    demand: int = Field(default=1, ge=0)


class Vehicle(BaseModel):
    id: int
    capacity: int = Field(ge=0)


class OptimizeIn(BaseModel):
    depot: Point
    stops: List[Stop] = []
    vehicles: List[Vehicle] = Field(min_length=1)
    time_limit_s: Optional[int] = Field(default=None, ge=1, le=MAX_TIME_LIMIT_S)

    @field_validator("stops")
    @classmethod
    def _limit_stops(cls, v):
        return _at_most(v, MAX_STOPS, "paradas")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/matrix")
def matrix(body: MatrixIn):
    pts = [(p.lat, p.lon) for p in body.points]
    dist, dur, source = provider().matrix(pts)
    return {"distance_m": dist, "duration_s": dur, "source": source}


@app.get("/route")
def route(origin_lat: float = Query(ge=-90, le=90), origin_lon: float = Query(ge=-180, le=180),
          dest_lat: float = Query(ge=-90, le=90), dest_lon: float = Query(ge=-180, le=180)):
    geom, km, minutes, source = provider().route((origin_lat, origin_lon), (dest_lat, dest_lon))
    return {"geometry": geom, "distance_km": round(km, 3),
            "duration_min": round(minutes, 2), "source": source}


@app.post("/optimize")
def optimize_route(body: OptimizeIn):
    started = _now()
    prov = provider()
    if not body.stops:
        # sin paradas no se pide matriz: se informa el proveedor configurado (D2)
        return {"routes": [], "unassigned": [], "source": prov.label,
                "optimization_version": OPTIMIZATION_VERSION}
    pts = [(body.depot.lat, body.depot.lon)] + [(s.lat, s.lon) for s in body.stops]
    dist, dur, source = prov.matrix(pts)
    demands = [0] + [s.demand for s in body.stops]
    requested = body.time_limit_s or int(os.environ.get("ROUTING_TIME_LIMIT_S", "5"))
    limit = solver_limit_s(requested, _now() - started)
    routes, unassigned = optimize(dist, dur, demands, [v.capacity for v in body.vehicles], limit)
    return {
        "routes": [{
            "vehicle_id": body.vehicles[v].id,
            "stops": [{"id": body.stops[n - 1].id, "sequence": i + 1} for i, n in enumerate(nodes)],
            "distance_km": round(d / 1000.0, 3),
            "duration_min": round(t / 60.0, 2),
            "load": load,
        } for v, nodes, d, t, load in routes],
        "unassigned": [{"id": body.stops[n - 1].id, "reason": r} for n, r in unassigned],
        "source": source,
        "optimization_version": OPTIMIZATION_VERSION,
    }
