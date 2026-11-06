import copy
import json
import os
import uuid
from datetime import datetime, timezone

import psycopg2
import pytest

from etl import config, quality
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
    dsn = os.environ.get("DWH_ADMIN_DSN") or os.environ.get("DWH_DSN")
    if not dsn:
        pytest.skip("DWH_ADMIN_DSN / DWH_DSN no definidos: pruebas de base de datos omitidas")
    return config.with_dbname(dsn, "postgres")


@pytest.fixture
def dwh_env():
    """Base PostgreSQL desechable (etl_test_<hex>) con el esquema aplicado; se elimina al terminar.
    Devuelve los DSN (admin y de la base de prueba) para pruebas que necesitan reconectar o crear roles."""
    admin = _admin_dsn()
    name = "etl_test_" + uuid.uuid4().hex[:10]
    dsn = config.with_dbname(admin, name)
    bootstrap(dwh_dsn=dsn, admin_dsn=admin)
    try:
        yield {"admin": admin, "dsn": dsn, "name": name}
    finally:
        a = psycopg2.connect(admin)
        a.autocommit = True
        with a.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name)
        a.close()


@pytest.fixture
def dwh(dwh_env):
    conn = psycopg2.connect(dwh_env["dsn"])
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def ro_role(dwh_env):
    """Nombre de un rol de solo lectura desechable (nunca el dwh_ro real); se elimina al terminar."""
    role = "dwh_ro_t_" + uuid.uuid4().hex[:8]
    try:
        yield role
    finally:
        a = psycopg2.connect(dwh_env["admin"])
        a.autocommit = True
        with a.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % dwh_env["name"])
            cur.execute('DROP ROLE IF EXISTS "%s"' % role)
        a.close()


def q1(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def qall(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()
