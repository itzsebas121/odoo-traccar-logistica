import glob
import os
import re

import pytest

from etl import config
from etl.__main__ import main

ETL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "etl")


def test_dwh_dsn_sin_variable_falla_claro(monkeypatch):
    monkeypatch.delenv("DWH_DSN", raising=False)
    with pytest.raises(config.ConfigError, match="DWH_DSN"):
        config.dwh_dsn()


def test_variable_vacia_cuenta_como_faltante(monkeypatch):
    monkeypatch.setenv("ODOO_PASSWORD", "")
    with pytest.raises(config.ConfigError, match="ODOO_PASSWORD"):
        config.require("ODOO_PASSWORD")


@pytest.mark.parametrize("faltante", ["ODOO_PASSWORD", "TRACCAR_PASSWORD"])
def test_run_sin_credenciales_falla_antes_de_conectar(monkeypatch, capsys, faltante):
    monkeypatch.setenv("DWH_DSN", "postgresql://u@no-existe.invalid:1/x")
    monkeypatch.setenv("ODOO_PASSWORD", "x")
    monkeypatch.setenv("TRACCAR_PASSWORD", "x")
    monkeypatch.delenv(faltante)
    assert main(["run", "--mode", "full"]) == 2
    assert faltante in capsys.readouterr().err


def test_sin_credenciales_por_defecto_en_codigo():
    archivos = glob.glob(os.path.join(ETL_DIR, "*.py"))
    assert archivos
    for path in archivos:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert not re.search(r"env\(\s*[\"'][A-Z_]*PASSWORD[\"']\s*,", src), "contrasena por defecto en " + path
        assert "odoo:odoo@" not in src, path
