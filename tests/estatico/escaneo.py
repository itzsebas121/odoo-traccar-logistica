# -*- coding: utf-8 -*-
"""Busca datos de negocio y literales de contraseña fuera de su sitio.

Los tokens salen de seeds/data (uniqueId, ref, marca, modelo, cliente y el
nombre de cada geocerca). No se buscan placas ni nombres de persona: las
pruebas de ETL y BI ya los usan como datos de ejemplo de esa fase.

Tampoco se busca el valor de las variables de .env si está vacío. Las claves
cuyo nombre contiene PASSWORD, TOKEN o SECRET sí se buscan cuando el valor
tiene al menos 8 caracteres. El hallazgo de una contraseña no incluye el valor.
"""
import json
import os
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DIR_EXCLUIDOS = {
    '.git', '.codegraph', '__pycache__', '.pytest_cache', '.superpowers',
    '.idea', '.vscode', 'docs', 'backups',
}
EXTENSIONES = {
    '.py', '.xml', '.js', '.json', '.yml', '.yaml', '.md', '.sh', '.ps1',
    '.csv', '.txt', '.conf', '.toml', '.example',
}
CLAVES_TOKEN = {'uniqueId', 'ref', 'marca', 'modelo', 'cliente'}
_PASSWORD = re.compile(
    r"""(?i)(?:['\"]password['\"]\s*:\s*|password\s*=\s*)['\"]([^'\"]{8,})['\"]""")


class Hallazgo(object):
    def __init__(self, ruta, motivo):
        self.ruta = ruta
        self.motivo = motivo

    def __eq__(self, otro):
        return isinstance(otro, Hallazgo) and (self.ruta, self.motivo) == (otro.ruta, otro.motivo)

    def __repr__(self):
        return 'Hallazgo(%r, %r)' % (self.ruta, self.motivo)


def _relativa(raiz, ruta):
    return ruta.relative_to(raiz).as_posix()


def _excluida(raiz, ruta):
    relativa = _relativa(raiz, ruta)
    if relativa == '.env' or relativa.startswith('.env.') or '/.env.' in relativa:
        return True
    partes = Path(relativa).parts
    if any(parte in DIR_EXCLUIDOS for parte in partes):
        return True
    return 'seeds/data/' in (relativa + '/') or relativa.startswith('seeds/data/')


def tokens_de_datos(directorio):
    """Identificadores de negocio leídos de los JSON de seeds/data."""
    tokens = set()
    for ruta in Path(directorio).glob('*.json'):
        datos = json.loads(ruta.read_text(encoding='utf-8'))
        _recolectar(datos, tokens)
    return {token for token in tokens if isinstance(token, str) and len(token) >= 6}


def _recolectar(nodo, tokens):
    if isinstance(nodo, dict):
        for clave, valor in nodo.items():
            if clave in CLAVES_TOKEN and isinstance(valor, str):
                tokens.add(valor)
            if clave == 'name' and isinstance(valor, str) and 'area' in nodo:
                tokens.add(valor)
            _recolectar(valor, tokens)
    elif isinstance(nodo, list):
        for item in nodo:
            _recolectar(item, tokens)


def secretos_de_env(ruta_env):
    """Valores no vacíos de claves secretas. No devuelve la clave, solo el valor para buscarlo."""
    if not ruta_env.is_file():
        return set()
    valores = set()
    for linea in ruta_env.read_text(encoding='utf-8').splitlines():
        if not linea or linea.lstrip().startswith('#') or '=' not in linea:
            continue
        clave, _, valor = linea.partition('=')
        valor = valor.strip().strip('"').strip("'")
        if len(valor) < 8:
            continue
        if any(parte in clave.upper() for parte in ('PASSWORD', 'TOKEN', 'SECRET')):
            valores.add(valor)
    return valores


def escanear(raiz=RAIZ, directorio_datos=None, archivos_env=None):
    raiz = Path(raiz)
    directorio_datos = Path(directorio_datos or raiz / 'seeds' / 'data')
    if archivos_env is None:
        archivos_env = [raiz / '.env.example']
        if (raiz / '.env').is_file():
            archivos_env.append(raiz / '.env')
    tokens = tokens_de_datos(directorio_datos) if directorio_datos.is_dir() else set()
    secretos = set()
    for archivo in archivos_env:
        secretos.update(secretos_de_env(Path(archivo)))
    hallazgos = []
    for dirpath, dirnames, filenames in os.walk(raiz):
        actual = Path(dirpath)
        dirnames[:] = [nombre for nombre in dirnames if nombre not in DIR_EXCLUIDOS]
        for nombre in filenames:
            ruta = actual / nombre
            if _excluida(raiz, ruta):
                continue
            if ruta.suffix.lower() not in EXTENSIONES and not nombre.startswith('.env'):
                continue
            try:
                texto = ruta.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            relativa = _relativa(raiz, ruta)
            for token in sorted(tokens):
                if token in texto:
                    hallazgos.append(Hallazgo(relativa, token))
            for secreto in secretos:
                if secreto in texto:
                    hallazgos.append(Hallazgo(relativa, 'valor secreto de .env'))
            # Las pruebas pueden usar una contraseña ficticia para un caso límite.
            # Un literal fuera de tests/ sí cuenta: es código que se ejecuta de verdad.
            if '/tests/' not in relativa and _PASSWORD.search(texto):
                hallazgos.append(Hallazgo(relativa, 'literal de password'))
    return hallazgos
