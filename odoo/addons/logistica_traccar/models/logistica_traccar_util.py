# -*- coding: utf-8 -*-
"""Conversiones puras para datos GPS de Traccar. No acceden a la base de datos."""
import math

KNOT_TO_KMH = 1.852
METERS_PER_KM = 1000.0


def knots_to_kmh(knots):
    """Convierte nudos a km/h, redondeado a 2 decimales."""
    return round(knots * KNOT_TO_KMH, 2)


def valid_latlon(lat, lon):
    """Indica si la coordenada está en rango y no es la posición nula (0, 0)."""
    if lat is None or lon is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)


def meters_to_km(meters):
    """Convierte metros a kilómetros."""
    return meters / METERS_PER_KM


EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos coordenadas (círculo máximo)."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = f2 - f1
    dl = math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
