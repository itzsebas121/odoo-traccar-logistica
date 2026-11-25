from datetime import date

import pandas as pd
import pytest

import olap

NOMBRES = {"distancia_vehiculo", "recorridos_dia_hora", "duracion_promedio", "zonas_visitadas", "paradas",
           "entregas_cliente", "entregas_estado", "motivos_no_entrega", "cumplimiento", "plan_real_vehiculo",
           "rutas_plan_real", "tiempos_parada", "ventas_cliente", "ventas_producto", "ventas_zona",
           "etl_ejecuciones", "etl_calidad", "etl_rechazos", "od_viajes", "conductor_resumen", "vinculo_gps",
           "demanda_producto_zona", "ventas_categoria", "ventas_dia_semana", "pronostico_vs_real",
           "comparativa_modelos"}


def total(df, clave, col):
    return float(olap.total(df, clave, col))


def test_olap_ejecuta(conn, monkeypatch):
    """Cada consulta se ejecuta con datos y devuelve filas; las de ROLLUP traen una fila de total."""
    assert set(olap.QUERIES) == NOMBRES
    for nombre, (_, rollup) in olap.QUERIES.items():
        df = olap.consulta(conn, nombre)
        assert len(df) > 0, nombre
        if rollup:
            claves = [c for c in df.columns if c.startswith("k_")]
            assert df[claves].isna().all(axis=1).sum() == 1, "debe haber una sola fila de total en %s" % nombre
    assert total(olap.consulta(conn, "distancia_vehiculo"), "k_vehiculo", "distancia_km") == 100.0
    # sin DWH_DB_PASSWORD la aplicacion falla con un mensaje claro
    monkeypatch.delenv("DWH_DB_PASSWORD", raising=False)
    with pytest.raises(olap.ConfigError, match="DWH_DB_PASSWORD"):
        olap.params()


def test_conexion_por_argumentos(monkeypatch):
    """La clave no va dentro de una cadena de conexion: puede tener espacios y comillas."""
    monkeypatch.setenv("DWH_DB_PASSWORD", "con espacio y 'comilla'")
    monkeypatch.setenv("DWH_HOST", "pghost")
    p = olap.params()
    assert p["password"] == "con espacio y 'comilla'" and p["host"] == "pghost" and p["user"] == "dwh_ro"


def test_filtro_procedencia(conn):
    real = olap.consulta(conn, "distancia_vehiculo", procedencia=["REAL"])
    sim = olap.consulta(conn, "distancia_vehiculo", procedencia=["SIMULADO"])
    assert set(real["k_vehiculo"].dropna()) == {"ABC-1234"}
    assert set(sim["k_vehiculo"].dropna()) == {"DEF-5678"}
    assert total(real, "k_vehiculo", "distancia_km") == 30.0
    ent = olap.consulta(conn, "entregas_estado", procedencia=["REAL"])
    assert total(ent, "k_resultado", "entregas") == 2
    assert olap.hay_simulados(["REAL", "SIMULADO"]) and not olap.hay_simulados(["REAL"])
    assert total(olap.consulta(conn, "plan_real_vehiculo", procedencia=["REAL"]), "k_vehiculo", "rutas") == 1
    # filtro de fechas
    df = olap.consulta(conn, "distancia_vehiculo", desde=date(2026, 11, 4), hasta=date(2026, 11, 4))
    assert total(df, "k_vehiculo", "distancia_km") == 60.0


def test_cada_fila_dice_su_procedencia(conn):
    """Los datos simulados no pueden pasar por reales: cada fila indica de donde sale."""
    d = olap.consulta(conn, "distancia_vehiculo").set_index("k_vehiculo")["procedencias"].to_dict()
    assert d["ABC-1234"] == "REAL" and d["DEF-5678"] == "SIMULADO"
    assert olap.consulta(conn, "distancia_vehiculo")["procedencias"].iloc[-1] == "REAL+SIMULADO"       # fila de total


def test_vehiculo_sin_placa_no_se_confunde_con_el_total(conn):
    with conn.cursor() as cur:
        cur.execute("UPDATE dim_vehiculo SET placa = NULL WHERE vehiculo_id_odoo = 2")
    df = olap.consulta(conn, "distancia_vehiculo")
    assert set(df["k_vehiculo"].dropna()) == {"ABC-1234", "(sin placa)"}
    assert total(df, "k_vehiculo", "distancia_km") == 100.0
    conn.rollback()


