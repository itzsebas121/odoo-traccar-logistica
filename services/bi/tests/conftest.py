import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def _with_db(dsn, name):
    p = urlsplit(dsn)
    return urlunsplit((p.scheme, p.netloc, "/" + name, p.query, p.fragment))


def _ts(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=timezone.utc)


def _tsk(t):
    return int(t.strftime("%Y%m%d%H"))


@pytest.fixture
def dwh_env():
    """Base desechable bi_test_<hex> con el esquema del DWH (copia de services/etl/sql en tests/) y datos minimos;
    se elimina al terminar. Nunca toca logistica_dwh. Se omite si no hay DWH_ADMIN_DSN."""
    admin = os.environ.get("DWH_ADMIN_DSN")
    if not admin:
        pytest.skip("DWH_ADMIN_DSN no definido: pruebas de base de datos omitidas")
    admin = _with_db(admin, "postgres")
    name = "bi_test_" + uuid.uuid4().hex[:10]
    a = psycopg2.connect(admin)
    a.autocommit = True
    with a.cursor() as cur:
        cur.execute('CREATE DATABASE "%s"' % name)
    dsn = _with_db(admin, name)
    try:
        conn = psycopg2.connect(dsn)
        with conn, conn.cursor() as cur:
            for f in ("dwh_schema.sql", "dwh_views.sql"):
                with open(os.path.join(HERE, f), encoding="utf-8") as fh:
                    cur.execute(fh.read())
            cur.execute("INSERT INTO dim_vehiculo (vehiculo_id_odoo, placa, procedencia) VALUES "
                        "(1,'ABC-1234','REAL'),(2,'DEF-5678','SIMULADO')")
            cur.execute("INSERT INTO dim_conductor (conductor_id_odoo, nombre) VALUES (1,'Carlos')")
            cur.execute("SELECT codigo, sk FROM dim_zona")
            z = dict(cur.fetchall())
            cur.execute("INSERT INTO dim_cliente (cliente_id_odoo, nombre, zona_sk) VALUES "
                        "(1,'Cliente Uno',%s),(2,'Cliente Dos',%s)", (z["centro"], z["ficoa"]))
            # (vehiculo, dia, hora, origen, destino, km, min, paradas, procedencia)
            rec = [(1, 3, 8, "centro", "ficoa", 10, 30, 1, "REAL"),
                   (1, 4, 9, "ficoa", "huachi", 20, 45, 2, "REAL"),
                   (2, 3, 14, "centro", "izamba", 30, 60, 3, "SIMULADO"),
                   (2, 4, 15, "izamba", "centro", 40, 90, 0, "SIMULADO")]
            for i, (v, d, h, o, de, km, mn, p, pr) in enumerate(rec):
                t = _ts(d, h)
                cur.execute("INSERT INTO dim_tiempo VALUES (%s,%s,2026,11,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (_tsk(t), t.date(), d, t.weekday(), h))
                cur.execute("""INSERT INTO fact_recorridos (vehiculo_sk, conductor_sk, tiempo_inicio_sk,
                    zona_origen_sk, zona_destino_sk, inicio_utc, fin_utc, distancia_km, duracion_min, num_paradas,
                    fuente_id, procedencia) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (v, _tsk(t), z[o], z[de], t, t, km, mn, p, "t%d" % i, pr))
            # (cliente, vehiculo, dia, hora, resultado, minuto de cierre, procedencia); plan = hora:15
            ent = [(1, 1, 3, 8, "entregado", 0, "REAL"), (2, 1, 4, 9, "no_entregado", None, "REAL"),
                   (1, 2, 3, 14, "entregado", 30, "SIMULADO"), (2, 2, 4, 15, "pendiente", None, "SIMULADO")]
            for i, (c, v, d, h, res, minuto, pr) in enumerate(ent):
                t = _ts(d, h)
                comp = None if minuto is None else _ts(d, h, minuto)
                cur.execute("""INSERT INTO fact_entregas (cliente_sk, vehiculo_sk, tiempo_sk, zona_sk,
                    entrega_id_odoo, resultado, planificado_utc, completado_utc, procedencia)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (c, v, _tsk(t), z["centro"], i + 1, res, _ts(d, h, 15), comp, pr))
        conn.close()
        yield {"admin": admin, "dsn": dsn, "name": name}
    finally:
        with a.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name)
        a.close()


@pytest.fixture
def conn(dwh_env):
    c = psycopg2.connect(dwh_env["dsn"])
    try:
        yield c
    finally:
        c.close()
