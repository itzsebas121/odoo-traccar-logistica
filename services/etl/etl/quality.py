"""Reglas de calidad (spec 10.2): unidades, coordenadas, fechas, velocidad, duplicados, nulos."""
from datetime import datetime, timezone

KNOT_KMH = 1.852
MAX_SPEED_KMH = 150.0


def knots_to_kmh(knots):
    return round(float(knots) * KNOT_KMH, 2)


def meters_to_km(m):
    return round(float(m) / 1000.0, 3)


def parse_ts(value):
    """Devuelve datetime UTC aware o None. Un valor naive (formato Odoo, que guarda UTC) se marca como UTC;
    uno con offset (Traccar / ISO-8601) se convierte a UTC."""
    if value in (None, False, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def coords_valid(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)


def check_position(p):
    """p: dict normalizado (lat, lon, speed_kmh, time). Devuelve motivo de rechazo o None."""
    if p.get("time") is None or p.get("lat") is None or p.get("lon") is None:
        return "nulos_obligatorios"
    if not coords_valid(p["lat"], p["lon"]):
        return "coordenadas_invalidas"
    if p.get("speed_kmh") is not None and (p["speed_kmh"] < 0 or p["speed_kmh"] > MAX_SPEED_KMH):
        return "velocidad_anomala"
    return None


def check_trip(t):
    """t: dict con inicio, fin, lat_ini/lon_ini, lat_fin/lon_fin, distancia_km, avg_kmh, max_kmh."""
    if t.get("inicio") is None or t.get("fin") is None:
        return "nulos_obligatorios"
    if t["fin"] < t["inicio"]:
        return "fechas_incoherentes"
    for a, b in (("lat_ini", "lon_ini"), ("lat_fin", "lon_fin")):
        if t.get(a) is not None and not coords_valid(t[a], t[b]):
            return "coordenadas_invalidas"
    for k in ("avg_kmh", "max_kmh"):
        if t.get(k) is not None and t[k] > MAX_SPEED_KMH:
            return "velocidad_anomala"
    if t.get("distancia_km") is not None and t["distancia_km"] < 0:
        return "distancia_negativa"
    return None


def check_ruta(r):
    """r: dict con inicio, fin (ventana de la ruta). Una ruta sin inicio no tiene ventana verificable."""
    if r.get("inicio") and r.get("fin") and r["fin"] < r["inicio"]:
        return "fechas_incoherentes"
    return None


def check_entrega(e):
    if e.get("id") is None:
        return "nulos_obligatorios"
    if e.get("lat") is not None and not coords_valid(e["lat"], e["lon"]):
        return "coordenadas_invalidas"
    if e.get("inicio_ruta") and e.get("completado") and e["completado"] < e["inicio_ruta"]:
        return "fechas_incoherentes"
    return None


def dedupe(rows, key):
    """Una fila por clave (gana la ultima aparicion), conservando el orden de primera aparicion."""
    seen = {}
    for r in rows:
        seen[key(r)] = r
    return list(seen.values())
