"""Reglas de calidad (spec 10.2). Cada check_* recibe un dict ya normalizado y devuelve el motivo de rechazo o None.

Motivos: nulos_obligatorios, coordenadas_invalidas, fechas_incoherentes, velocidad_anomala, distancia_negativa,
importe_invalido, dispositivo_sin_vehiculo (este ultimo lo decide la carga, que conoce los vehiculos)."""
from datetime import timedelta

MAX_SPEED_KMH = 150.0
# Una lectura de Traccar con fecha posterior a "ahora" mas este margen viene de un reloj mal puesto en el equipo.
MARGEN_FUTURO = timedelta(minutes=5)

MOTIVOS = ("nulos_obligatorios", "coordenadas_invalidas", "fechas_incoherentes", "velocidad_anomala",
           "distancia_negativa", "importe_invalido", "dispositivo_sin_vehiculo")


def coords_valid(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)


def _ordenadas(*fechas):
    """True si las fechas presentes estan en orden no decreciente."""
    presentes = [f for f in fechas if f is not None]
    return all(a <= b for a, b in zip(presentes, presentes[1:]))


def _futura(fecha, ahora):
    return ahora is not None and fecha is not None and fecha > ahora + MARGEN_FUTURO


def check_position(p, ahora=None):
    """p: device, time, lat, lon, speed_kmh. Con `ahora`, una fecha futura es fechas_incoherentes."""
    if p.get("device") is None or p.get("time") is None or p.get("lat") is None or p.get("lon") is None:
        return "nulos_obligatorios"
    if _futura(p["time"], ahora):
        return "fechas_incoherentes"
    if not coords_valid(p["lat"], p["lon"]):
        return "coordenadas_invalidas"
    if p.get("speed_kmh") is not None and (p["speed_kmh"] < 0 or p["speed_kmh"] > MAX_SPEED_KMH):
        return "velocidad_anomala"
    return None


def check_trip(t, ahora=None):
    """t: device, inicio, fin, lat_ini/lon_ini, lat_fin/lon_fin, distancia_km, avg_kmh, max_kmh.
    Con `ahora`, un viaje que termina en el futuro es fechas_incoherentes."""
    if t.get("device") is None or t.get("inicio") is None or t.get("fin") is None:
        return "nulos_obligatorios"
    if t["fin"] < t["inicio"] or _futura(t["fin"], ahora):
        return "fechas_incoherentes"
    for a, b in (("lat_ini", "lon_ini"), ("lat_fin", "lon_fin")):
        if (t.get(a) is not None or t.get(b) is not None) and not coords_valid(t.get(a), t.get(b)):
            return "coordenadas_invalidas"
    for k in ("avg_kmh", "max_kmh"):
        if t.get(k) is not None and (t[k] < 0 or t[k] > MAX_SPEED_KMH):
            return "velocidad_anomala"
    if t.get("distancia_km") is not None and t["distancia_km"] < 0:
        return "distancia_negativa"
    return None


def check_ruta(r):
    """r: id, carga, inicio, fin, km_plan, min_plan."""
    if r.get("id") is None:
        return "nulos_obligatorios"
    if not _ordenadas(r.get("inicio"), r.get("fin")):
        return "fechas_incoherentes"
    for k in ("km_plan", "min_plan"):
        if r.get(k) is not None and r[k] < 0:
            return "distancia_negativa"
    return None


def check_parada(p):
    """p: id, ruta_id, llegada, cierre."""
    if p.get("id") is None or p.get("ruta_id") is None:
        return "nulos_obligatorios"
    if not _ordenadas(p.get("llegada"), p.get("cierre")):
        return "fechas_incoherentes"
    return None


def check_entrega(e):
    """e: id, lat, lon, inicio_ruta, completado."""
    if e.get("id") is None:
        return "nulos_obligatorios"
    if (e.get("lat") is not None or e.get("lon") is not None) and not coords_valid(e.get("lat"), e.get("lon")):
        return "coordenadas_invalidas"
    if not _ordenadas(e.get("inicio_ruta"), e.get("completado")):
        return "fechas_incoherentes"
    return None


def check_venta(v):
    """v: id, pedido_id, producto_id, cantidad, subtotal."""
    if v.get("id") is None or v.get("pedido_id") is None or v.get("producto_id") is None:
        return "nulos_obligatorios"
    if v.get("cantidad") is None or v["cantidad"] < 0:
        return "importe_invalido"
    if v.get("subtotal") is not None and v["subtotal"] < 0:
        return "importe_invalido"
    return None
