"""CLI: python -m etl bootstrap | simulate --dias N | run --mode full|incremental"""
import argparse
import os
import sys

import psycopg2
from psycopg2 import sql

from . import config, load, simulado, staging

STAGING_FILES = ("staging_schema.sql",)
DWH_FILES = ("dwh_schema.sql", "dwh_views.sql")


# ---------------------------------------------------------------- bootstrap
def _role_exists(cur, role):
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
    return cur.fetchone() is not None


def _ensure_role(cur, role, password):
    """Crea el rol (LOGIN, sin privilegios de servidor) o actualiza su clave."""
    verbo = "ALTER" if _role_exists(cur, role) else "CREATE"
    cur.execute(sql.SQL(verbo + " ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
        sql.Identifier(role), sql.Literal(password)))


def _ensure_database(cur, dbname, owner):
    """Crea la base si falta; si el propietario (rol existente) es otro, lo cambia."""
    cur.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (dbname,))
    fila = cur.fetchone()
    if fila is None:
        stmt = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
        if owner:
            stmt = sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(dbname), sql.Identifier(owner))
        cur.execute(stmt)
    elif owner and fila[0] != owner:
        cur.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(sql.Identifier(dbname), sql.Identifier(owner)))


def _apply_ddl(admin_dsn, dbname, files, owner):
    """Aplica los archivos DDL (administrador) y deja las tablas y vistas de public a nombre del propietario."""
    conn = psycopg2.connect(admin_dsn, dbname=dbname)
    with conn, conn.cursor() as cur:
        for nombre in files:
            with open(os.path.join(config.SQL_DIR, nombre), encoding="utf-8") as f:
                cur.execute(f.read())
        if owner:
            cur.execute("SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind IN ('r','v') AND pg_get_userbyid(c.relowner) <> %s",
                        (owner,))
            for relname, relkind in cur.fetchall():
                kind = sql.SQL("VIEW" if relkind == "v" else "TABLE")
                cur.execute(sql.SQL("ALTER {} {} OWNER TO {}").format(
                    kind, sql.Identifier(relname), sql.Identifier(owner)))
    conn.close()


def _grant_readonly(admin_dsn, dbname, ro_role, owner):
    """Solo lectura sobre las tablas de public de la base del DWH (y las futuras que cree `owner`).
    No concede nada sobre la base de staging. Solo actua si el rol existe; devuelve True si lo concedio."""
    conn = psycopg2.connect(admin_dsn, dbname=dbname)
    conn.autocommit = True
    with conn.cursor() as cur:
        if not _role_exists(cur, ro_role):
            conn.close()
            return False
        r = sql.Identifier(ro_role)
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), r))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r))
        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(r))
        cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}")
                    .format(sql.Identifier(owner), r))
    conn.close()
    return True


def _restringir_conexion(cur, dbname, roles):
    """Quita CONNECT a PUBLIC (PostgreSQL lo concede por defecto) y lo vuelve a conceder solo a los roles dados
    que existan. El propietario de la base conserva su CONNECT. Idempotente."""
    cur.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
    for rol in roles:
        if rol and _role_exists(cur, rol):
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(dbname), sql.Identifier(rol)))


def bootstrap(admin_dsn=None, staging_db=None, dwh_db=None, stg_user=None, dwh_user=None,
              stg_password=None, dwh_password=None, ro_password=None, ro_role=config.RO_ROLE):
    """Crea las bases de staging y del DWH (si faltan), los roles propietarios y el rol de lectura, y aplica el DDL.

    - Un rol (propietario de staging, propietario del DWH, dwh_ro) se crea o actualiza SOLO si se da su clave.
    - Un propietario que ya existe pasa a ser dueno de su base y de sus tablas aunque no se de la clave.
    - dwh_ro recibe CONNECT, USAGE y SELECT sobre las tablas de public de la base del DWH (mas las futuras);
      sobre la base de staging no recibe nada.
    - CONNECT se quita a PUBLIC en ambas bases y se concede solo a sus roles de servicio: etl_stg en staging;
      dwh_etl y dwh_ro en el DWH.
    Idempotente. Devuelve {'staging_owner': bool, 'dwh_owner': bool, 'ro': bool}: True si se creo/actualizo el rol."""
    admin_dsn = admin_dsn or config.admin_dsn()
    staging_db = staging_db or config.staging_db()
    dwh_db = dwh_db or config.dwh_db()
    stg_user = stg_user or config.staging_user()
    dwh_user = dwh_user or config.dwh_user()

    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    hecho = {"staging_owner": False, "dwh_owner": False, "ro": False}
    with conn.cursor() as cur:
        for clave, rol, clave_rol in (("staging_owner", stg_user, stg_password), ("dwh_owner", dwh_user, dwh_password),
                                      ("ro", ro_role, ro_password)):
            if clave_rol:
                _ensure_role(cur, rol, clave_rol)
                hecho[clave] = True
        stg_owner = stg_user if _role_exists(cur, stg_user) else None
        dwh_owner = dwh_user if _role_exists(cur, dwh_user) else None
        _ensure_database(cur, staging_db, stg_owner)
        _ensure_database(cur, dwh_db, dwh_owner)
        _restringir_conexion(cur, staging_db, (stg_user,))
        _restringir_conexion(cur, dwh_db, (dwh_user, ro_role))
        cur.execute("SELECT current_user")
        admin_user = cur.fetchone()[0]
    conn.close()

    _apply_ddl(admin_dsn, staging_db, STAGING_FILES, stg_owner)
    _apply_ddl(admin_dsn, dwh_db, DWH_FILES, dwh_owner)
    _grant_readonly(admin_dsn, dwh_db, ro_role, dwh_owner or admin_user)
    return hecho


