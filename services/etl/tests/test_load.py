import copy
import secrets
from datetime import datetime, timezone

import psycopg2
import psycopg2.errors
import psycopg2.extensions
import pytest

from conftest import FixtureOdoo, NOW, q1, qall
from etl import load
from etl.__main__ import bootstrap


def test_vinculo_solo_con_coincidencia(dwh, odoo, traccar):
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    rows = dict(qall(dwh, "select entrega_id_odoo, recorrido_sk from dwh.fact_entregas"))
    assert rows[1] is not None          # vehiculo 1, cierre 13:40 dentro del recorrido 13:30-14:00
    assert rows[2] is None              # cierre 13:50 dentro de la ventana, pero otro vehiculo
    assert rows[3] is None              # sin cierre
    # el vinculo apunta a un recorrido del mismo vehiculo
    assert q1(dwh, """select count(*) from dwh.fact_entregas f join dwh.fact_recorridos r on r.sk=f.recorrido_sk
                      where f.vehiculo_sk = r.vehiculo_sk""") == 1


def test_fechas_utc(dwh, odoo, traccar):
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    plan, comp = qall(dwh, "select planificado_utc, completado_utc from dwh.fact_entregas where entrega_id_odoo=1")[0]
    assert comp == datetime(2026, 11, 5, 13, 40, tzinfo=timezone.utc)
    assert plan == datetime(2026, 11, 5, 13, 10, tzinfo=timezone.utc)
    assert comp.utcoffset().total_seconds() == plan.utcoffset().total_seconds()
    assert q1(dwh, "select sk from dwh.dim_tiempo where sk=2026110513") == 2026110513


def test_resultados_y_motivo(dwh, odoo, traccar):
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    res = {r[0]: (r[1], r[2]) for r in qall(dwh, "select entrega_id_odoo, resultado, motivo from dwh.fact_entregas")}
    assert res == {1: ("entregado", None), 2: ("no_entregado", "absent"), 3: ("pendiente", None)}
    # unidades: 5200 m -> 5.2 km, 30 min
    assert float(q1(dwh, "select distancia_km from dwh.fact_recorridos where fuente_id like 'trip:10:%%'")) == 5.2
    assert q1(dwh, "select num_paradas from dwh.fact_recorridos where fuente_id like 'trip:10:%%'") == 1


def test_modelos_odoo_ausentes_se_omiten(dwh, traccar):
    odoo = FixtureOdoo({"fleet.vehicle": FixtureOdoo().data["fleet.vehicle"]})  # aun no existe logistica.*
    counts = load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    assert "logistica.entrega" in counts["omitidos"]
    assert q1(dwh, "select count(*) from dwh.fact_entregas") == 0
    assert q1(dwh, "select count(*) from dwh.fact_recorridos") == 2


def test_vista_entrenamiento(dwh, odoo, traccar):
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    cols = [r[0] for r in qall(dwh, "select column_name from information_schema.columns "
                                    "where table_name='v_viajes_entrenamiento' order by ordinal_position")]
    assert cols == ["vehiculo_codigo", "fecha_hora", "zona_origen", "zona_destino", "procedencia"]
    assert qall(dwh, "select vehiculo_codigo, fecha_hora, zona_origen, zona_destino, procedencia "
                     "from dwh.v_viajes_entrenamiento where vehiculo_codigo='ABC-1234'") == [
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


def test_vinculo_exige_ventana_de_ruta(dwh, odoo, traccar):
    """Entrega de la ruta A que cierra dentro de un recorrido de la ruta B (mismo vehiculo): NO se vincula."""
    _agregar_ruta_b(odoo)
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    rows = dict(qall(dwh, "select entrega_id_odoo, recorrido_sk from dwh.fact_entregas"))
    # recorrido 13:30-14:00 contiene el cierre de la entrega 1 (13:40), pero no se solapa con la ruta A (13:10-13:25)
    assert rows[1] is None
    # la entrega 4 pertenece a la ruta B (13:28-14:05), que si se solapa con el recorrido
    assert rows[4] is not None
    assert q1(dwh, "select vehiculo_sk from dwh.fact_recorridos where sk=%s", rows[4]) ==         q1(dwh, "select vehiculo_sk from dwh.fact_entregas where entrega_id_odoo=4")


def test_vinculo_ruta_abierta_usa_now(dwh, odoo, traccar):
    """Ruta sin finished_at: su ventana llega hasta 'ahora'. Con 'ahora' anterior al recorrido no hay vinculo."""
    antes = datetime(2026, 11, 5, 13, 20, tzinfo=timezone.utc)   # el recorrido empieza a las 13:30
    load.run_etl(dwh, "full", odoo, traccar, now=antes)
    assert q1(dwh, "select recorrido_sk from dwh.fact_entregas where entrega_id_odoo=1") is None
    load.run_etl(dwh, "incremental", odoo, traccar, now=NOW)
    assert q1(dwh, "select recorrido_sk from dwh.fact_entregas where entrega_id_odoo=1") is not None


# ---------------------------------------------------------------- rol de solo lectura
def _conectar_como(dwh_env, role, password):
    p = psycopg2.extensions.parse_dsn(dwh_env["dsn"])
    conn = psycopg2.connect(host=p["host"], port=p.get("port", 5432), dbname=dwh_env["name"], user=role,
                            password=password)
    conn.autocommit = True
    return conn


def test_dwh_ro_solo_lee_dwh(dwh, dwh_env, ro_role, odoo, traccar):
    load.run_etl(dwh, "full", odoo, traccar, now=NOW)
    password = secrets.token_hex(8)
    assert bootstrap(dwh_dsn=dwh_env["dsn"], admin_dsn=dwh_env["admin"], ro_password=password,
                     ro_role=ro_role) is True
    ro = _conectar_como(dwh_env, ro_role, password)
    try:
        with ro.cursor() as cur:
            cur.execute("select count(*) from dwh.fact_recorridos")
            assert cur.fetchone()[0] == 2
            cur.execute("select count(*) from dwh.v_viajes_entrenamiento")
            assert cur.fetchone()[0] == 2
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("insert into dwh.rechazados (entidad, fuente_id, motivo) values ('x','x','x')")
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("delete from dwh.fact_entregas")
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("select count(*) from stg.odoo_raw")
    finally:
        ro.close()


def test_dwh_ro_cubre_tablas_nuevas(dwh, dwh_env, ro_role):
    """Reaplicar bootstrap (idempotente) mantiene los permisos; una tabla nueva en dwh queda legible."""
    password = secrets.token_hex(8)
    bootstrap(dwh_dsn=dwh_env["dsn"], admin_dsn=dwh_env["admin"], ro_password=password, ro_role=ro_role)
    with dwh.cursor() as cur:
        cur.execute("create table dwh.tabla_nueva (x int)")
    dwh.commit()
    ro = _conectar_como(dwh_env, ro_role, password)
    try:
        with ro.cursor() as cur:
            cur.execute("select count(*) from dwh.tabla_nueva")
            assert cur.fetchone()[0] == 0
    finally:
        ro.close()


def test_bootstrap_sin_password_no_crea_rol(dwh_env, ro_role):
    assert bootstrap(dwh_dsn=dwh_env["dsn"], admin_dsn=dwh_env["admin"], ro_password=None,
                     ro_role=ro_role) is False
    a = psycopg2.connect(dwh_env["admin"])
    try:
        with a.cursor() as cur:
            cur.execute("select count(*) from pg_roles where rolname=%s", (ro_role,))
            assert cur.fetchone()[0] == 0
    finally:
        a.close()
