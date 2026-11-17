"""Normalizacion: unidades, fechas a UTC y valores de Odoo (XML-RPC). Funciones puras, sin base de datos."""
import math
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

KNOT_KMH = 1.852
RADIO_TIERRA_KM = 6371.0088


def knots_to_kmh(knots):
    return round(float(knots) * KNOT_KMH, 2)


def meters_to_km(m):
    return round(float(m) / 1000.0, 3)


def parse_ts(value):
    """Devuelve datetime UTC con zona o None. Un valor sin zona (formato Odoo, que guarda UTC) se marca como UTC;
    uno con desfase (Traccar / ISO-8601) se convierte a UTC. Un texto que no es fecha devuelve None."""
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


def fecha_local_a_utc(value, tz):
    """Fecha sin hora (campo Date de Odoo, en hora local) -> medianoche local expresada en UTC."""
    if value in (None, False, ""):
        return None
    try:
        dia = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime.combine(dia, time.min, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def m2o_id(v):
    """Many2one de XML-RPC ([id, nombre] | id | False) -> int | None. El entero 0 cuenta como vacio."""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v in (None, False, "") or isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n or None


def m2o_nombre(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else None


def texto(v):
    """Char/Selection de Odoo: False o cadena vacia -> None."""
    if v in (None, False):
        return None
    s = str(v).strip()
    return s or None


def numero(v):
    """Float/Integer de Odoo -> float | None. False (campo vacio) -> None; 0 es un valor valido."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def coordenada(lat, lon):
    """Par de coordenadas de Odoo. Los Float de Odoo valen 0 cuando estan vacios: (0, 0) o False -> (None, None)."""
    la, lo = numero(lat), numero(lon)
    if la is None or lo is None or (la == 0 and lo == 0):
        return None, None
    return la, lo


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return RADIO_TIERRA_KM * 2 * math.asin(math.sqrt(a))


def minutos(desde, hasta):
    """Minutos entre dos instantes; None si falta alguno."""
    if desde is None or hasta is None:
        return None
    return round((hasta - desde).total_seconds() / 60.0, 2)


def franja(hora):
    """Franja del dia para una hora local 0-23."""
    if hora < 6:
        return "madrugada"
    if hora < 12:
        return "manana"
    if hora < 18:
        return "tarde"
    return "noche"


def fila_tiempo(dt, tz):
    """Fila de dim_tiempo para el instante `dt` (con zona): clave YYYYMMDDHH en UTC y columnas en hora local."""
    u = dt.astimezone(timezone.utc)
    loc = u.astimezone(ZoneInfo(tz))
    return dict(sk=int(u.strftime("%Y%m%d%H")), fecha=u.date(), anio=u.year, mes=u.month, dia=u.day,
                dia_semana=u.isoweekday(), hora=u.hour, fecha_local=loc.date(), hora_local=loc.hour,
                dia_semana_local=loc.isoweekday(), franja=franja(loc.hour), fin_de_semana=loc.isoweekday() >= 6)


def dedupe(rows, key):
    """Una fila por clave (gana la ultima aparicion), conservando el orden de primera aparicion."""
    seen = {}
    for r in rows:
        seen[key(r)] = r
    return list(seen.values())
