import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EXCLUIR = {"__pycache__", ".pytest_cache", "data", "models", ".git"}
# "esquema." seguido de identificador (el DWH usa tablas/vistas publicas, sin prefijo de esquema).
PATRON = re.compile(r"\b" + "dw" + r"h\.[A-Za-z_]", re.IGNORECASE)


def test_sin_prefijo_de_esquema_dwh_en_sql():
    ofensores = []
    for f in RAIZ.rglob("*"):
        if not f.is_file() or EXCLUIR & set(f.relative_to(RAIZ).parts):
            continue
        try:
            texto = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, linea in enumerate(texto.splitlines(), 1):
            if PATRON.search(linea):
                ofensores.append(f"{f.relative_to(RAIZ)}:{n}: {linea.strip()}")
    assert not ofensores, "\n".join(ofensores)
