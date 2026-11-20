import glob
import os
import re

import pytest

from etl import config
from etl.__main__ import main

ETL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "etl")

SECRETOS = ["ODOO_PASSWORD", "TRACCAR_PASSWORD", "ETL_STG_PASSWORD", "DWH_ETL_PASSWORD"]


@pytest.fixture
def entorno(monkeypatch):
    """Entorno minimo valido; el host es inalcanzable a proposito para detectar cualquier conexion."""
    for k in ("DB_HOST", "DB_PORT", "STAGING_DB", "STAGING_USER", "DWH_DB", "DWH_ETL_USER", "ETL_HORARIO",
              "ETL_RETENTION_DAYS", "ETL_TZ", "ETL_FULL_HOURS", "ETL_TRACCAR_DAYS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DB_HOST", "no-existe.invalid")
    for k in SECRETOS:
        monkeypatch.setenv(k, "x")
    return monkeypatch


def test_variable_vacia_cuenta_como_faltante(monkeypatch):
    monkeypatch.setenv("ODOO_PASSWORD", "")
    with pytest.raises(config.ConfigError, match="ODOO_PASSWORD"):
        config.require("ODOO_PASSWORD")


@pytest.mark.parametrize("variable, funcion", [("ETL_STG_PASSWORD", "staging_params"),
                                               ("DWH_ETL_PASSWORD", "dwh_params"),
                                               ("DWH_ADMIN_DSN", "admin_dsn")])
def test_secreto_sin_variable_falla_claro(monkeypatch, variable, funcion):
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(config.ConfigError, match=variable):
        getattr(config, funcion)()


def test_conexiones_armadas_por_partes(entorno):
    """La clave viaja como argumento, no dentro de una URL: puede tener cualquier caracter."""
    entorno.setenv("DB_HOST", "pghost")
    entorno.setenv("DB_PORT", "6543")
    entorno.setenv("ETL_STG_PASSWORD", "p:con/raros@ y espacio")
    assert config.staging_params() == dict(host="pghost", port="6543", dbname="logistica_staging", user="etl_stg",
                                           password="p:con/raros@ y espacio")
    assert config.dwh_params() == dict(host="pghost", port="6543", dbname="logistica_dwh", user="dwh_etl",
                                       password="x")


def test_valores_por_defecto_no_secretos(entorno):
    entorno.delenv("DB_HOST")
    p = config.dwh_params()
    assert (p["host"], str(p["port"]), p["dbname"], p["user"]) == ("db", "5432", "logistica_dwh", "dwh_etl")
    assert (config.horario(), config.dias_retencion(), config.horas_entre_completas(),
            config.dias_ventana_traccar(), config.zona_horaria()) == ([(3, 0), (12, 0)], 30, 20, 30, "America/Guayaquil")


def test_variable_no_secreta_vacia_usa_el_valor_por_defecto(entorno):
    """Compose pasa las variables sin definir como cadena vacia."""
    entorno.setenv("ETL_HORARIO", "")
    entorno.setenv("ETL_TZ", "")
    assert config.horario() == [(3, 0), (12, 0)] and config.zona_horaria() == "America/Guayaquil"


@pytest.mark.parametrize("variable, valor", [("ETL_HORARIO", "cinco"), ("ETL_HORARIO", "25:00"),
                                             ("ETL_HORARIO", " , "), ("ETL_RETENTION_DAYS", "-1"),
                                             ("ETL_FULL_HOURS", "1.5")])
def test_numero_invalido_es_error_de_configuracion(entorno, variable, valor):
    entorno.setenv(variable, valor)
    with pytest.raises(config.ConfigError, match=variable):
        (config.horario(), config.dias_retencion(), config.horas_entre_completas())


def test_horario_ordenado_y_mayor_hueco(entorno):
    entorno.setenv("ETL_HORARIO", "12:00, 3")
    assert config.horario() == [(3, 0), (12, 0)]
    assert config.max_hueco_min() == 15 * 60              # de 12:00 a 03:00 del dia siguiente
    entorno.setenv("ETL_HORARIO", "06:30")
    assert config.max_hueco_min() == 24 * 60


@pytest.mark.parametrize("faltante", SECRETOS)
def test_run_sin_credenciales_falla_antes_de_conectar(entorno, capsys, faltante):
    entorno.delenv(faltante)
    assert main(["run", "--mode", "full"]) == 2
    assert faltante in capsys.readouterr().err


@pytest.mark.parametrize("comando, faltante", [
    ("simulate", "ETL_STG_PASSWORD"), ("simulate", "DWH_ETL_PASSWORD"),
    ("report", "ETL_STG_PASSWORD"), ("purge", "ETL_STG_PASSWORD"),      # report y purge solo usan staging
    ("health", "DWH_ETL_PASSWORD")])                                    # health solo usa el DWH
def test_comandos_sin_credenciales_fallan_antes_de_conectar(entorno, capsys, comando, faltante):
    entorno.delenv(faltante)
    assert main([comando]) == 2
    assert faltante in capsys.readouterr().err


def test_sin_credenciales_por_defecto_en_codigo():
    archivos = glob.glob(os.path.join(ETL_DIR, "**", "*.py"), recursive=True)
    assert len(archivos) > 10
    for path in archivos:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert not re.search(r"env\(\s*[\"'][A-Z_]*(PASSWORD|DSN)[\"']\s*,", src), "secreto por defecto en " + path
        assert "odoo:odoo@" not in src, path
        assert "postgresql://" not in src, "DSN completo en " + path


def test_serve_hace_bootstrap_una_vez_y_reintenta_si_falla(entorno, monkeypatch):
    """`etl serve` (servicio del servidor): bootstrap sin --reset antes de la primera corrida; si falla (p. ej.
    faltan claves) se reintenta en el ciclo siguiente y no se repite una vez hecho."""
    from etl import __main__ as cli
    from etl import scheduler
    llamadas = []
    entorno.delenv("DWH_ADMIN_DSN", raising=False)
    monkeypatch.setattr(cli.db, "bootstrap", lambda **kw: llamadas.append(kw["reset"]) or {
        "staging_owner": True, "dwh_owner": True, "ro": True, "ml": True})
    monkeypatch.setattr(cli, "_corrida", lambda modo: "corrida %s" % modo)
    salidas = []

    def correr(ciclo):
        for i in range(3):
            if i == 1:
                entorno.setenv("DWH_ADMIN_DSN", "x")
            try:
                salidas.append(ciclo())
            except config.ConfigError as exc:
                salidas.append("config: %s" % exc)
        return 0
    monkeypatch.setattr(scheduler, "run", correr)
    assert main(["serve"]) == 0
    assert "DWH_ADMIN_DSN" in salidas[0]
    assert salidas[1:] == ["corrida auto", "corrida auto"]
    assert llamadas == [False]          # una sola vez y nunca con --reset
