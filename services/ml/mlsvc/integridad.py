"""Verificacion de los modelos que el servidor carga con joblib.

joblib usa pickle: cargar un archivo ajeno puede ejecutar codigo. Por eso `models/SHA256SUMS` guarda el hash de cada
modelo que se sirve (demanda.joblib, model.joblib), en formato sha256sum. El entrenamiento en local lo actualiza
(registrar) y el servidor no carga ningun archivo cuyo hash no coincida (verificar).

Limite: el manifiesto viaja en el mismo repo que los modelos. Esto protege contra archivos cambiados o corruptos en el
servidor y deja rastro en cada cambio de hash; no protege contra quien puede hacer push a la rama. Eso lo dan las
ramas protegidas y la revision de cambios en GitHub.
"""
import hashlib
import os
import pathlib
import tempfile

MANIFIESTO = "SHA256SUMS"


class ModeloNoVerificado(RuntimeError):
    """El archivo no tiene hash registrado o no coincide con el registrado."""


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _leer(carpeta):
    f = pathlib.Path(carpeta) / MANIFIESTO
    if not f.exists():
        return {}
    entradas = {}
    for linea in f.read_text(encoding="utf-8").splitlines():
        partes = linea.split(None, 1)
        if len(partes) == 2:
            entradas[partes[1].strip()] = partes[0].lower()
    return entradas


def _escribir(ruta, texto):
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=ruta.name + ".")
    os.close(fd)
    try:
        pathlib.Path(tmp).write_text(texto, encoding="utf-8")
        os.replace(tmp, ruta)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def registrar(ruta):
    """Anota el hash actual de `ruta` en el manifiesto de su carpeta. Lo llama el entrenamiento tras guardar."""
    ruta = pathlib.Path(ruta)
    entradas = _leer(ruta.parent)
    entradas[ruta.name] = sha256(ruta)
    _escribir(ruta.parent / MANIFIESTO,
              "".join("%s  %s\n" % (h, nombre) for nombre, h in sorted(entradas.items())))


def verificar(ruta):
    """Lanza ModeloNoVerificado si `ruta` no tiene hash registrado o su contenido no coincide."""
    ruta = pathlib.Path(ruta)
    esperado = _leer(ruta.parent).get(ruta.name)
    if esperado is None:
        raise ModeloNoVerificado("%s no tiene hash en %s: no se carga un modelo sin registrar. Reentrene en local "
                                 "(o registre el archivo) y suba el manifiesto." % (ruta.name, MANIFIESTO))
    if sha256(ruta) != esperado:
        raise ModeloNoVerificado("%s no coincide con su hash en %s: el archivo cambio desde el entrenamiento. "
                                 "Reentrene en local y suba los archivos." % (ruta.name, MANIFIESTO))
