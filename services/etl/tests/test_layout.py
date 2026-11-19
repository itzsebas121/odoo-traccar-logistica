"""Una base por componente, sin esquemas ni SQL entre bases (decision R26); roles y version de esquema."""
import os
import re

import psycopg2
import pytest

from conftest import correr, q1, qall
from etl import db

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TABLAS_STAGING = {"schema_version", "odoo_raw", "traccar_raw", "lote", "watermark", "rechazados"}
TABLAS_DWH = {"schema_version", "dim_vehiculo", "dim_conductor", "dim_tiempo", "dim_zona", "dim_cliente",
              "dim_producto", "fact_recorridos", "fact_posicion_gps", "fact_rutas", "fact_paradas", "fact_entregas",
              "fact_ventas", "etl_ejecucion", "ml_evaluacion_modelos", "ml_unidad_espacial", "ml_pronostico_demanda"}
VISTAS_ML = {"v_viajes_entrenamiento", "v_ruta_plan_vs_real", "v_ml_viajes", "v_ml_transiciones_paradas",
             "v_ml_ventas_geo", "v_ml_demanda_diaria_zona"}
VISTAS_BI = {"v_bi_dim_fecha", "v_bi_dim_producto", "v_bi_dim_cliente", "v_bi_dim_zona", "v_bi_dim_vehiculo",
             "v_bi_ventas_diarias", "v_bi_pedidos", "v_bi_ventas_mapa", "v_bi_top_productos_zona",
             "v_bi_comparativa_modelos", "v_bi_corridas_modelo", "v_bi_unidades_espaciales",
             "v_bi_demanda_real_vs_pronostico", "v_bi_recorridos", "v_bi_od_viajes", "v_bi_conductor_resumen",
             "v_bi_entregas", "v_bi_vinculo_gps", "v_bi_ruta_plan_vs_real", "v_bi_paradas", "v_bi_posiciones_ruta",
             "v_bi_etl_ejecuciones"}
VISTAS_DWH = VISTAS_ML | VISTAS_BI


def _tablas(conn):
    return {r[0] for r in qall(conn, "select table_name from information_schema.tables "
                                     "where table_schema='public' and table_type='BASE TABLE'")}


def _esquemas_propios(conn):
    return {r[0] for r in qall(conn, "select schema_name from information_schema.schemata "
                                     "where schema_name <> 'public' and schema_name <> 'information_schema' "
                                     "and schema_name not like 'pg\\_%'")}


def test_tablas_por_base(stg_con, dwh_con):
    assert _tablas(stg_con) == TABLAS_STAGING
    assert _tablas(dwh_con) == TABLAS_DWH
    assert _esquemas_propios(stg_con) == set() and _esquemas_propios(dwh_con) == set()
    assert {r[0] for r in qall(dwh_con, "select table_name from information_schema.views "
                                        "where table_schema='public'")} == VISTAS_DWH
    assert q1(stg_con, "select version from schema_version") == db.SCHEMA_VERSION
    assert q1(dwh_con, "select version from schema_version") == db.SCHEMA_VERSION


def test_bootstrap_agrega_columnas_nuevas_a_una_base_existente(dbs, dwh_con):
    """Las columnas de fact_recorridos que se anadieron despues de la v2 llegan a una base v2 ya creada con un
    `bootstrap` normal (sin --reset): el cambio es aditivo."""
    with dwh_con.cursor() as cur:
        cur.execute("drop view v_ml_viajes cascade")      # cascade: las vistas BI dependen de ella
        cur.execute("alter table fact_recorridos drop column ruta_id_odoo cascade, drop column lat_destino cascade")
    dwh_con.commit()
    dbs.bootstrap()
    assert q1(dwh_con, "select count(*) from information_schema.columns where table_name='fact_recorridos' "
                       "and column_name in ('ruta_id_odoo','lat_destino')") == 2


def test_dim_zona_nace_vacia(dwh_con):
    """Las zonas vienen de Odoo: el DDL no trae valores fijos."""
    assert q1(dwh_con, "select count(*) from dim_zona") == 0


def test_contrato_de_columnas_para_bi_y_ml(dwh_con):
    """Columnas que consumen el BI y el servicio ML: no pueden desaparecer ni cambiar de nombre."""
    def cols(tabla):
        return {r[0] for r in qall(dwh_con, "select column_name from information_schema.columns "
                                            "where table_name=%s", tabla)}
    assert cols("fact_recorridos") >= {"vehiculo_sk", "conductor_sk", "tiempo_inicio_sk", "zona_origen_sk",
                                       "zona_destino_sk", "inicio_utc", "fin_utc", "distancia_km", "duracion_min",
                                       "num_paradas", "fuente_id", "procedencia", "lote_id", "ruta_id_odoo",
                                       "lat_origen", "lon_origen", "lat_destino", "lon_destino"}
    assert cols("fact_entregas") >= {"cliente_sk", "vehiculo_sk", "conductor_sk", "tiempo_sk", "zona_sk",
                                     "entrega_id_odoo", "ruta_id_odoo", "recorrido_sk", "resultado", "motivo",
                                     "planificado_utc", "completado_utc", "procedencia"}
    assert cols("fact_posicion_gps") >= {"vehiculo_sk", "tiempo_sk", "gps_time_utc", "latitud", "longitud",
                                         "velocidad_kmh", "fuente_id"}
    assert [r[0] for r in qall(dwh_con, "select column_name from information_schema.columns "
                                        "where table_name='v_viajes_entrenamiento' order by ordinal_position")] == [
        "vehiculo_codigo", "fecha_hora", "zona_origen", "zona_destino", "procedencia"]


