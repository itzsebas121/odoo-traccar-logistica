from datetime import date

import pytest

import olap

NOMBRES = {"distancia_vehiculo", "recorridos_dia_hora", "duracion_promedio", "zonas_visitadas",
           "paradas", "entregas_cliente", "entregas_estado", "cumplimiento"}


def total(df, clave, col):
    return float(df[df[clave].isna()][col].iloc[0])


def test_olap_ejecuta(conn, monkeypatch):
    """Cada consulta se ejecuta con datos y devuelve filas; las de ROLLUP traen una fila de total."""
    assert set(olap.QUERIES) == NOMBRES
    for nombre, (_, rollup) in olap.QUERIES.items():
        df = olap.consulta(conn, nombre)
        assert len(df) > 0, nombre
        if rollup:
            claves = [c for c in df.columns if c.startswith("k_")]
            assert df[claves].isna().all(axis=1).any(), "sin fila de total en %s" % nombre
    assert total(olap.consulta(conn, "distancia_vehiculo"), "k_vehiculo", "distancia_km") == 100.0
    # sin DWH_DB_PASSWORD la aplicacion falla con un mensaje claro
    monkeypatch.delenv("DWH_DB_PASSWORD", raising=False)
    with pytest.raises(olap.ConfigError, match="DWH_DB_PASSWORD"):
        olap.dsn()


def test_filtro_procedencia(conn):
    real = olap.consulta(conn, "distancia_vehiculo", procedencia=["REAL"])
    sim = olap.consulta(conn, "distancia_vehiculo", procedencia=["SIMULADO"])
    assert set(real["k_vehiculo"].dropna()) == {"ABC-1234"}
    assert set(sim["k_vehiculo"].dropna()) == {"DEF-5678"}
    assert total(real, "k_vehiculo", "distancia_km") == 30.0
    ent = olap.consulta(conn, "entregas_estado", procedencia=["REAL"])
    assert total(ent, "k_resultado", "entregas") == 2
    assert olap.hay_simulados(["REAL", "SIMULADO"]) and not olap.hay_simulados(["REAL"])
    # filtro de fechas
    df = olap.consulta(conn, "distancia_vehiculo", desde=date(2026, 11, 4), hasta=date(2026, 11, 4))
    assert total(df, "k_vehiculo", "distancia_km") == 60.0


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
    # 2 entregadas: una a las 08:00 (plan 08:15, a tiempo) y otra a 14:30 (plan 14:15, tarde) -> 50 %
    assert total(ind["cumplimiento"], "k_vehiculo", "pct_a_tiempo") == 50.0
