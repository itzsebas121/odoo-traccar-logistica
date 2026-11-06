import copy

from conftest import NOW, q1
from etl import load, simulado, staging, watermark

TABLAS = ("fact_recorridos", "fact_entregas", "fact_posicion_gps", "dim_vehiculo", "dim_conductor", "dim_cliente",
          "ruta_ventana")


def conteos(stg_con, dwh_con):
    c = {t: q1(dwh_con, "select count(*) from %s" % t) for t in TABLAS}
    c["rechazados"] = q1(stg_con, "select count(*) from rechazados")
    return c


def wm(conn, fuente):
    with conn.cursor() as cur:
        return watermark.get(cur, fuente)


def test_carga_incremental_idempotente(stg_con, dwh_con, odoo, traccar):
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    base = conteos(stg_con, dwh_con)
    w1 = wm(stg_con, "odoo:logistica.entrega")
    assert w1 is not None and wm(stg_con, "traccar") is not None

    load.run_etl(stg_con, dwh_con, "incremental", odoo, traccar, now=NOW)
    assert conteos(stg_con, dwh_con) == base
    assert wm(stg_con, "odoo:logistica.entrega") == w1

    # llega una entrega nueva: el incremental la toma y la marca de agua avanza
    nueva = copy.deepcopy(odoo.data["logistica.entrega"][0])
    nueva.update(id=4, name="ENT/0004", write_date="2026-11-05 15:00:00", state="preparado", route_id=False)
    odoo.data["logistica.entrega"].append(nueva)
    load.run_etl(stg_con, dwh_con, "incremental", odoo, traccar, now=NOW)
    assert q1(dwh_con, "select count(*) from fact_entregas") == base["fact_entregas"] + 1
    assert wm(stg_con, "odoo:logistica.entrega") > w1
    load.run_etl(stg_con, dwh_con, "incremental", odoo, traccar, now=NOW)
    assert q1(dwh_con, "select count(*) from fact_entregas") == base["fact_entregas"] + 1


def test_simulado_marcado(stg_con, dwh_con):
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote = staging.new_lote(scur, "simulate")
        n = simulado.generar(dcur, lote, dias=5, seed=1, now=NOW)
        n2 = simulado.generar(dcur, lote, dias=5, seed=1, now=NOW)  # idempotente
    stg_con.commit()
    dwh_con.commit()
    assert n > 0 and n2 == 0
    assert q1(dwh_con, "select count(*) from fact_recorridos where procedencia <> 'SIMULADO'") == 0
    assert q1(dwh_con, "select count(*) from dim_vehiculo where procedencia='SIMULADO'") == 3
    assert q1(dwh_con, "select count(*) from v_viajes_entrenamiento where procedencia='SIMULADO'") == n
