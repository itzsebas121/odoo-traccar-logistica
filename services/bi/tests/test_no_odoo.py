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
