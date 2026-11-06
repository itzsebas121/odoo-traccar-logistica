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
    for k in ("DB_HOST", "DB_PORT", "STAGING_DB", "STAGING_USER", "DWH_DB", "DWH_ETL_USER"):
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
    entorno.setenv("DB_HOST", "pghost")
    entorno.setenv("DB_PORT", "6543")
    entorno.setenv("ETL_STG_PASSWORD", "p:con/raros@")
    assert config.staging_params() == dict(host="pghost", port="6543", dbname="logistica_staging", user="etl_stg",
                                           password="p:con/raros@")
    assert config.dwh_params() == dict(host="pghost", port="6543", dbname="logistica_dwh", user="dwh_etl",
                                       password="x")


def test_valores_por_defecto_no_secretos(entorno):
    entorno.delenv("DB_HOST")
    p = config.dwh_params()
    assert (p["host"], str(p["port"]), p["dbname"], p["user"]) == ("db", "5432", "logistica_dwh", "dwh_etl")


@pytest.mark.parametrize("faltante", SECRETOS)
def test_run_sin_credenciales_falla_antes_de_conectar(entorno, capsys, faltante):
    entorno.delenv(faltante)
    assert main(["run", "--mode", "full"]) == 2
    assert faltante in capsys.readouterr().err


@pytest.mark.parametrize("faltante", ["ETL_STG_PASSWORD", "DWH_ETL_PASSWORD"])
def test_simulate_sin_credenciales_falla_antes_de_conectar(entorno, capsys, faltante):
    entorno.delenv(faltante)
    assert main(["simulate"]) == 2
    assert faltante in capsys.readouterr().err


def test_sin_credenciales_por_defecto_en_codigo():
    archivos = glob.glob(os.path.join(ETL_DIR, "*.py"))
    assert archivos
    for path in archivos:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert not re.search(r"env\(\s*[\"'][A-Z_]*(PASSWORD|DSN)[\"']\s*,", src), "secreto por defecto en " + path
        assert "odoo:odoo@" not in src, path
        assert "postgresql://" not in src, "DSN completo en " + path