def test_indicadores(conn):
    """§10.3: distancia, recorridos por dia/hora, duracion, zonas, paradas, entregas por cliente/estado, cumplimiento."""
    ind = olap.indicadores(conn)
    assert set(ind) == NOMBRES
    assert total(ind["duracion_promedio"], "k_vehiculo", "duracion_min") == pytest.approx(56.25)
    assert total(ind["paradas"], "k_vehiculo", "paradas") == 6
    assert set(ind["zonas_visitadas"]["zona"]) >= {"ficoa", "huachi", "izamba", "centro"}
    est = ind["entregas_estado"].dropna(subset=["k_resultado"])
    assert dict(zip(est["k_resultado"], est["entregas"])) == {"entregado": 2, "no_entregado": 1, "pendiente": 1}
    assert set(ind["entregas_cliente"]["k_cliente"].dropna()) == {"Cliente Uno", "Cliente Dos"}
    assert ind["motivos_no_entrega"][["motivo", "entregas"]].values.tolist() == [["absent", 1]]
    # 2 entregadas evaluables: una antes del limite del plan y otra despues -> 50 %
    assert total(ind["cumplimiento"], "k_vehiculo", "pct_a_tiempo") == 50.0
    assert total(ind["cumplimiento"], "k_vehiculo", "evaluables") == 2


def test_plan_contra_real(conn):
    ind = olap.indicadores(conn)
    pr = ind["plan_real_vehiculo"]
    assert (total(pr, "k_vehiculo", "km_planificado"), total(pr, "k_vehiculo", "km_real")) == (30.0, 12.0)
    assert (total(pr, "k_vehiculo", "paradas"), total(pr, "k_vehiculo", "entregadas")) == (3, 1)
    ruta = ind["rutas_plan_real"].set_index("ruta").loc["RUTA/0001"]
    assert (float(ruta["desviacion_km_pct"]), float(ruta["desviacion_min_pct"]), float(ruta["pct_entregado"])) == (
        20.0, 20.0, 50.0)
    assert ruta["vehiculo"] == "ABC-1234" and ruta["conductor"] == "Carlos"
    sin_gps = ind["rutas_plan_real"].set_index("ruta").loc["RUTA/0002"]
    assert pd.isna(sin_gps["km_real"]) and pd.isna(sin_gps["desviacion_km_pct"])    # sin GPS no se inventa nada
    assert ind["rutas_plan_real"]["km_planificado"].dtype == float                   # numeros, no Decimal
    tp = ind["tiempos_parada"].set_index("k_zona")
    assert float(tp.loc["Centro", "min_en_parada"]) == 2.0 and tp.loc["Ficoa", "fallidas"] == 1
    assert total(ind["tiempos_parada"], "k_zona", "paradas") == 3


def test_ventas(conn):
    ind = olap.indicadores(conn)
    assert total(ind["ventas_cliente"], "k_cliente", "importe") == 62.5
    assert total(ind["ventas_cliente"], "k_cliente", "pedidos") == 2
    prod = ind["ventas_producto"].dropna(subset=["k_producto"]).set_index("k_producto")
    assert (float(prod.loc["Producto Uno", "importe"]), float(prod.loc["Producto Uno", "unidades"])) == (50.0, 5.0)
    zona = ind["ventas_zona"].dropna(subset=["k_zona"]).set_index("k_zona")
    assert float(zona.loc["Ficoa", "importe"]) == 30.0
    un_dia = olap.consulta(conn, "ventas_cliente", desde=date(2026, 11, 4), hasta=date(2026, 11, 4))
    assert total(un_dia, "k_cliente", "importe") == 30.0


def test_calidad_del_etl(conn):
    """La bitacora del ETL se lee del DWH (el rol del BI no puede abrir la base de staging)."""
    ej = olap.consulta(conn, "etl_ejecuciones", procedencia=["REAL"])     # la procedencia no le aplica
    assert ej["lote_id"].tolist() == [2, 1]
    assert ej["estado"].tolist() == ["error", "ok"] and ej["error"].tolist() == ["Traccar no responde", None]
    assert [float(x) for x in ej["filas_cargadas"]] == [0.0, 6.0]
    assert [float(x) for x in ej["segundos"]] == [120.0, 60.0]
    rech = olap.consulta(conn, "etl_rechazos").set_index("motivo")
    assert float(rech.loc["coordenadas_invalidas", "filas"]) == 3.0 and rech.loc["coordenadas_invalidas", "corridas"] == 2
    assert float(rech.loc["velocidad_anomala", "filas"]) == 1.0
    assert [float(x) for x in ej["filas_entrada"]] == [0.0, 8.0]
    assert [float(x) for x in ej["filas_validas"]] == [0.0, 6.0]
    calidad = olap.consulta(conn, "etl_calidad").set_index("entidad")
    fila = calidad.loc["entrega"]
    assert (int(fila["entrada"]), int(fila["validos"]), int(fila["rechazados"]), int(fila["transformados"]),
            int(fila["cargados"])) == (6, 4, 2, 4, 4)
    assert int(calidad.loc["ruta", "cargados"]) == 2


