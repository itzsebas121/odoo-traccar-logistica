"""Asignacion de zona por centroide mas cercano. Las zonas vienen de Odoo (logistica.zona) via dim_zona."""
from .normalize import haversine_km
from .quality import coords_valid

# Codigo de la zona residual ("Otra / Periferica"): recibe todo lo que queda lejos de los demas centroides.
OTRA = "otra"
# Mas alla de este radio de todo centroide, el punto es de la zona residual.
OTRA_KM = 4.0
# Codigos del contrato C3 (los mismos de logistica.zona y del servicio ML).
CODIGOS_CONTRATO = ("centro", "ficoa", "huachi", "izamba", "atocha", "ingahurco", OTRA)


def zona_mas_cercana(zonas, lat, lon):
    """zonas: [{sk, codigo, lat, lon, activa}]. Devuelve el sk de la zona del punto, o None si no hay coordenadas
    validas. La zona residual no compite por distancia (su centroide es solo una referencia)."""
    if lat is None or lon is None or not coords_valid(lat, lon):
        return None
    mejor, mejor_d = None, None
    for z in zonas:
        if z["codigo"] == OTRA or z["lat"] is None or z["lon"] is None or not z.get("activa", True):
            continue
        d = haversine_km(float(lat), float(lon), z["lat"], z["lon"])
        if mejor_d is None or d < mejor_d:
            mejor, mejor_d = z, d
    if mejor is None or mejor_d > OTRA_KM:
        return next((z["sk"] for z in zonas if z["codigo"] == OTRA), None)
    return mejor["sk"]