# ---------------------------------------------------------------- roles
def test_bootstrap_propietarios(dbs_roles):
    e = dbs_roles
    assert e.result == {"staging_owner": True, "dwh_owner": True, "ro": True, "ml": True}
    for base, rol, tablas in ((e.stg_db, e.stg_user, TABLAS_STAGING), (e.dwh_db, e.dwh_user, TABLAS_DWH)):
        conn = e.connect(base)
        try:
            assert q1(conn, "select pg_get_userbyid(datdba) from pg_database where datname=%s", base) == rol
            assert {r[0] for r in qall(conn, "select tableowner from pg_tables where schemaname='public'")} == {rol}
            assert {r[0] for r in qall(conn, "select viewowner from pg_views where schemaname='public'")} <= {rol}
            assert {r[0] for r in qall(conn, "select tablename from pg_tables where schemaname='public'")} == tablas
        finally:
            conn.close()


def test_pipeline_con_roles_propietarios(dbs_roles, odoo, traccar):
    """El ETL corre sin superusuario: etl_stg escribe en staging y dwh_etl en el DWH."""
    e = dbs_roles
    stg_c, dwh_c = e.connect(e.stg_db, e.stg_user), e.connect(e.dwh_db, e.dwh_user)
    try:
        correr(stg_c, dwh_c, "full", odoo, traccar)
        correr(stg_c, dwh_c, "incremental", odoo, traccar)
        assert q1(dwh_c, "select count(*) from fact_recorridos") == 2
        assert q1(stg_c, "select count(*) from lote where estado='ok'") == 2
    finally:
        stg_c.close()
        dwh_c.close()


def test_roles_no_cruzan_bases(dbs_roles):
    """Ni dwh_etl ni dwh_ro abren sesion en staging (psycopg2 reporta el rechazo de CONNECT como OperationalError)."""
    e = dbs_roles
    for rol in (e.dwh_user, e.ro_role):
        with pytest.raises(psycopg2.OperationalError, match="permission denied for database"):
            e.connect(e.stg_db, rol)
    with pytest.raises(psycopg2.OperationalError, match="permission denied for database"):
        e.connect(e.dwh_db, e.stg_user)


def test_dwh_ro_solo_lee(dbs_roles, odoo, traccar):
    e = dbs_roles
    stg_c, dwh_c = e.connect(e.stg_db, e.stg_user), e.connect(e.dwh_db, e.dwh_user)
    try:
        correr(stg_c, dwh_c, "full", odoo, traccar)
    finally:
        stg_c.close()
        dwh_c.close()
    ro = e.connect(e.dwh_db, e.ro_role, autocommit=True)
    try:
        with ro.cursor() as cur:
            for tabla in ("fact_recorridos", "v_viajes_entrenamiento", "v_ruta_plan_vs_real", "etl_ejecucion",
                          "fact_ventas"):
                cur.execute("select count(*) from %s" % tabla)
                assert cur.fetchone()[0] >= 1, tabla
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("insert into dim_zona (codigo, nombre) values ('x','x')")
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("delete from fact_entregas")
    finally:
        ro.close()


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


def test_bootstrap_idempotente_con_roles(dbs_roles):
    assert dbs_roles.bootstrap() == {"staging_owner": True, "dwh_owner": True, "ro": True, "ml": True}


def test_bootstrap_sin_password_no_crea_roles(dbs):
    e = dbs
    assert e.result == {"staging_owner": False, "dwh_owner": False, "ro": False, "ml": False}
    a = psycopg2.connect(e.admin)
    try:
        for rol in (e.stg_user, e.dwh_user, e.ro_role):
            assert q1(a, "select count(*) from pg_roles where rolname=%s", rol) == 0
    finally:
        a.close()


# ---------------------------------------------------------------- version de esquema y reset
def _dejar_esquema_viejo(e):
    """Simula el DWH de la version anterior del ETL: tablas sin schema_version."""
    conn = e.connect(e.dwh_db, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("drop table schema_version")
        cur.execute("insert into dim_zona (codigo, nombre) values ('vieja','Vieja')")
    conn.close()


def test_bootstrap_rechaza_esquema_de_otra_version(dbs):
    _dejar_esquema_viejo(dbs)
    with pytest.raises(db.EsquemaIncompatible, match="--reset"):
        dbs.bootstrap()
    conn = dbs.connect(dbs.dwh_db)
    try:
        assert q1(conn, "select count(*) from dim_zona where codigo='vieja'") == 1     # no la toco
    finally:
        conn.close()


def test_bootstrap_reset_recrea_las_bases(dbs):
    _dejar_esquema_viejo(dbs)
    dbs.bootstrap(reset=True)
    conn = dbs.connect(dbs.dwh_db)
    try:
        assert q1(conn, "select count(*) from dim_zona") == 0
        assert q1(conn, "select version from schema_version") == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_sin_esquemas_ni_sql_entre_bases():
    """Ningun archivo del servicio usa nombres calificados con esquema ni SQL entre bases."""
    esquemas = re.compile(r"\b(stg|etl_control|dwh)\.")
    entre_bases = ("db" + "link", "postgres" + "_fdw")
    revisados = 0
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for nombre in files:
            if not nombre.endswith((".py", ".sql")):
                continue
            ruta = os.path.join(base, nombre)
            with open(ruta, encoding="utf-8") as f:
                lineas = f.read().splitlines()
            revisados += 1
            for num, linea in enumerate(lineas, 1):
                if linea.lstrip().startswith(("#", "--")):  # comentarios que explican la regla
                    continue
                assert not esquemas.search(linea), "%s:%d usa un nombre con esquema" % (ruta, num)
                assert not any(p in linea.lower() for p in entre_bases), "%s:%d SQL entre bases" % (ruta, num)
                assert ("create " + "schema") not in linea.lower(), "%s:%d crea un esquema" % (ruta, num)
    assert revisados > 10