def test_total_devuelve_numeros_de_python():
    import pandas as pd
    from decimal import Decimal
    df = pd.DataFrame({"k": ["a", None], "v": [Decimal("1.50"), Decimal("3.00")], "w": [None, None]})
    assert olap.total(df, "k", "v") == 3 and isinstance(olap.total(df, "k", "v"), int)
    assert olap.total(df, "k", "w") == 0
    assert olap.total(df[df["k"].notna()], "k", "v") == 0


def test_rango_fecha_unica():
    """Una sola fecha elegida en st.date_input llega como tupla de 1 elemento: debe filtrar ese dia, no todo."""
    d = date(2026, 11, 4)
    assert olap.rango_fechas((d,)) == (d, d)
    assert olap.rango_fechas(d) == (d, d)
    assert olap.rango_fechas((d, date(2026, 11, 5))) == (d, date(2026, 11, 5))
    assert olap.rango_fechas(()) == (None, None)


def test_recorridos_por_hora_local(conn):
    """Un viaje de las 08:00 UTC se cuenta a las 03:00 locales (UTC-5), no a las 08:00."""
    h = olap.consulta(conn, "recorridos_dia_hora", procedencia=["REAL"])
    horas = set(h["k_hora"].dropna().astype(int))
    assert horas == {3, 4}


def test_consultas_para_la_web(conn):
    ind = olap.indicadores(conn)
    od = ind["od_viajes"]
    assert od["viajes"].sum() == 4 and {"centro", "ficoa"} <= set(od["zona_origen"])
    assert total(ind["conductor_resumen"], "k_conductor", "recorridos") == 4
    vg = ind["vinculo_gps"]
    assert total(vg, "k_resultado", "entregas") == 3          # la pendiente no esta cerrada
    dz = ind["demanda_producto_zona"]
    assert float(dz["unidades"].sum()) == 6.0
    cat = ind["ventas_categoria"].dropna(subset=["k_categoria"]).set_index("k_categoria")
    assert float(cat.loc["Granos", "unidades"]) == 5.0 and float(cat.loc["Limpieza", "importe"]) == 12.5
    assert total(ind["ventas_categoria"], "k_categoria", "importe") == 62.5
    assert set(ind["ventas_dia_semana"]["dia_semana"]) <= set(range(1, 8))
    pr = ind["pronostico_vs_real"].set_index("tipo_registro")
    assert float(pr.loc["backtest", "unidades_real"]) == 2.0 and float(pr.loc["pronostico", "p90"]) == 5.0
    cm = ind["comparativa_modelos"]
    assert cm.loc[cm["elegido"], "modelo"].tolist() == ["lightgbm_tweedie"]
    assert cm["modelo"].tolist()[:2] == ["lightgbm_tweedie", "estacional_7"]


def test_filtro_procedencia_en_ventas_y_viajes(conn):
    assert olap.consulta(conn, "od_viajes", procedencia=["SIMULADO"])["viajes"].sum() == 2
    assert olap.consulta(conn, "demanda_producto_zona", procedencia=["SIMULADO"]).empty


def test_vistas_bi_para_power_bi(conn):
    """Las vistas planas sin parametros existen y suman lo mismo que los hechos."""
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_bi_%'")
        vistas = {r[0] for r in cur.fetchall()}
        assert len(vistas) >= 20
        for v in sorted(vistas):
            cur.execute("SELECT count(*) FROM %s" % v)
        cur.execute("SELECT sum(importe) FROM v_bi_ventas_diarias")
        assert float(cur.fetchone()[0]) == 62.5
        cur.execute("SELECT count(*) FROM v_bi_recorridos")
        assert cur.fetchone()[0] == 4
        cur.execute("SELECT modelo FROM v_bi_comparativa_modelos WHERE elegido")
        assert cur.fetchall() == [("lightgbm_tweedie",)]
        cur.execute("SELECT puesto FROM v_bi_top_productos_zona WHERE zona='centro' ORDER BY puesto")
        assert [r[0] for r in cur.fetchall()] == [1, 2]
    conn.rollback()
