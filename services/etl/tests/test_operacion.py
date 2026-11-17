"""Operacion: historico simulado, programador y comandos de la CLI (report, purge, health)."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from conftest import NOW, TZ, correr, q1
from etl import __main__ as cli
from etl import config, db, scheduler, simulate, staging

UTC = timezone.utc


# ---------------------------------------------------------------- simulado
def test_simulado_marcado_y_sin_zonas_previas(stg_con, dwh_con):
    """`simulate` funciona en un DWH recien creado: crea los codigos de zona del contrato si faltan."""
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _inicio = staging.new_lote(scur, "simulate")
        primero = simulate.generar(dcur, lote, dias=5, seed=1, now=NOW, tz=TZ)
        segundo = simulate.generar(dcur, lote, dias=5, seed=1, now=NOW, tz=TZ)      # idempotente
    stg_con.commit()
    dwh_con.commit()
    assert primero > 0 and segundo == 0
    assert q1(dwh_con, "select count(*) from fact_recorridos where procedencia <> 'SIMULADO'") == 0
    assert q1(dwh_con, "select count(*) from dim_vehiculo where procedencia='SIMULADO'") == 3
    assert q1(dwh_con, "select count(*) from v_viajes_entrenamiento where procedencia='SIMULADO'") == primero
    assert q1(dwh_con, "select count(*) from dim_zona") == 7


def test_simulado_en_hora_local(stg_con, dwh_con):
    """Los viajes simulados siguen la jornada local (07:00-21:00 en ETL_TZ), no la de UTC: el ML y dim_tiempo
    trabajan con la hora local, y el patron por franja debe caer en la franja local correcta."""
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _inicio = staging.new_lote(scur, "simulate")
        simulate.generar(dcur, lote, dias=10, seed=3, now=NOW, tz=TZ)
    stg_con.commit()
    dwh_con.commit()
    minima, maxima = qall_uno(dwh_con, "select min(t.hora_local), max(t.hora_local) from fact_recorridos r "
                                       "join dim_tiempo t on t.sk=r.tiempo_inicio_sk where r.procedencia='SIMULADO'")
    assert 7 <= minima and maxima < 21
    # SIM-003 prefiere izamba de manana: es el destino mas frecuente antes de las 12 locales
    assert q1(dwh_con, """select zd.codigo from fact_recorridos r join dim_tiempo t on t.sk=r.tiempo_inicio_sk
                          join dim_vehiculo v on v.sk=r.vehiculo_sk join dim_zona zd on zd.sk=r.zona_destino_sk
                          where v.placa='SIM-003' and t.hora_local < 12
                          group by zd.codigo order by count(*) desc limit 1""") == "izamba"


def qall_uno(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()


def test_simulado_y_real_conviven(stg_con, dwh_con, odoo, traccar):
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _inicio = staging.new_lote(scur, "simulate")
        simulados = simulate.generar(dcur, lote, dias=3, seed=1, now=NOW, tz=TZ)
    stg_con.commit()
    dwh_con.commit()
    correr(stg_con, dwh_con, "full", odoo, traccar)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    # la carga real completa las zonas del contrato con los datos de Odoo y no toca lo simulado
    assert q1(dwh_con, "select latitud from dim_zona where codigo='ficoa'") == -1.2230
    assert q1(dwh_con, "select count(*) from fact_recorridos where procedencia='SIMULADO'") == simulados
    assert q1(dwh_con, "select count(*) from fact_recorridos where procedencia='REAL'") == 2
    assert q1(dwh_con, "select count(*) from dim_vehiculo where procedencia='SIMULADO' "
                       "and traccar_device_id is null") == 3


# ---------------------------------------------------------------- programador
def test_modo_completo_la_primera_vez_y_cada_24_horas(stg_con, dwh_con, odoo, traccar):
    assert scheduler.decidir_modo(stg_con, 24) == "full"
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert scheduler.decidir_modo(stg_con, 24) == "incremental"
    manana = datetime.now(UTC) + timedelta(hours=25)
    assert scheduler.decidir_modo(stg_con, 24, now=manana) == "full"


def test_el_programador_sobrevive_a_los_errores():
    parar, mensajes = threading.Event(), []
    resultados = iter([config.ConfigError("Falta X"), db.Ocupado("ocupado"), RuntimeError("Odoo caido"), "ETL ok"])

    def ciclo():
        r = next(resultados)
        if isinstance(r, Exception):
            raise r
        parar.set()
        return r

    assert scheduler.bucle(ciclo, 0, parar, registrar=lambda m, error=False: mensajes.append((m, error))) == 4
    assert [e for _m, e in mensajes] == [True, False, True, False]
    assert "Falta X" in mensajes[0][0] and "Odoo caido" in mensajes[2][0] and mensajes[3][0] == "ETL ok"


def test_el_programador_no_corre_si_ya_se_pidio_parar():
    parar = threading.Event()
    parar.set()
    assert scheduler.bucle(lambda: pytest.fail("no debia correr"), 0, parar) == 0


# ---------------------------------------------------------------- CLI
@pytest.fixture
def cli_env(dbs_roles, monkeypatch):
    """Variables de entorno de la CLI apuntando a las bases y roles desechables."""
    import psycopg2.extensions
    e = dbs_roles
    p = psycopg2.extensions.parse_dsn(e.admin)
    for k, v in {"DB_HOST": p["host"], "DB_PORT": p.get("port", "5432"), "STAGING_DB": e.stg_db,
                 "STAGING_USER": e.stg_user, "ETL_STG_PASSWORD": e.passwords[e.stg_user], "DWH_DB": e.dwh_db,
                 "DWH_ETL_USER": e.dwh_user, "DWH_ETL_PASSWORD": e.passwords[e.dwh_user],
                 "ODOO_PASSWORD": "x", "TRACCAR_PASSWORD": "x", "ETL_TZ": TZ, "ETL_RETENTION_DAYS": "0"}.items():
        monkeypatch.setenv(k, v)
    return e


def test_cli_corrida_reporte_salud_y_purga(cli_env, monkeypatch, capsys, odoo, traccar):
    monkeypatch.setattr(cli, "_sources", lambda: (odoo, traccar))
    assert cli.main(["health"]) == 1                      # todavia no hubo ninguna corrida
    assert cli.main(["run", "--mode", "full"]) == 0
    salida = capsys.readouterr().out
    assert "ETL full" in salida and "'fact_entregas': 3" in salida
    assert cli.main(["health"]) == 0
    assert cli.main(["health", "--max-min", "0"]) == 1    # limite imposible: la ultima corrida ya es vieja

    traccar.data["positions"][0]["latitude"] = 91
    assert cli.main(["run", "--mode", "full"]) == 0
    capsys.readouterr()
    assert cli.main(["report", "--lotes", "5"]) == 0
    reporte = capsys.readouterr().out
    assert "Ultimas corridas" in reporte and "full" in reporte
    assert "posicion" in reporte and "coordenadas_invalidas" in reporte
    assert "odoo:logistica.entrega" in reporte

    assert cli.main(["purge", "--dias", "30"]) == 0
    assert "Retencion de 30 dias" in capsys.readouterr().out


def test_cli_simulate_registra_la_ejecucion(cli_env, capsys):
    assert cli.main(["simulate", "--dias", "2", "--seed", "7"]) == 0
    assert "Recorridos SIMULADO insertados" in capsys.readouterr().out
    conn = cli_env.connect(cli_env.dwh_db)
    try:
        assert q1(conn, "select count(*) from etl_ejecucion where modo='simulate' and estado='ok'") == 1
        assert q1(conn, "select count(*) from fact_recorridos where procedencia='SIMULADO'") > 0
    finally:
        conn.close()
    assert cli.main(["health"]) == 1                      # un simulado no cuenta como corrida del ETL


def test_cli_corrida_ocupada_devuelve_3(cli_env, monkeypatch, capsys, odoo, traccar):
    monkeypatch.setattr(cli, "_sources", lambda: (odoo, traccar))
    otra = cli_env.connect(cli_env.stg_db)
    try:
        db.tomar_candado(otra)
        assert cli.main(["run"]) == 3
        assert "otra corrida" in capsys.readouterr().err
    finally:
        otra.close()


def test_cli_modo_auto_del_programador(cli_env, monkeypatch, odoo, traccar):
    monkeypatch.setattr(cli, "_sources", lambda: (odoo, traccar))
    assert cli._corrida("auto").startswith("ETL full")
    assert cli._corrida("auto").startswith("ETL incremental")
