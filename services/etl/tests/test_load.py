import copy
from datetime import datetime, timezone

import psycopg2.errors
import pytest

from conftest import FixtureOdoo, NOW, q1, qall
from etl import load


def test_vinculo_solo_con_coincidencia(stg_con, dwh_con, odoo, traccar):
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    rows = dict(qall(dwh_con, "select entrega_id_odoo, recorrido_sk from fact_entregas"))
    assert rows[1] is not None          # vehiculo 1, cierre 13:40 dentro del recorrido 13:30-14:00
    assert rows[2] is None              # cierre 13:50 dentro de la ventana, pero otro vehiculo
    assert rows[3] is None              # sin cierre
    # el vinculo apunta a un recorrido del mismo vehiculo
    assert q1(dwh_con, """select count(*) from fact_entregas f join fact_recorridos r on r.sk=f.recorrido_sk
                          where f.vehiculo_sk = r.vehiculo_sk""") == 1


def test_fechas_utc(stg_con, dwh_con, odoo, traccar):
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    plan, comp = qall(dwh_con, "select planificado_utc, completado_utc from fact_entregas where entrega_id_odoo=1")[0]
    assert comp == datetime(2026, 11, 5, 13, 40, tzinfo=timezone.utc)
    assert plan == datetime(2026, 11, 5, 13, 10, tzinfo=timezone.utc)
    assert comp.utcoffset().total_seconds() == plan.utcoffset().total_seconds()
    assert q1(dwh_con, "select sk from dim_tiempo where sk=2026110513") == 2026110513


def test_resultados_y_motivo(stg_con, dwh_con, odoo, traccar):
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    res = {r[0]: (r[1], r[2]) for r in qall(dwh_con, "select entrega_id_odoo, resultado, motivo from fact_entregas")}
    assert res == {1: ("entregado", None), 2: ("no_entregado", "absent"), 3: ("pendiente", None)}
    # unidades: 5200 m -> 5.2 km, 30 min
    assert float(q1(dwh_con, "select distancia_km from fact_recorridos where fuente_id like 'trip:10:%%'")) == 5.2
    assert q1(dwh_con, "select num_paradas from fact_recorridos where fuente_id like 'trip:10:%%'") == 1


def test_modelos_odoo_ausentes_se_omiten(stg_con, dwh_con, traccar):
    odoo = FixtureOdoo({"fleet.vehicle": FixtureOdoo().data["fleet.vehicle"]})  # aun no existe logistica.*
    counts = load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    assert "logistica.entrega" in counts["omitidos"]
    assert q1(dwh_con, "select count(*) from fact_entregas") == 0
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 2


def test_vista_entrenamiento(stg_con, dwh_con, odoo, traccar):
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    cols = [r[0] for r in qall(dwh_con, "select column_name from information_schema.columns "
                                        "where table_name='v_viajes_entrenamiento' order by ordinal_position")]
    assert cols == ["vehiculo_codigo", "fecha_hora", "zona_origen", "zona_destino", "procedencia"]
    assert qall(dwh_con, "select vehiculo_codigo, fecha_hora, zona_origen, zona_destino, procedencia "
                         "from v_viajes_entrenamiento where vehiculo_codigo='ABC-1234'") == [
        ("ABC-1234", "2026-11-05T13:30:00Z", "centro", "ficoa", "REAL")]


