"""Ubicacion aproximada de las ventas, vistas de demanda para el ML, vistas BI y rol dwh_ml."""
import psycopg2
import pytest

from conftest import correr, q1, qall
from test_layout import VISTAS_BI


def test_ventas_guardan_ubicacion_aproximada(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    filas = dict((r[0], (r[1], r[2])) for r in qall(
        dwh_con, "select linea_id_odoo, lat_aprox, lon_aprox from fact_ventas order by 1"))
    assert filas[501] == (-1.242, -78.62)          # -1.2417, -78.6197 redondeado a 3 decimales (~110 m)
    assert filas[504][0] is not None              # sin coordenadas en el pedido: usa las de su entrega


def test_v_ml_ventas_geo(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    fila = qall(dwh_con, "select producto, categoria, grupo, zona, cantidad, fecha_local, lat_aprox "
                         "from v_ml_ventas_geo where linea_id_odoo=501")[0]
    assert fila[0] == "[P1] Producto Uno" and fila[1] == "All" and fila[3] == "centro" and fila[4] == 2
    assert fila[5] is not None and fila[6] == -1.242


def test_v_ml_demanda_diaria_rellena_con_ceros(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    # La linea 503 (P1) pasa a la misma zona que la 501 (P1, 2026-11-05 local) pero tres dias despues.
    with dwh_con.cursor() as cur:
        cur.execute("insert into dim_tiempo (sk, fecha, anio, mes, dia, dia_semana, hora, fecha_local, hora_local, "
                    "dia_semana_local) values (2026110812, '2026-11-08', 2026, 11, 8, 7, 12, '2026-11-08', 7, 7) "
                    "on conflict do nothing")
        cur.execute("update fact_ventas set tiempo_sk = 2026110812, "
                    "zona_sk = (select zona_sk from fact_ventas where linea_id_odoo = 501) where linea_id_odoo = 503")
    dwh_con.commit()
    filas = qall(dwh_con, "select fecha_local::text, unidades from v_ml_demanda_diaria_zona d "
                          "join dim_producto p on p.sk = d.producto_sk where p.referencia = 'P1' and d.zona = 'centro' "
                          "order by 1")
    assert filas == [("2026-11-05", 2), ("2026-11-06", 0), ("2026-11-07", 0), ("2026-11-08", 1)]


def test_vistas_bi_responden(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    for vista in sorted(VISTAS_BI):
        q1(dwh_con, "select count(*) from %s" % vista)
    assert q1(dwh_con, "select count(*) from v_bi_ventas_diarias") >= 1
    assert q1(dwh_con, "select sum(importe) from v_bi_ventas_diarias") == q1(
        dwh_con, "select sum(subtotal) from fact_ventas")
    assert q1(dwh_con, "select count(*) from v_bi_dim_fecha") >= 30
    assert q1(dwh_con, "select count(*) from v_bi_comparativa_modelos") == 0        # sin corridas del ML


def test_comparativa_muestra_la_ultima_corrida(dwh_con):
    with dwh_con.cursor() as cur:
        for corrida, t, modelo in (("c1", "2026-11-01", "naive"), ("c2", "2026-11-02", "lightgbm"),
                                   ("c2", "2026-11-02", "naive")):
            cur.execute("insert into ml_evaluacion_modelos (corrida_id, corrida_utc, modelo, familia, "
                        "unidad_espacial, procedencia, wape, elegido) values (%s,%s,%s,'x','zona','TODAS',0.3,%s)",
                        (corrida, t, modelo, modelo == "lightgbm"))
    dwh_con.commit()
    assert sorted(r[0] for r in qall(dwh_con, "select modelo from v_bi_comparativa_modelos")) == ["lightgbm", "naive"]
    assert qall(dwh_con, "select modelo_elegido from v_bi_corridas_modelo where corrida_id='c2'") == [("lightgbm",)]


# ---------------------------------------------------------------- rol dwh_ml
def test_dwh_ml_escribe_solo_tablas_ml(dbs_roles):
    e = dbs_roles
    ml = e.connect(e.dwh_db, e.ml_role, autocommit=True)
    try:
        with ml.cursor() as cur:
            cur.execute("insert into ml_evaluacion_modelos (corrida_id, modelo, familia, unidad_espacial, "
                        "procedencia) values ('c','m','f','zona','TODAS')")
            cur.execute("insert into ml_unidad_espacial (tipo, unidad_id) values ('zona','centro')")
            cur.execute("insert into ml_pronostico_demanda (fecha_objetivo, tipo_unidad, unidad_id, unidades_pred, "
                        "modelo, model_version) values ('2026-11-20','zona','centro',1,'m','v')")
            cur.execute("delete from ml_pronostico_demanda")
            cur.execute("select count(*) from v_ml_ventas_geo")
            cur.execute("select count(*) from v_bi_ventas_diarias")
        with ml.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("insert into dim_zona (codigo, nombre) values ('x','x')")
        with ml.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("delete from fact_ventas")
    finally:
        ml.close()
    with pytest.raises(psycopg2.OperationalError, match="permission denied for database"):
        e.connect(e.stg_db, e.ml_role)


def test_dwh_ro_no_escribe_tablas_ml(dbs_roles):
    e = dbs_roles
    ro = e.connect(e.dwh_db, e.ro_role, autocommit=True)
    try:
        with ro.cursor() as cur:
            cur.execute("select count(*) from ml_evaluacion_modelos")
        with ro.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("insert into ml_unidad_espacial (tipo, unidad_id) values ('zona','x')")
    finally:
        ro.close()


def test_vista_de_lineas_de_venta_cuadra_con_las_ventas(stg_con, dwh_con, odoo, traccar):
    """v_bi_lineas_venta (base de los filtros del tablero) tiene las mismas ventas que v_bi_ventas_diarias y cuenta cada
    pedido una sola vez aunque tenga varias lineas."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select sum(importe) from v_bi_lineas_venta") == q1(dwh_con, "select sum(importe) from v_bi_ventas_diarias")
    assert q1(dwh_con, "select sum(unidades) from v_bi_lineas_venta") == q1(dwh_con, "select sum(unidades) from v_bi_ventas_diarias")
    assert q1(dwh_con, "select count(distinct pedido_id_odoo) from v_bi_lineas_venta") == q1(
        dwh_con, "select count(*) from v_bi_pedidos")
