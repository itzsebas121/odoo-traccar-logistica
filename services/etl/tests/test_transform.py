"""Transformacion pura: normalizacion, calidad y zonas. No usa base de datos."""
from datetime import date, datetime, timedelta, timezone

import pytest

from etl import staging
from etl.transform import normalize as n
from etl.transform import quality as q
from etl.transform import zonas as z

UTC = timezone.utc


# ---------------------------------------------------------------- fechas y husos horarios
def test_fecha_sin_zona_es_utc():
    assert n.parse_ts("2026-11-05 13:40:00") == datetime(2026, 11, 5, 13, 40, tzinfo=UTC)


@pytest.mark.parametrize("texto", ["2026-11-05T08:40:00.000-05:00", "2026-11-05T13:40:00.000+00:00",
                                   "2026-11-05T13:40:00Z", "2026-11-05T19:10:00+05:30"])
def test_fecha_con_desfase_se_convierte_a_utc(texto):
    """Traccar puede responder con cualquier desfase: el instante es el mismo y se guarda en UTC."""
    dt = n.parse_ts(texto)
    assert dt == datetime(2026, 11, 5, 13, 40, tzinfo=UTC)
    assert dt.utcoffset() == timedelta(0)


@pytest.mark.parametrize("vacio", [None, False, "", "no es fecha", "2026-13-45"])
def test_fecha_vacia_o_invalida_es_none(vacio):
    assert n.parse_ts(vacio) is None


def test_fecha_local_de_odoo_a_utc():
    """El campo Date de la ruta es un dia local: su medianoche en Guayaquil (UTC-5) son las 05:00 UTC."""
    assert n.fecha_local_a_utc("2026-11-05", "America/Guayaquil") == datetime(2026, 11, 5, 5, 0, tzinfo=UTC)
    assert n.fecha_local_a_utc(False, "America/Guayaquil") is None
    assert n.fecha_local_a_utc("basura", "America/Guayaquil") is None


def test_dim_tiempo_tiene_hora_utc_y_local():
    """03:00 UTC del dia 5 es todavia la noche del dia 4 en Guayaquil."""
    f = n.fila_tiempo(datetime(2026, 11, 5, 3, 15, tzinfo=UTC), "America/Guayaquil")
    assert (f["sk"], f["fecha"], f["hora"]) == (2026110503, date(2026, 11, 5), 3)
    assert (f["fecha_local"], f["hora_local"], f["franja"]) == (date(2026, 11, 4), 22, "noche")
    assert f["dia_semana"] == 4 and f["dia_semana_local"] == 3 and f["fin_de_semana"] is False
    sabado = n.fila_tiempo(datetime(2026, 11, 7, 15, 0, tzinfo=UTC), "America/Guayaquil")
    assert sabado["fin_de_semana"] is True and sabado["franja"] == "manana"


def test_minutos():
    a = datetime(2026, 11, 5, 13, 38, tzinfo=UTC)
    assert n.minutos(a, a + timedelta(seconds=150)) == 2.5
    assert n.minutos(None, a) is None and n.minutos(a, None) is None


# ---------------------------------------------------------------- unidades y valores de Odoo
def test_unidades():
    assert n.knots_to_kmh(10) == 18.52
    assert n.meters_to_km(5200) == 5.2


@pytest.mark.parametrize("valor, esperado", [([7, "X"], 7), (7, 7), ("7", 7), (False, None), (None, None), ([], None),
                                             (0, None), (True, None), ("x", None)])
def test_many2one(valor, esperado):
    assert n.m2o_id(valor) == esperado


def test_nulos_de_odoo():
    """Odoo manda False en los campos vacios y 0 en los Float sin valor."""
    assert n.m2o_nombre([7, "Carlos"]) == "Carlos" and n.m2o_nombre(False) is None and n.m2o_nombre(7) is None
    assert n.texto(False) is None and n.texto("  ") is None and n.texto(" a ") == "a"
    assert n.numero(False) is None and n.numero(None) is None and n.numero(0) == 0.0 and n.numero("x") is None
    assert n.coordenada(0.0, 0.0) == (None, None)
    assert n.coordenada(False, -78.6) == (None, None)
    assert n.coordenada(-1.24, -78.62) == (-1.24, -78.62)


def test_dedupe_gana_la_ultima():
    filas = [{"k": 1, "v": "a"}, {"k": 2, "v": "b"}, {"k": 1, "v": "c"}]
    assert n.dedupe(filas, key=lambda r: r["k"]) == [{"k": 1, "v": "c"}, {"k": 2, "v": "b"}]


def test_huella_ignora_write_date():
    a = {"id": 1, "name": "x", "write_date": "2026-11-05 10:00:00"}
    assert staging.huella(a) == staging.huella(dict(a, write_date="2026-11-06 10:00:00"))
    assert staging.huella(a) != staging.huella(dict(a, name="y"))


# ---------------------------------------------------------------- calidad
T0 = datetime(2026, 11, 5, 13, 0, tzinfo=UTC)
POS = dict(device=10, time=T0, lat=-1.24, lon=-78.62, speed_kmh=30.0)
TRIP = dict(device=10, inicio=T0, fin=T0 + timedelta(minutes=30), lat_ini=-1.24, lon_ini=-78.62, lat_fin=-1.22,
            lon_fin=-78.63, distancia_km=5.2, avg_kmh=18.5, max_kmh=46.3)