def _agregar_ruta_b(odoo):
    """Ruta A (id 1) termina a las 13:25; ruta B (id 3, mismo vehiculo) va de 13:28 a 14:05 con la entrega 4."""
    odoo.data["logistica.ruta"][0]["finished_at"] = "2026-11-05 13:25:00"
    ruta_b = copy.deepcopy(odoo.data["logistica.ruta"][0])
    ruta_b.update(id=3, name="RUTA/0003", state="cerrada", started_at="2026-11-05 13:28:00",
                  finished_at="2026-11-05 14:05:00", write_date="2026-11-05 14:05:00")
    odoo.data["logistica.ruta"].append(ruta_b)
    ent = copy.deepcopy(odoo.data["logistica.entrega"][0])
    ent.update(id=4, name="ENT/0004", route_id=[3, "RUTA/0003"], write_date="2026-11-05 13:51:00")
    odoo.data["logistica.entrega"].append(ent)
    par = copy.deepcopy(odoo.data["logistica.ruta.parada"][0])
    par.update(id=4, route_id=[3, "RUTA/0003"], entrega_id=[4, "ENT/0004"], completed_at="2026-11-05 13:50:00",
               write_date="2026-11-05 13:51:00")
    odoo.data["logistica.ruta.parada"].append(par)


def test_vinculo_exige_ventana_de_ruta(stg_con, dwh_con, odoo, traccar):
    """Entrega de la ruta A que cierra dentro de un recorrido de la ruta B (mismo vehiculo): NO se vincula."""
    _agregar_ruta_b(odoo)
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    rows = dict(qall(dwh_con, "select entrega_id_odoo, recorrido_sk from fact_entregas"))
    # recorrido 13:30-14:00 contiene el cierre de la entrega 1 (13:40), pero no se solapa con la ruta A (13:10-13:25)
    assert rows[1] is None
    # la entrega 4 pertenece a la ruta B (13:28-14:05), que si se solapa con el recorrido
    assert rows[4] is not None
    assert q1(dwh_con, "select vehiculo_sk from fact_recorridos where sk=%s", rows[4]) == \
        q1(dwh_con, "select vehiculo_sk from fact_entregas where entrega_id_odoo=4")


def test_vinculo_ruta_abierta_usa_now(stg_con, dwh_con, odoo, traccar):
    """Ruta sin finished_at: su ventana llega hasta 'ahora'. Con 'ahora' anterior al recorrido no hay vinculo."""
    antes = datetime(2026, 11, 5, 13, 20, tzinfo=timezone.utc)   # el recorrido empieza a las 13:30
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=antes)
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is None
    load.run_etl(stg_con, dwh_con, "incremental", odoo, traccar, now=NOW)
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is not None


# ---------------------------------------------------------------- rol de solo lectura
def test_dwh_ro_solo_lee_dwh(dbs_roles, odoo, traccar):
    e = dbs_roles
    stg_c, dwh_c = e.connect(e.stg_db, e.stg_user), e.connect(e.dwh_db, e.dwh_user)
    try:
        load.run_etl(stg_c, dwh_c, "full", odoo, traccar, now=NOW)
    finally:
        stg_c.close()
        dwh_c.close()
    ro = e.connect(e.dwh_db, e.ro_role, autocommit=True)
    try:
        with ro.cursor() as cur:
            cur.execute("select count(*) from fact_recorridos")
            assert cur.fetchone()[0] == 2
            cur.execute("select count(*) from v_viajes_entrenamiento")
            assert cur.fetchone()[0] == 2
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("insert into dim_zona (codigo, nombre) values ('x','x')")
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("delete from fact_entregas")
    finally:
        ro.close()
    # dwh_ro no abre sesion en la base de staging (detalle en test_roles.py)
    with pytest.raises(psycopg2.OperationalError, match="permission denied for database"):
        e.connect(e.stg_db, e.ro_role)


def test_dwh_ro_cubre_tablas_nuevas(dbs_roles):
    """Una tabla creada despues por el propietario del DWH queda legible por el rol de lectura."""
    e = dbs_roles
    owner = e.connect(e.dwh_db, e.dwh_user, autocommit=True)
    ro = e.connect(e.dwh_db, e.ro_role, autocommit=True)
    try:
        with owner.cursor() as cur:
            cur.execute("create table tabla_nueva (x int)")
        with ro.cursor() as cur:
            cur.execute("select count(*) from tabla_nueva")
            assert cur.fetchone()[0] == 0
    finally:
        owner.close()
        ro.close()
