import copy

from conftest import NOW, q1
from etl import load, quality


def test_normaliza_velocidad_nudos():
    assert quality.knots_to_kmh(10) == 18.52


def test_rechaza_coordenadas_invalidas(dwh, odoo, traccar):
    traccar.data["positions"][0]["latitude"] = 91
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.rechazados where motivo='coordenadas_invalidas' and entidad='posicion'") == 1
    assert q1(dwh, "select count(*) from dwh.fact_posicion_gps") == 3


def test_rechaza_fechas_incoherentes(dwh, odoo, traccar):
    bad = copy.deepcopy(traccar.data["trips"][0])
    bad["startTime"], bad["endTime"] = "2026-11-05T16:00:00.000+00:00", "2026-11-05T15:30:00.000+00:00"
    traccar.data["trips"].append(bad)
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.rechazados where motivo='fechas_incoherentes'") == 1
    assert q1(dwh, "select count(*) from dwh.fact_recorridos") == 2


def test_rechaza_velocidad_anomala(dwh, odoo, traccar):
    traccar.data["positions"][1]["speed"] = 100  # nudos = 185.2 km/h
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.rechazados where motivo='velocidad_anomala'") == 1
    assert q1(dwh, "select count(*) from dwh.fact_posicion_gps where velocidad_kmh > 150") == 0


def test_duplicados_por_fuente(dwh, odoo, traccar):
    traccar.data["positions"].append(copy.deepcopy(traccar.data["positions"][0]))
    traccar.data["trips"].append(copy.deepcopy(traccar.data["trips"][0]))
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.fact_posicion_gps") == 4
    assert q1(dwh, "select count(*) from dwh.fact_recorridos") == 2


def test_rechaza_ruta_con_fechas_incoherentes(dwh, odoo, traccar):
    odoo.data["logistica.ruta"][0]["finished_at"] = "2026-11-05 13:00:00"  # antes de started_at (13:10)
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.rechazados where entidad='ruta' and motivo='fechas_incoherentes'") == 1
    assert q1(dwh, "select count(*) from dwh.ruta_ventana") == 1          # solo la ruta 2
    # sin ventana verificable de su ruta, la entrega 1 no se vincula a ningun recorrido
    assert q1(dwh, "select recorrido_sk from dwh.fact_entregas where entrega_id_odoo=1") is None
