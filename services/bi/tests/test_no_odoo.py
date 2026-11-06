import ast
import os

BI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROHIBIDOS = {"xmlrpc", "odoo", "odoorpc", "requests"}


def test_no_odoo():
    """§10.3: el BI consulta solo el DWH; ningun archivo importa xmlrpc, odoo ni requests."""
    hallados = []
    for raiz, dirs, files in os.walk(BI):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for f in files:
            ruta = os.path.join(raiz, f)
            if f.endswith(".py"):
                with open(ruta, encoding="utf-8") as fh:
                    for n in ast.walk(ast.parse(fh.read())):
                        mods = []
                        if isinstance(n, ast.Import):
                            mods = [a.name for a in n.names]
                        elif isinstance(n, ast.ImportFrom) and n.module:
                            mods = [n.module]
                        hallados += [(ruta, m) for m in mods if m.split(".")[0] in PROHIBIDOS]
            elif f.startswith("requirements"):
                with open(ruta, encoding="utf-8") as fh:
                    for linea in fh:
                        if linea.strip().lower().split("=")[0] in PROHIBIDOS:
                            hallados.append((ruta, linea.strip()))
    assert not hallados, hallados


def test_copias_esquema_iguales_a_etl():
    """Las copias de tests/ deben coincidir con services/etl/sql (si la carpeta existe; no esta en la imagen)."""
    import pytest
    etl = os.path.join(os.path.dirname(BI), "etl", "sql")
    if not os.path.isdir(etl):
        pytest.skip("services/etl/sql no esta presente")
    for nombre in ("dwh_schema.sql", "dwh_views.sql"):
        with open(os.path.join(etl, nombre), "rb") as a, open(os.path.join(BI, "tests", nombre), "rb") as b:
            assert a.read() == b.read(), "%s difiere del ETL: vuelva a copiarlo" % nombre
