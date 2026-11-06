"""Proveedores de distancia: OSRM con caida a estimacion haversine."""
import math

import httpx

FACTOR = 1.3
SPEED_MS = 30 / 3.6  # 30 km/h
SOURCE_EST = "estimado_haversine"
SOURCE_OSRM = "osrm"
# Tope de espera por llamada a OSRM (lectura; la conexion se limita a 2 s). main.py descuenta
# lo que tarde del presupuesto de 30 s de la peticion, asi que OSRM nunca la alarga.
OSRM_TIMEOUT_S = 5.0


def haversine_m(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


class HaversineProvider:
    def matrix(self, points):
        n = len(points)
        dist = [[0] * n for _ in range(n)]
        dur = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    d = haversine_m(points[i], points[j]) * FACTOR
                    dist[i][j] = int(round(d))
                    dur[i][j] = int(round(d / SPEED_MS))
        return dist, dur, SOURCE_EST

    def route(self, a, b):
        d = haversine_m(a, b) * FACTOR
        return [list(a), list(b)], d / 1000.0, d / SPEED_MS / 60.0, SOURCE_EST


def _checked_matrix(raw, n, name):
    """Matriz n x n de numeros. Un null es un par inalcanzable: la respuesta se descarta
    entera (nunca se convierte en 0, que el solver leeria como un arco gratis)."""
    if not isinstance(raw, list) or len(raw) != n:
        raise ValueError(f"OSRM {name}: se esperaba una matriz de {n} filas")
    out = []
    for row in raw:
        if not isinstance(row, list) or len(row) != n:
            raise ValueError(f"OSRM {name}: se esperaban filas de {n} columnas")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in row):
            raise ValueError(f"OSRM {name}: par inalcanzable o valor no numerico")
        out.append([int(round(v)) for v in row])
    return out


class OsrmProvider:
    def __init__(self, base_url, timeout=None):
        self.base = base_url.rstrip("/")
        self.timeout = OSRM_TIMEOUT_S if timeout is None else timeout

    def _get(self, path, params):
        timeout = httpx.Timeout(self.timeout, connect=min(2.0, self.timeout))
        r = httpx.get(f"{self.base}{path}", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise ValueError(f"OSRM respondio {data.get('code')}")
        return data

    def matrix(self, points):
        coords = ";".join(f"{lon},{lat}" for lat, lon in points)
        data = self._get(f"/table/v1/driving/{coords}", {"annotations": "distance,duration"})
        n = len(points)
        dist = _checked_matrix(data.get("distances"), n, "distances")
        dur = _checked_matrix(data.get("durations"), n, "durations")
        return dist, dur, SOURCE_OSRM

    def route(self, a, b):
        coords = f"{a[1]},{a[0]};{b[1]},{b[0]}"
        data = self._get(f"/route/v1/driving/{coords}", {"overview": "full", "geometries": "geojson"})
        rt = data["routes"][0]
        geom = [[lat, lon] for lon, lat in rt["geometry"]["coordinates"]]
        return geom, rt["distance"] / 1000.0, rt["duration"] / 60.0, SOURCE_OSRM


class DistanceProvider:
    """Usa OSRM si hay URL; ante cualquier fallo, estimacion haversine."""

    def __init__(self, osrm_url=None):
        self.osrm = OsrmProvider(osrm_url) if osrm_url else None
        self.fallback = HaversineProvider()

    @property
    def label(self):
        """Proveedor configurado, para respuestas que no llegan a pedir distancias."""
        return SOURCE_OSRM if self.osrm else SOURCE_EST

    def matrix(self, points):
        if self.osrm:
            try:
                return self.osrm.matrix(points)
            except Exception:
                pass
        return self.fallback.matrix(points)

    def route(self, a, b):
        if self.osrm:
            try:
                return self.osrm.route(a, b)
            except Exception:
                pass
        return self.fallback.route(a, b)
