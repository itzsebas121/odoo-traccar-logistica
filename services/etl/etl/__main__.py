"""CLI: python -m etl bootstrap | simulate --dias N | run --mode full|incremental"""
import argparse
import os
import sys

import psycopg2
from psycopg2 import sql

from . import config, load, simulado, staging

# Archivos de esquema que se aplican en orden; los permisos del rol de lectura se dan en grant_readonly().
SCHEMA_FILES = ("01_schema.sql", "02_views.sql")


def grant_readonly(cur, role):
    """Permisos de solo lectura sobre el esquema dwh (y tablas futuras). No toca stg ni etl_control.
    Solo actua si el rol existe; devuelve True si lo concedio."""
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
    if not cur.fetchone():
        return False
    r = sql.Identifier(role)
    cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
        sql.Identifier(_current_db(cur)), r))
    cur.execute(sql.SQL("GRANT USAGE ON SCHEMA dwh TO {}").format(r))
    cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA dwh TO {}").format(r))
    cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA dwh GRANT SELECT ON TABLES TO {}").format(r))
    return True


def _current_db(cur):
    cur.execute("SELECT current_database()")
    return cur.fetchone()[0]


def bootstrap(dwh_dsn=None, admin_dsn=None, ro_password=None, ro_role=config.RO_ROLE):
    """Crea la base del DWH (si falta), aplica el esquema y, solo si hay contrasena (DWH_DB_PASSWORD),
    crea o actualiza el rol de solo lectura. Idempotente. Devuelve True si se creo/actualizo el rol."""
    dwh_dsn = dwh_dsn or config.dwh_dsn()
    admin_dsn = admin_dsn or config.admin_dsn()
    dbname = config.dbname_of(dwh_dsn)
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    rol_listo = False
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        if ro_password:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ro_role,))
            verbo = "ALTER" if cur.fetchone() else "CREATE"
            cur.execute(sql.SQL(verbo + " ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(ro_role), sql.Literal(ro_password)))
            rol_listo = True
    conn.close()
    conn = psycopg2.connect(dwh_dsn)
    with conn, conn.cursor() as cur:
        for nombre in SCHEMA_FILES:
            with open(os.path.join(config.SQL_DIR, nombre), encoding="utf-8") as f:
                cur.execute(f.read())
        grant_readonly(cur, ro_role)  # si el rol ya existe (p. ej. creado antes) se mantienen sus permisos
    conn.close()
    return rol_listo


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
        rol = bootstrap(ro_password=config.env("DWH_DB_PASSWORD") or None)
        if not rol:
            print("AVISO: DWH_DB_PASSWORD no definida; no se crea el rol %s (BI/ML no tendran usuario de lectura)"
                  % config.RO_ROLE, file=sys.stderr)
        print("DWH listo (%s)" % config.dbname_of(config.dwh_dsn()))
        return 0
    if a.cmd == "simulate":
        conn = psycopg2.connect(config.dwh_dsn())
        with conn, conn.cursor() as cur:
            lote = staging.new_lote(cur, "simulate")
            n = simulado.generar(cur, lote, a.dias, a.seed)
            staging.close_lote(cur, lote, "ok", {"recorridos_simulados": n})
        conn.close()
        print("Recorridos SIMULADO insertados: %d" % n)
        return 0
    odoo, traccar = _sources()  # valida las variables obligatorias antes de tocar el DWH
    conn = psycopg2.connect(config.dwh_dsn())
    counts = load.run_etl(conn, a.mode, odoo, traccar, dias=a.dias)
    conn.close()
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