@pytest.mark.parametrize("cambio, motivo", [
    ({}, None),
    ({"speed_kmh": None}, None),
    ({"time": None}, "nulos_obligatorios"),
    ({"lat": None}, "nulos_obligatorios"),
    ({"device": None}, "nulos_obligatorios"),
    ({"lat": 91}, "coordenadas_invalidas"),
    ({"lon": -181}, "coordenadas_invalidas"),
    ({"lat": 0, "lon": 0}, "coordenadas_invalidas"),
    ({"speed_kmh": 150.1}, "velocidad_anomala"),
    ({"speed_kmh": -1}, "velocidad_anomala"),
])
def test_calidad_posicion(cambio, motivo):
    assert q.check_position(dict(POS, **cambio)) == motivo


@pytest.mark.parametrize("cambio, motivo", [
    ({}, None),
    ({"lat_ini": None, "lon_ini": None, "distancia_km": None, "avg_kmh": None, "max_kmh": None}, None),
    ({"fin": None}, "nulos_obligatorios"),
    ({"fin": T0 - timedelta(minutes=1)}, "fechas_incoherentes"),
    ({"lat_fin": 95}, "coordenadas_invalidas"),
    ({"lat_ini": None}, "coordenadas_invalidas"),
    ({"max_kmh": 200}, "velocidad_anomala"),
    ({"distancia_km": -0.1}, "distancia_negativa"),
])
def test_calidad_recorrido(cambio, motivo):
    assert q.check_trip(dict(TRIP, **cambio)) == motivo


def test_calidad_ruta_parada_entrega_venta():
    despues = T0 + timedelta(minutes=5)
    assert q.check_ruta(dict(id=1, inicio=T0, fin=despues, km_plan=6.0, min_plan=45.0)) is None
    assert q.check_ruta(dict(id=1, inicio=None, fin=None, km_plan=None, min_plan=None)) is None
    assert q.check_ruta(dict(id=1, inicio=despues, fin=T0)) == "fechas_incoherentes"
    assert q.check_ruta(dict(id=1, km_plan=-1.0)) == "distancia_negativa"
    assert q.check_ruta(dict(id=None)) == "nulos_obligatorios"

    assert q.check_parada(dict(id=1, ruta_id=1, llegada=T0, cierre=despues)) is None
    assert q.check_parada(dict(id=1, ruta_id=1, llegada=None, cierre=None)) is None
    assert q.check_parada(dict(id=1, ruta_id=None)) == "nulos_obligatorios"
    assert q.check_parada(dict(id=1, ruta_id=1, llegada=despues, cierre=T0)) == "fechas_incoherentes"

    assert q.check_entrega(dict(id=1, lat=None, lon=None, inicio_ruta=None, completado=None)) is None
    assert q.check_entrega(dict(id=1, lat=-1.24, lon=None)) == "coordenadas_invalidas"
    assert q.check_entrega(dict(id=1, lat=-1.24, lon=-78.6, inicio_ruta=despues, completado=T0)) == "fechas_incoherentes"

    venta = dict(id=1, pedido_id=1, producto_id=1, cantidad=2.0, subtotal=20.0)
    assert q.check_venta(venta) is None
    assert q.check_venta(dict(venta, producto_id=None)) == "nulos_obligatorios"
    assert q.check_venta(dict(venta, cantidad=-1.0)) == "importe_invalido"
    assert q.check_venta(dict(venta, cantidad=None)) == "importe_invalido"
    assert q.check_venta(dict(venta, subtotal=-5.0)) == "importe_invalido"


# ---------------------------------------------------------------- zonas
ZONAS = [dict(sk=1, codigo="centro", lat=-1.2417, lon=-78.6197, activa=True),
         dict(sk=2, codigo="ficoa", lat=-1.2230, lon=-78.6330, activa=True),
         dict(sk=3, codigo="izamba", lat=-1.2050, lon=-78.5900, activa=False),
         dict(sk=9, codigo="otra", lat=-1.2800, lon=-78.5900, activa=True)]


def test_zona_mas_cercana():
    assert z.zona_mas_cercana(ZONAS, -1.2420, -78.6200) == 1
    assert z.zona_mas_cercana(ZONAS, -1.2235, -78.6325) == 2


def test_zona_lejana_o_inactiva_es_otra():
    assert z.zona_mas_cercana(ZONAS, -1.4520, -78.6700) == 9      # Mocha: a mas de 4 km de todo centroide
    assert z.zona_mas_cercana(ZONAS, -1.2050, -78.5900) == 9      # sobre el centroide de una zona inactiva
    assert z.zona_mas_cercana(ZONAS, -1.2800, -78.5900) == 9      # 'otra' no compite por distancia


def test_zona_sin_coordenadas_es_none():
    assert z.zona_mas_cercana(ZONAS, None, -78.6) is None
    assert z.zona_mas_cercana(ZONAS, 0, 0) is None
    assert z.zona_mas_cercana([], -1.24, -78.62) is None
