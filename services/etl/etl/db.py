"""Bases de datos del ETL: creacion (bootstrap), roles, version de esquema y candado de ejecucion."""
import os

import psycopg2
from psycopg2 import sql

from . import config

# Version del esquema de las dos bases. Se sube cuando cambia el DDL de forma incompatible.
SCHEMA_VERSION = 2
STAGING_FILES = ("staging_schema.sql",)
DWH_FILES = ("dwh_schema.sql", "dwh_views.sql")
# Clave del candado: una sola corrida del ETL a la vez (manual o programada).
CANDADO = 7402601


class EsquemaIncompatible(RuntimeError):
    """La base existe con un esquema de otra version del ETL."""


class Ocupado(RuntimeError):
    """Ya hay otra corrida del ETL en curso."""


# ---------------------------------------------------------------- roles y bases
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


def _restringir_conexion(cur, dbname, roles):
    """Quita CONNECT a PUBLIC (PostgreSQL lo concede por defecto) y lo concede solo a los roles dados que
    existan. El propietario de la base conserva su CONNECT. Idempotente."""
    cur.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
    for rol in roles:
        if rol and _role_exists(cur, rol):
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(dbname), sql.Identifier(rol)))


def _comprobar_version(cur, dbname):
    """Una base vacia es valida. Una con tablas debe tener la version de esquema actual."""
    cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
    if cur.fetchone()[0] == 0:
        return
    cur.execute("SELECT to_regclass('public.schema_version')")
    version = None
    if cur.fetchone()[0] is not None:
        cur.execute("SELECT max(version) FROM schema_version")
        version = cur.fetchone()[0]
    if version != SCHEMA_VERSION:
        raise EsquemaIncompatible(
            "La base %s tiene un esquema de otra version del ETL (encontrada: %s, esperada: %s). "
            "Ejecute `bootstrap --reset` para recrearla: sus datos son derivados y se vuelven a cargar con "
            "`run --mode full` y `simulate`." % (dbname, version if version is not None else "sin version",
                                                 SCHEMA_VERSION))


def _apply_ddl(admin_dsn, dbname, files, owner):
    """Aplica los archivos DDL (administrador) y deja las tablas y vistas de public a nombre del propietario."""
    conn = psycopg2.connect(admin_dsn, dbname=dbname)
    try:
        with conn, conn.cursor() as cur:
            _comprobar_version(cur, dbname)
            for nombre in files:
                with open(os.path.join(config.SQL_DIR, nombre), encoding="utf-8") as f:
                    cur.execute(f.read())
            cur.execute("INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING", (SCHEMA_VERSION,))
            if owner:
                cur.execute(
                    "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','v') AND pg_get_userbyid(c.relowner) <> %s",
                    (owner,))
                for relname, relkind in cur.fetchall():
                    kind = sql.SQL("VIEW" if relkind == "v" else "TABLE")
                    cur.execute(sql.SQL("ALTER {} {} OWNER TO {}").format(
                        kind, sql.Identifier(relname), sql.Identifier(owner)))
    finally:
        conn.close()


def _grant_readonly(admin_dsn, dbname, ro_role, owner):
    """Solo lectura sobre las tablas de public de la base del DWH (y las futuras que cree `owner`).
    No concede nada sobre la base de staging. Solo actua si el rol existe; devuelve True si lo concedio."""
    conn = psycopg2.connect(admin_dsn, dbname=dbname)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            if not _role_exists(cur, ro_role):
                return False
            r = sql.Identifier(ro_role)
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), r))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r))
            cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(r))
            cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}")
                        .format(sql.Identifier(owner), r))
        return True
    finally:
        conn.close()


def bootstrap(admin_dsn=None, staging_db=None, dwh_db=None, stg_user=None, dwh_user=None,
              stg_password=None, dwh_password=None, ro_password=None, ro_role=config.RO_ROLE, reset=False):
    """Crea las bases de staging y del DWH (si faltan), los roles propietarios y el rol de lectura, y aplica el DDL.

    - Un rol (propietario de staging, propietario del DWH, dwh_ro) se crea o actualiza SOLO si se da su clave.
    - Un propietario que ya existe pasa a ser dueno de su base y de sus tablas aunque no se de la clave.
    - dwh_ro recibe CONNECT, USAGE y SELECT sobre las tablas de public de la base del DWH (mas las futuras);
      sobre la base de staging no recibe nada.
    - CONNECT se quita a PUBLIC en ambas bases y se concede solo a sus roles de servicio: etl_stg en staging;
      dwh_etl y dwh_ro en el DWH.
    - reset=True borra antes las dos bases (los roles se conservan).
    - Si una base ya tiene tablas de otra version del esquema, lanza EsquemaIncompatible sin modificarla.
    Idempotente. Devuelve {'staging_owner': bool, 'dwh_owner': bool, 'ro': bool}: True si se creo/actualizo el rol."""
    admin_dsn = admin_dsn or config.admin_dsn()
    staging_db = staging_db or config.staging_db()
    dwh_db = dwh_db or config.dwh_db()
    stg_user = stg_user or config.staging_user()
    dwh_user = dwh_user or config.dwh_user()

    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    hecho = {"staging_owner": False, "dwh_owner": False, "ro": False}
    try:
        with conn.cursor() as cur:
            if reset:
                for base in (staging_db, dwh_db):
                    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(base)))
            for clave, rol, clave_rol in (("staging_owner", stg_user, stg_password),
                                          ("dwh_owner", dwh_user, dwh_password), ("ro", ro_role, ro_password)):
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
    finally:
        conn.close()

    _apply_ddl(admin_dsn, staging_db, STAGING_FILES, stg_owner)
    _apply_ddl(admin_dsn, dwh_db, DWH_FILES, dwh_owner)
    _grant_readonly(admin_dsn, dwh_db, ro_role, dwh_owner or admin_user)
    return hecho


# ---------------------------------------------------------------- conexiones de ejecucion
def conectar_staging():
    return psycopg2.connect(**config.staging_params())


def conectar_dwh():
    return psycopg2.connect(**config.dwh_params())


def tomar_candado(stg_conn):
    """Candado de sesion sobre la base de staging. Lanza Ocupado si otra corrida lo tiene."""
    with stg_conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (CANDADO,))
        tomado = cur.fetchone()[0]
    stg_conn.commit()
    if not tomado:
        raise Ocupado("Ya hay otra corrida del ETL en curso; esta se omite.")


def soltar_candado(stg_conn):
    with stg_conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (CANDADO,))
    stg_conn.commit()