# ---------------------------------------------------------------- run / simulate
def _sources():
    """Credenciales obligatorias primero (error claro y sin tocar la red); luego se conecta a cada fuente."""
    odoo_password = config.require("ODOO_PASSWORD")
    traccar_password = config.require("TRACCAR_PASSWORD")
    odoo = traccar = None
    try:
        from .odoo_extract import OdooSource
        odoo = OdooSource(config.env("ODOO_URL", "http://odoo:8069"), config.env("ODOO_DB", "logistica_dev"),
                          config.env("ODOO_USER", "admin"), odoo_password)
    except Exception as exc:
        print("AVISO: Odoo no disponible, se omite (%s)" % exc, file=sys.stderr)
    try:
        from .traccar_extract import TraccarSource
        traccar = TraccarSource(config.env("TRACCAR_URL", "http://traccar:8082"),
                                config.env("TRACCAR_USER", "admin@logistica.local"), traccar_password)
        traccar.s.get(traccar.url + "/api/devices", timeout=10).raise_for_status()
    except Exception as exc:
        print("AVISO: Traccar no disponible, se omite (%s)" % exc, file=sys.stderr)
        traccar = None
    return odoo, traccar


def _run(a):
    if a.cmd == "bootstrap":
        hecho = bootstrap(stg_password=config.env("ETL_STG_PASSWORD") or None,
                          dwh_password=config.env("DWH_ETL_PASSWORD") or None,
                          ro_password=config.env("DWH_DB_PASSWORD") or None)
        for clave, rol, var, efecto in (
                ("staging_owner", config.staging_user(), "ETL_STG_PASSWORD", "no se crea el rol; la base queda a nombre del administrador"),
                ("dwh_owner", config.dwh_user(), "DWH_ETL_PASSWORD", "no se crea el rol; la base queda a nombre del administrador"),
                ("ro", config.RO_ROLE, "DWH_DB_PASSWORD", "BI/ML no tendran usuario de lectura")):
            if not hecho[clave]:
                print("AVISO: %s no definida; no se crea el rol %s (%s)" % (var, rol, efecto), file=sys.stderr)
        print("Bases listas: %s, %s" % (config.staging_db(), config.dwh_db()))
        return 0
    # run / simulate: validar todas las variables obligatorias antes de tocar la red o las bases
    stg_params, dwh_params = config.staging_params(), config.dwh_params()
    if a.cmd == "simulate":
        stg_c, dwh_c = psycopg2.connect(**stg_params), psycopg2.connect(**dwh_params)
        try:
            with stg_c.cursor() as scur:
                lote = staging.new_lote(scur, "simulate")
            stg_c.commit()
            with dwh_c.cursor() as dcur:
                n = simulado.generar(dcur, lote, a.dias, a.seed)
            dwh_c.commit()
            with stg_c.cursor() as scur:
                staging.close_lote(scur, lote, "ok", {"recorridos_simulados": n})
            stg_c.commit()
        finally:
            stg_c.close()
            dwh_c.close()
        print("Recorridos SIMULADO insertados: %d" % n)
        return 0
    odoo, traccar = _sources()
    stg_c, dwh_c = psycopg2.connect(**stg_params), psycopg2.connect(**dwh_params)
    try:
        counts = load.run_etl(stg_c, dwh_c, a.mode, odoo, traccar, dias=a.dias)
    finally:
        stg_c.close()
        dwh_c.close()
    print("ETL %s: %s" % (a.mode, counts))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="etl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    s = sub.add_parser("simulate")
    s.add_argument("--dias", type=int, default=30)
    s.add_argument("--seed", type=int, default=42)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    r.add_argument("--dias", type=int, default=30, help="ventana Traccar inicial")
    a = ap.parse_args(argv)
    try:
        return _run(a)
    except config.ConfigError as exc:
        print("ERROR de configuracion: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
