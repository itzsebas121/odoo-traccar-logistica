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
    for k in ("DB_HOST", "DB_PORT", "STAGING_DB", "STAGING_USER", "DWH_DB", "DWH_ETL_USER", "ETL_INTERVAL_MIN",
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
    assert (config.intervalo_min(), config.dias_retencion(), config.horas_entre_completas(),
            config.dias_ventana_traccar(), config.zona_horaria()) == (15, 30, 24, 30, "America/Guayaquil")


def test_variable_no_secreta_vacia_usa_el_valor_por_defecto(entorno):
    """Compose pasa las variables sin definir como cadena vacia."""
    entorno.setenv("ETL_INTERVAL_MIN", "")
    entorno.setenv("ETL_TZ", "")
    assert config.intervalo_min() == 15 and config.zona_horaria() == "America/Guayaquil"


@pytest.mark.parametrize("variable, valor", [("ETL_INTERVAL_MIN", "cinco"), ("ETL_INTERVAL_MIN", "0"),
                                             ("ETL_RETENTION_DAYS", "-1"), ("ETL_FULL_HOURS", "1.5")])
def test_numero_invalido_es_error_de_configuracion(entorno, variable, valor):
    entorno.setenv(variable, valor)
    with pytest.raises(config.ConfigError, match=variable):
        (config.intervalo_min(), config.dias_retencion(), config.horas_entre_completas())


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
