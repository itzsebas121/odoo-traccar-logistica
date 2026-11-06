import copy

from conftest import NOW, q1
from etl import load, simulado, staging, watermark

TABLAS = ("fact_recorridos", "fact_entregas", "fact_posicion_gps", "dim_vehiculo", "dim_conductor", "dim_cliente",
          "rechazados", "ruta_ventana")


def conteos(conn):
    return {t: q1(conn, "select count(*) from dwh.%s" % t) for t in TABLAS}


def wm(conn, fuente):
    with conn.cursor() as cur:
        return watermark.get(cur, fuente)


def test_carga_incremental_idempotente(dwh, odoo, traccar):
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    base = conteos(dwh)
    w1 = wm(dwh, "odoo:logistica.entrega")
    assert w1 is not None and wm(dwh, "traccar") is not None

    load.run_etl(dwh, "incremental", odoo, traccar, now=NOW)
    assert conteos(dwh) == base
    assert wm(dwh, "odoo:logistica.entrega") == w1

    # llega una entrega nueva: el incremental la toma y la marca de agua avanza
    nueva = copy.deepcopy(odoo.data["logistica.entrega"][0])
    nueva.update(id=4, name="ENT/0004", write_date="2026-11-05 15:00:00", state="preparado", route_id=False)
    odoo.data["logistica.entrega"].append(nueva)
    load.run_etl(dwh, "incremental", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.fact_entregas") == base["fact_entregas"] + 1
    assert wm(dwh, "odoo:logistica.entrega") > w1
    load.run_etl(dwh, "incremental", odoo, traccar, now=NOW)
    assert q1(dwh, "select count(*) from dwh.fact_entregas") == base["fact_entregas"] + 1


def test_simulado_marcado(dwh):
    with dwh.cursor() as cur:
        lote = staging.new_lote(cur, "simulate")
        n = simulado.generar(cur, lote, dias=5, seed=1, now=NOW)
        n2 = simulado.generar(cur, lote, dias=5, seed=1, now=NOW)  # idempotente
    dwh.commit()
    assert n > 0 and n2 == 0
    assert q1(dwh, "select count(*) from dwh.fact_recorridos where procedencia <> 'SIMULADO'") == 0
    assert q1(dwh, "select count(*) from dwh.dim_vehiculo where procedencia='SIMULADO'") == 3
    assert q1(dwh, "select count(*) from dwh.v_viajes_entrenamiento where procedencia='SIMULADO'") == n
