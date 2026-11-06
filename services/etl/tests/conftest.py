import copy
import json
import os
import uuid
from datetime import datetime, timezone

import psycopg2
import psycopg2.extensions
import pytest

from etl import quality
from etl.__main__ import bootstrap

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class FixtureOdoo:
    """Imita OdooSource.fetch: filtra por write_date > since; modelos ausentes -> None."""

    def __init__(self, data=None):
        if data is None:
            data = {m: _load("odoo_%s.json" % m.replace(".", "_")) for m in (
                "res.partner", "fleet.vehicle", "logistica.ruta", "logistica.ruta.parada",
                "logistica.entrega", "logistica.entrega.evento")}
        self.data = data

    def fetch(self, model, since=None):
        if model not in self.data:
            return None
        rows = copy.deepcopy(self.data[model])
        if since is not None:
            rows = [r for r in rows if quality.parse_ts(r["write_date"]) > since]
        return rows


class FixtureTraccar:
    def __init__(self, data=None):
        self.data = data or {
            "devices": _load("traccar_devices.json"), "trips": _load("traccar_trips.json"),
            "stops": _load("traccar_stops.json"), "positions": _load("traccar_positions.json")}

    def fetch(self, desde, hasta):
        d = copy.deepcopy(self.data)
        d["trips"] = [t for t in d["trips"] if quality.parse_ts(t["startTime"]) > desde]
        d["stops"] = [t for t in d["stops"] if quality.parse_ts(t["startTime"]) > desde]
        d["positions"] = [p for p in d["positions"] if quality.parse_ts(p["fixTime"]) > desde]
        return d


@pytest.fixture
def odoo():
    return FixtureOdoo()


@pytest.fixture
def traccar():
    return FixtureTraccar()


def _admin_dsn():
    dsn = os.environ.get("DWH_ADMIN_DSN")
    if not dsn:
        pytest.skip("DWH_ADMIN_DSN no definido: pruebas de base de datos omitidas")
    return dsn


class Dbs:
    """Par de bases desechables (staging y DWH, nombres con _t_<hex>) y sus roles desechables.
    Nunca toca las bases ni los roles reales (etl_stg, dwh_etl, dwh_ro)."""

    def __init__(self, admin):
        tag = uuid.uuid4().hex[:8]
        self.admin = admin
        self.stg_db = "logistica_staging_t_" + tag
        self.dwh_db = "logistica_dwh_t_" + tag
        self.stg_user = "etl_stg_t_" + tag
        self.dwh_user = "dwh_etl_t_" + tag
        self.ro_role = "dwh_ro_t_" + tag
        self.passwords = {}
        self.result = None

    def bootstrap(self, roles=False):
        if roles:
            self.passwords = {self.stg_user: uuid.uuid4().hex, self.dwh_user: uuid.uuid4().hex,
                              self.ro_role: uuid.uuid4().hex}
        pw = self.passwords
        self.result = bootstrap(
            admin_dsn=self.admin, staging_db=self.stg_db, dwh_db=self.dwh_db,
            stg_user=self.stg_user, dwh_user=self.dwh_user, ro_role=self.ro_role,
            stg_password=pw.get(self.stg_user), dwh_password=pw.get(self.dwh_user),
            ro_password=pw.get(self.ro_role))
        return self.result

    def connect(self, dbname, role=None, autocommit=False):
        """Conexion como admin (role=None) o como uno de los roles desechables."""
        if role is None:
            conn = psycopg2.connect(self.admin, dbname=dbname)
        else:
            p = psycopg2.extensions.parse_dsn(self.admin)
            conn = psycopg2.connect(host=p["host"], port=p.get("port", "5432"), dbname=dbname, user=role,
                                    password=self.passwords[role])
        conn.autocommit = autocommit
        return conn

    def cleanup(self):
        a = psycopg2.connect(self.admin)
        a.autocommit = True
        with a.cursor() as cur:
            for db in (self.stg_db, self.dwh_db):
                cur.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % db)
            for role in (self.stg_user, self.dwh_user, self.ro_role):
                cur.execute('DROP ROLE IF EXISTS "%s"' % role)
        a.close()


@pytest.fixture
def dbs():
    """Bases desechables sin roles (propietario: el administrador)."""
    d = Dbs(_admin_dsn())
    try:
        d.bootstrap()
        yield d
    finally:
        d.cleanup()


@pytest.fixture
def dbs_roles():
    """Bases desechables con roles desechables propietarios (etl_stg, dwh_etl) y de lectura (dwh_ro)."""
    d = Dbs(_admin_dsn())
    try:
        d.bootstrap(roles=True)
        yield d
    finally:
        d.cleanup()


@pytest.fixture
def stg_con(dbs):
    conn = dbs.connect(dbs.stg_db)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def dwh_con(dbs):
    conn = dbs.connect(dbs.dwh_db)
    try:
        yield conn
    finally:
        conn.close()


def q1(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def qall(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()
