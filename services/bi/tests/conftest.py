import os
import uuid
from datetime import date, datetime, timedelta, timezone
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


def _tiempo(cur, t):
    """Fila de dim_tiempo con la vista local (America/Guayaquil = UTC-5), como la carga el ETL."""
    loc = t - timedelta(hours=5)
    cur.execute("INSERT INTO dim_tiempo (sk, fecha, anio, mes, dia, dia_semana, hora, fecha_local, hora_local, "
                "dia_semana_local, fin_de_semana) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (_tsk(t), t.date(), t.year, t.month, t.day, t.isoweekday(), t.hour, loc.date(), loc.hour,
                 loc.isoweekday(), loc.isoweekday() >= 6))
    return _tsk(t)


def _poblar(cur):
    cur.execute("INSERT INTO dim_zona (codigo, nombre, latitud, longitud, zona_id_odoo) VALUES "
                "('centro','Centro',-1.2417,-78.6197,1),('ficoa','Ficoa',-1.2230,-78.6330,2),"
                "('huachi','Huachi',-1.2750,-78.6300,3),('izamba','Izamba',-1.2050,-78.5900,4)")
    cur.execute("SELECT codigo, sk FROM dim_zona")
    z = dict(cur.fetchall())
    cur.execute("INSERT INTO dim_vehiculo (vehiculo_id_odoo, placa, procedencia) VALUES "
                "(1,'ABC-1234','REAL'),(2,'DEF-5678','SIMULADO')")
    cur.execute("INSERT INTO dim_conductor (conductor_id_odoo, nombre) VALUES (1,'Carlos')")
    cur.execute("INSERT INTO dim_cliente (cliente_id_odoo, nombre, zona_sk) VALUES "
                "(1,'Cliente Uno',%s),(2,'Cliente Dos',%s)", (z["centro"], z["ficoa"]))
    cur.execute("INSERT INTO dim_producto (producto_id_odoo, nombre, referencia, categoria) VALUES "
                "(1,'Producto Uno','P1','All / Alimentos / Granos'),(2,'Producto Dos','P2','All / Hogar / Limpieza')")

    # (vehiculo, dia, hora, origen, destino, km, min, paradas, procedencia)
    rec = [(1, 3, 8, "centro", "ficoa", 10, 30, 1, "REAL"),
           (1, 4, 9, "ficoa", "huachi", 20, 45, 2, "REAL"),
           (2, 3, 14, "centro", "izamba", 30, 60, 3, "SIMULADO"),
           (2, 4, 15, "izamba", "centro", 40, 90, 0, "SIMULADO")]
    for i, (v, d, h, o, de, km, mn, p, pr) in enumerate(rec):
        t = _ts(d, h)
        cur.execute("""INSERT INTO fact_recorridos (vehiculo_sk, conductor_sk, tiempo_inicio_sk,
            zona_origen_sk, zona_destino_sk, inicio_utc, fin_utc, distancia_km, duracion_min, num_paradas,
            fuente_id, procedencia) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (v, _tiempo(cur, t), z[o], z[de], t, t, km, mn, p, "t%d" % i, pr))

    # (cliente, vehiculo, dia, hora, resultado, minuto de cierre, a_tiempo, motivo, procedencia); limite = hora:15
    ent = [(1, 1, 3, 8, "entregado", 0, True, None, "REAL"),
           (2, 1, 4, 9, "no_entregado", 20, None, "absent", "REAL"),
           (1, 2, 3, 14, "entregado", 30, False, None, "SIMULADO"),
           (2, 2, 4, 15, "pendiente", None, None, None, "SIMULADO")]
    for i, (c, v, d, h, res, minuto, a_tiempo, motivo, pr) in enumerate(ent):
        t = _ts(d, h)
        comp = None if minuto is None else _ts(d, h, minuto)
        cur.execute("""INSERT INTO fact_entregas (cliente_sk, vehiculo_sk, tiempo_sk, zona_sk, entrega_id_odoo,
            resultado, motivo, planificado_utc, completado_utc, limite_plan_utc, a_tiempo, procedencia)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (c, v, _tiempo(cur, t), z["centro"], i + 1, res, motivo, t, comp, _ts(d, h, 15), a_tiempo, pr))

    # (ruta, vehiculo, dia, km plan, km real, min plan, min real, paradas, entregadas, fallidas, procedencia)
    rutas = [(1, 1, 3, 10, 12, 30, 36, 2, 1, 1, "REAL"), (2, 2, 4, 20, None, 40, None, 1, 0, 0, "SIMULADO")]
    for rid, v, d, kp, kr, mp, mr, par, ok, mal, pr in rutas:
        t = _ts(d, 8)
        cur.execute("""INSERT INTO fact_rutas (ruta_id_odoo, codigo, vehiculo_sk, conductor_sk, tiempo_sk, fecha,
            estado, inicio_utc, km_planificado, km_real, min_planificado, min_real, posiciones_gps, paradas_total,
            paradas_entregadas, paradas_fallidas, paradas_pendientes, procedencia)
            VALUES (%s,%s,%s,1,%s,%s,'cerrada',%s,%s,%s,%s,%s,5,%s,%s,%s,%s,%s)""",
                    (rid, "RUTA/%04d" % rid, v, _tiempo(cur, t), date(2026, 11, d), t, kp, kr, mp, mr, par, ok, mal,
                     par - ok - mal, pr))

    # (parada, ruta, dia, zona, estado, min en parada, min desde inicio, procedencia)
    paradas = [(1, 1, 3, "centro", "entregado", 2, 20, "REAL"), (2, 1, 3, "ficoa", "no_entregado", 4, 30, "REAL"),
               (3, 2, 4, "centro", "pendiente", None, None, "SIMULADO")]
    for pid, rid, d, zona, estado, m1, m2, pr in paradas:
        cur.execute("""INSERT INTO fact_paradas (parada_id_odoo, ruta_id_odoo, zona_sk, tiempo_sk, orden, estado,
            min_en_parada, min_desde_inicio_ruta, procedencia) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (pid, rid, z[zona], _tiempo(cur, _ts(d, 8)), pid, estado, m1, m2, pr))

    # (linea, pedido, cliente, producto, zona, dia, cantidad, subtotal)
    ventas = [(1, 1, 1, 1, "centro", 3, 2, 20), (2, 1, 1, 2, "centro", 3, 1, 12.5), (3, 2, 2, 1, "ficoa", 4, 3, 30)]
    for lid, ped, c, p, zona, d, cant, sub in ventas:
        t = _ts(d, 7)
        cur.execute("""INSERT INTO fact_ventas (linea_id_odoo, pedido_id_odoo, pedido_ref, cliente_sk, producto_sk,
            zona_sk, tiempo_sk, fecha_pedido_utc, estado_pedido, cantidad, precio_unitario, subtotal, total,
            lat_aprox, lon_aprox)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'sale',%s,10,%s,%s,-1.242,-78.62)""",
                    (lid, ped, "S%04d" % ped, c, p, z[zona], _tiempo(cur, t), t, cant, sub, sub))

    # Resultados del ML: una corrida del benchmark, una unidad espacial y el pronostico con su backtest.
    cur.execute("""INSERT INTO ml_evaluacion_modelos (corrida_id, modelo, familia, libreria, unidad_espacial,
        procedencia, estado, wape, mae, mase, puesto, elegido) VALUES
        ('c1','lightgbm_tweedie','ml_arboles','lightgbm','h3:8','TODAS','ok',0.40,0.8,0.7,1,true),
        ('c1','estacional_7','baseline','propio','h3:8','TODAS','ok',0.60,1.2,1.0,2,false),
        ('c1','tft','deep_learning','neuralforecast','h3:8','TODAS','omitido',NULL,NULL,NULL,NULL,false)""")
    cur.execute("INSERT INTO ml_unidad_espacial (tipo, unidad_id, centro_lat, centro_lon, lineas) "
                "VALUES ('h3:8','88abc',-1.242,-78.62,3)")
    cur.execute("""INSERT INTO ml_pronostico_demanda (tipo_registro, fecha_objetivo, producto_sk, tipo_unidad, unidad_id,
        unidades_pred, unidades_real, p10, p90, modelo, model_version) VALUES
        ('backtest','2026-11-03',1,'h3:8','88abc',2.5,2,NULL,NULL,'lightgbm_tweedie','v1'),
        ('pronostico','2026-11-05',1,'h3:8','88abc',3,NULL,1,5,'lightgbm_tweedie','v1')""")

    cur.execute("""INSERT INTO etl_ejecucion (lote_id, modo, inicio_utc, fin_utc, estado, cargados, rechazados,
                                              omitidos, error) VALUES
        (1,'full',%s,%s,'ok','{"fact_entregas": 4, "fact_rutas": 2}','{"coordenadas_invalidas": 2}','[]',NULL),
        (2,'incremental',%s,%s,'error','{}','{"coordenadas_invalidas": 1, "velocidad_anomala": 1}','["traccar"]',
         'Traccar no responde')""", (_ts(4, 16), _ts(4, 16, 1), _ts(4, 17), _ts(4, 17, 2)))


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
            for f in ("dwh_schema.sql", "dwh_views.sql", "dwh_bi_views.sql"):
                with open(os.path.join(HERE, f), encoding="utf-8") as fh:
                    cur.execute(fh.read())
            _poblar(cur)
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
