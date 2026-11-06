"""Una base por componente, sin esquemas ni SQL entre bases (decision R26)."""
import os
import re

import psycopg2
import psycopg2.errors
import pytest

from conftest import NOW, q1, qall
from etl import load

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TABLAS_STAGING = {"odoo_raw", "traccar_raw", "lote", "watermark", "rechazados"}
TABLAS_DWH = {"dim_vehiculo", "dim_conductor", "dim_tiempo", "dim_zona", "dim_cliente", "fact_recorridos",
              "fact_entregas", "fact_posicion_gps", "ruta_ventana"}


def _tablas(conn):
    return {r[0] for r in qall(conn, "select table_name from information_schema.tables "
                                     "where table_schema='public' and table_type='BASE TABLE'")}


def _esquemas_propios(conn):
    return {r[0] for r in qall(conn, "select schema_name from information_schema.schemata "
                                     "where schema_name <> 'public' and schema_name <> 'information_schema' "
                                     "and schema_name not like 'pg\\_%%'")}


def test_tablas_por_base(stg_con, dwh_con):
    assert _tablas(stg_con) == TABLAS_STAGING
    assert _tablas(dwh_con) == TABLAS_DWH
    assert _esquemas_propios(stg_con) == set() and _esquemas_propios(dwh_con) == set()
    assert [r[0] for r in qall(dwh_con, "select table_name from information_schema.views "
                                        "where table_schema='public'")] == ["v_viajes_entrenamiento"]


def test_columnas_ruta_ventana(dwh_con):
    cols = [r[0] for r in qall(dwh_con, "select column_name from information_schema.columns "
                                        "where table_name='ruta_ventana' order by ordinal_position")]
    assert cols == ["ruta_id_odoo", "vehiculo_sk", "inicio_utc", "fin_utc", "lote_id"]


def test_crudo_en_staging_y_hechos_en_dwh(stg_con, dwh_con, odoo, traccar):
    load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    # staging: crudo con lote, bitacora de lotes y marcas de agua
    assert q1(stg_con, "select count(*) from odoo_raw where modelo='logistica.entrega'") == 3
    assert q1(stg_con, "select count(*) from traccar_raw where endpoint='reports/trips'") == 2
    assert q1(stg_con, "select count(*) from traccar_raw where endpoint='reports/route'") == 4
    assert q1(stg_con, "select count(*) from lote where estado='ok'") == 1
    assert q1(stg_con, "select count(*) from watermark") >= 2
    # DWH: hechos, sin tablas de staging
    assert q1(dwh_con, "select count(*) from fact_entregas") == 3
    assert q1(dwh_con, "select count(*) from fact_posicion_gps") == 4
    assert TABLAS_STAGING.isdisjoint(_tablas(dwh_con))


def test_error_de_carga_marca_el_lote_y_no_avanza_marcas(stg_con, dwh_con, odoo, traccar):
    dwh_con.cursor().execute("drop table fact_posicion_gps")      # fuerza un fallo en la carga del DWH
    dwh_con.commit()
    try:
        load.run_etl(stg_con, dwh_con, "full", odoo, traccar, now=NOW)
    except psycopg2.Error:
        pass
    else:
        raise AssertionError("debia fallar")
    assert q1(stg_con, "select estado from lote") == "error"
    assert q1(stg_con, "select count(*) from watermark") == 0


def test_bootstrap_propietarios(dbs_roles):
    e = dbs_roles
    assert e.result == {"staging_owner": True, "dwh_owner": True, "ro": True}
    for db, rol, tablas in ((e.stg_db, e.stg_user, TABLAS_STAGING), (e.dwh_db, e.dwh_user, TABLAS_DWH)):
        conn = e.connect(db)
        try:
            assert q1(conn, "select pg_get_userbyid(datdba) from pg_database where datname=%s", db) == rol
            duenos = {r[0] for r in qall(conn, "select tableowner from pg_tables where schemaname='public'")}
            assert duenos == {rol}
            assert {r[0] for r in qall(conn, "select tablename from pg_tables where schemaname='public'")} == tablas
        finally:
            conn.close()


def test_pipeline_con_roles_propietarios(dbs_roles, odoo, traccar):
    """El ETL corre sin superusuario: etl_stg escribe en staging y dwh_etl en el DWH."""
    e = dbs_roles
    stg_c, dwh_c = e.connect(e.stg_db, e.stg_user), e.connect(e.dwh_db, e.dwh_user)
    try:
        load.run_etl(stg_c, dwh_c, "full", odoo, traccar, now=NOW)
        load.run_etl(stg_c, dwh_c, "incremental", odoo, traccar, now=NOW)
        assert q1(dwh_c, "select count(*) from fact_recorridos") == 2
        assert q1(stg_c, "select count(*) from lote where estado='ok'") == 2
    finally:
        stg_c.close()
        dwh_c.close()


def test_roles_no_cruzan_bases(dbs_roles):
    """dwh_etl no abre sesion en staging (la base de staging no le concede CONNECT)."""
    e = dbs_roles
    with pytest.raises(psycopg2.OperationalError, match="permission denied for database"):
        e.connect(e.stg_db, e.dwh_user)


def test_bootstrap_idempotente_con_roles(dbs_roles):
    e = dbs_roles
    assert e.bootstrap() == {"staging_owner": True, "dwh_owner": True, "ro": True}


def test_bootstrap_sin_password_no_crea_roles(dbs):
    e = dbs
    assert e.result == {"staging_owner": False, "dwh_owner": False, "ro": False}
    a = psycopg2.connect(e.admin)
    try:
        for rol in (e.stg_user, e.dwh_user, e.ro_role):
            assert q1(a, "select count(*) from pg_roles where rolname=%s", rol) == 0
    finally:
        a.close()


def test_sin_esquemas_ni_sql_entre_bases():
    """Ningun archivo del servicio usa nombres calificados con esquema ni SQL entre bases."""
    esquemas = re.compile(r"\b(stg|etl_control|dwh)\.")
    entre_bases = ("db" + "link", "postgres" + "_fdw")
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for nombre in files:
            ruta = os.path.join(base, nombre)
            try:
                with open(ruta, encoding="utf-8") as f:
                    lineas = f.read().splitlines()
            except UnicodeDecodeError:
                continue
            for n, linea in enumerate(lineas, 1):
                if linea.lstrip().startswith(("#", "--")):  # comentarios que explican la regla
                    continue
                assert not esquemas.search(linea), "%s:%d usa un nombre con esquema" % (ruta, n)
                assert not any(p in linea.lower() for p in entre_bases), "%s:%d SQL entre bases" % (ruta, n)
                assert ("create " + "schema") not in linea.lower(), "%s:%d crea un esquema" % (ruta, n)
