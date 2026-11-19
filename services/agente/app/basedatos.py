"""Respaldos y restauración de las bases de datos (Odoo y Traccar) desde la interfaz del administrador.

Formatos:
- Odoo: ZIP igual al del gestor de bases de Odoo (dump.sql + filestore/ + manifest.json), así que los
  respaldos sirven también en otra instalación de Odoo 16 y se pueden cargar ZIPs hechos por Odoo.
  También se acepta un .dump de pg_dump (formato custom, solo base de datos, como los de scripts/backup.sh).
- Traccar: .dump de pg_dump (formato custom).

Restaurar nunca toca la base en uso hasta el final: se restaura en una base temporal, se comprueba y recién
entonces se intercambian los nombres. La base reemplazada queda como «<base>_anterior» (solo la última) y,
además, antes de restaurar se crea un respaldo automático. Si algo falla antes del intercambio, la base
actual queda intacta.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_logger = logging.getLogger('agente.basedatos')

NOMBRE_SEGURO = re.compile(r'^[a-z][a-z0-9_]{0,40}$')
ARCHIVO_VALIDO = re.compile(r'^(odoo|traccar)_[A-Za-z0-9_.-]{1,120}\.(zip|dump)$')
TIMEOUT_S = 60 * 60
MAGIA_PGDUMP = b'PGDMP'


class ErrorBD(RuntimeError):
    """Error de una operación de base de datos, con mensaje apto para el usuario."""


@dataclass(frozen=True)
class ConfigBD:
    host: str
    puerto: str
    usuario: str
    clave: str
    base_odoo: str
    base_traccar: str
    usuario_traccar: str
    dir_datos_odoo: Path
    dir_respaldos: Path

    @classmethod
    def desde_entorno(cls):
        config = cls(
            host=os.environ.get('PGHOST') or 'db',
            puerto=os.environ.get('PGPORT') or '5432',
            usuario=os.environ.get('PGUSER') or 'odoo',
            clave=os.environ.get('PGPASSWORD') or '',
            base_odoo=os.environ.get('ODOO_DB') or 'logistica_dev',
            base_traccar=os.environ.get('TRACCAR_DB_NAME') or 'traccar',
            usuario_traccar=os.environ.get('TRACCAR_DB_USER') or 'traccar',
            dir_datos_odoo=Path(os.environ.get('ODOO_DATA_DIR') or '/var/lib/odoo'),
            dir_respaldos=Path(os.environ.get('AGENTE_DIR_RESPALDOS') or '/respaldos'),
        )
        for nombre in (config.base_odoo, config.base_traccar, config.usuario_traccar, config.usuario):
            if not NOMBRE_SEGURO.match(nombre):
                raise RuntimeError(f'Nombre de base o usuario no admitido: {nombre!r}')
        return config

    @property
    def disponible(self):
        return bool(self.clave)

    def base(self, cual):
        return {'odoo': self.base_odoo, 'traccar': self.base_traccar}[cual]


# ------------------------------------------------------------------ comandos
def _entorno(config):
    return {**os.environ, 'PGHOST': config.host, 'PGPORT': config.puerto, 'PGUSER': config.usuario,
            'PGPASSWORD': config.clave}


def _ejecutar(config, args, descripcion, entrada=None):
    try:
        resultado = subprocess.run(args, env=_entorno(config), capture_output=True, timeout=TIMEOUT_S,
                                   input=entrada, check=False)
    except subprocess.TimeoutExpired:
        raise ErrorBD(f'{descripcion}: superó el tiempo máximo.') from None
    except FileNotFoundError:
        raise ErrorBD(f'{descripcion}: falta la herramienta {args[0]} en el servicio.') from None
    if resultado.returncode != 0:
        detalle = resultado.stderr.decode('utf-8', 'replace').strip().splitlines()[-3:]
        raise ErrorBD(f'{descripcion} falló: {" | ".join(detalle)[-400:]}')
    return resultado.stdout.decode('utf-8', 'replace')


def _sql(config, sql, base='postgres'):
    return _ejecutar(config, ['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-d', base, '-c', sql], 'Consulta SQL').strip()


def _existe(config, base):
    return _sql(config, f"SELECT 1 FROM pg_database WHERE datname = '{base}'") == '1'


def _sello():
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _filestore(config, base):
    return config.dir_datos_odoo / 'filestore' / base


def _tamano_dir(ruta):
    total = 0
    for raiz, _dirs, archivos in os.walk(ruta):
        for archivo in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, archivo))
            except OSError:
                pass
    return total


# ------------------------------------------------------------------ estado y archivos
def estado(config):
    bases = []
    for cual in ('odoo', 'traccar'):
        nombre = config.base(cual)
        try:
            tamano = _sql(config, f"SELECT pg_database_size('{nombre}')") if _existe(config, nombre) else ''
        except ErrorBD as exc:
            return {'disponible': False, 'error': str(exc), 'bases': [], 'respaldos': listar(config)}
        item = {'base': cual, 'nombre': nombre, 'existe': bool(tamano), 'tamano_bytes': int(tamano or 0),
                'anterior': _existe(config, f'{nombre}_anterior')}
        if cual == 'odoo':
            item['filestore_bytes'] = _tamano_dir(_filestore(config, nombre))
        bases.append(item)
    return {'disponible': True, 'bases': bases, 'respaldos': listar(config)}


def listar(config):
    if not config.dir_respaldos.is_dir():
        return []
    salida = []
    for archivo in config.dir_respaldos.iterdir():
        if archivo.is_file() and ARCHIVO_VALIDO.match(archivo.name):
            info = archivo.stat()
            salida.append({'nombre': archivo.name, 'base': archivo.name.split('_', 1)[0],
                           'tamano_bytes': info.st_size, 'creado': info.st_mtime,
                           'automatico': '_antes-de-restaurar' in archivo.name})
    return sorted(salida, key=lambda r: r['creado'], reverse=True)


def ruta_respaldo(config, nombre):
    """Ruta de un respaldo existente; ErrorBD si el nombre no es válido o no existe (sin salir del directorio)."""
    if not ARCHIVO_VALIDO.match(nombre or ''):
        raise ErrorBD('Nombre de respaldo no válido.')
    ruta = (config.dir_respaldos / nombre).resolve()
    if ruta.parent != config.dir_respaldos.resolve() or not ruta.is_file():
        raise ErrorBD('El respaldo no existe.')
    return ruta


def borrar(config, nombre):
    ruta_respaldo(config, nombre).unlink()


def nombre_para_subida(cual, nombre_original):
    extension = Path(nombre_original or '').suffix.lower()
    permitidas = {'odoo': ('.zip', '.dump'), 'traccar': ('.dump',)}[cual]
    if extension not in permitidas:
        raise ErrorBD(f'Para {cual} se admite {" o ".join(permitidas)}.')
    return f'{cual}_subido_{_sello()}{extension}'


# ------------------------------------------------------------------ respaldos
def respaldar(config, cual, etiqueta=''):
    config.dir_respaldos.mkdir(parents=True, exist_ok=True)
    base = config.base(cual)
    if not _existe(config, base):
        raise ErrorBD(f'La base {base} no existe.')
    sufijo = f'_{etiqueta}' if etiqueta else ''
    if cual == 'traccar':
        destino = config.dir_respaldos / f'traccar_{base}_{_sello()}{sufijo}.dump'
        parcial = destino.with_suffix('.parcial')
        try:
            _ejecutar(config, ['pg_dump', '--format=custom', '--no-owner', f'--file={parcial}', base], 'Respaldo de Traccar')
            parcial.rename(destino)
        finally:
            parcial.unlink(missing_ok=True)
        return destino
    return _respaldar_odoo(config, base, sufijo)


def _respaldar_odoo(config, base, sufijo):
    destino = config.dir_respaldos / f'odoo_{base}_{_sello()}{sufijo}.zip'
    parcial = destino.with_suffix('.parcial')
    with tempfile.TemporaryDirectory(prefix='respaldo_') as tmp:
        dump = Path(tmp) / 'dump.sql'
        _ejecutar(config, ['pg_dump', '--no-owner', f'--file={dump}', base], 'Respaldo de Odoo')
        modulos = _sql(config, "SELECT name || '=' || COALESCE(latest_version, '') FROM ir_module_module "
                               "WHERE state = 'installed' ORDER BY name", base=base)
        manifiesto = {
            'odoo_dump': '1', 'db_name': base, 'version': '16.0', 'major_version': '16.0',
            'pg_version': _sql(config, 'SHOW server_version'),
            'modules': dict(linea.split('=', 1) for linea in modulos.splitlines() if '=' in linea),
            'creado_por': 'Bitácora', 'creado': datetime.now().isoformat(timespec='seconds'),
        }
        try:
            with zipfile.ZipFile(parcial, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                z.writestr('manifest.json', json.dumps(manifiesto, indent=2))
                z.write(dump, 'dump.sql')
                filestore = _filestore(config, base)
                if filestore.is_dir():
                    for raiz, _dirs, archivos in os.walk(filestore):
                        for archivo in archivos:
                            completo = Path(raiz) / archivo
                            z.write(completo, Path('filestore') / completo.relative_to(filestore))
            parcial.rename(destino)
        finally:
            parcial.unlink(missing_ok=True)
    return destino


# ------------------------------------------------------------------ restauración
def tipo_archivo(ruta):
    """'zip_odoo' | 'pgdump' (formato custom). ErrorBD si no es un respaldo reconocible."""
    with open(ruta, 'rb') as f:
        cabecera = f.read(5)
    if cabecera == MAGIA_PGDUMP:
        return 'pgdump'
    if zipfile.is_zipfile(ruta):
        with zipfile.ZipFile(ruta) as z:
            if 'dump.sql' not in z.namelist():
                raise ErrorBD('El ZIP no es un respaldo de Odoo (falta dump.sql).')
        return 'zip_odoo'
    raise ErrorBD('El archivo no es un respaldo reconocido (ZIP de Odoo o .dump de pg_dump).')


def _extraer_filestore(z, destino):
    """Extrae filestore/ del ZIP a `destino`, rechazando rutas que salgan del directorio (zip slip)."""
    destino = destino.resolve()
    for miembro in z.infolist():
        if not miembro.filename.startswith('filestore/') or miembro.is_dir():
            continue
        relativo = miembro.filename[len('filestore/'):]
        objetivo = (destino / relativo).resolve()
        if not objetivo.is_relative_to(destino):
            raise ErrorBD('El ZIP contiene rutas no válidas.')
        objetivo.parent.mkdir(parents=True, exist_ok=True)
        with z.open(miembro) as origen, open(objetivo, 'wb') as salida:
            shutil.copyfileobj(origen, salida, 1024 * 1024)


def restaurar(config, cual, ruta, quien):
    """Restaura `ruta` en la base `cual`. Devuelve un resumen. El servicio que usa la base debe reiniciarse."""
    inicio = time.monotonic()
    base = config.base(cual)
    tipo = tipo_archivo(ruta)
    if cual == 'traccar' and tipo != 'pgdump':
        raise ErrorBD('Para Traccar se necesita un .dump de pg_dump.')
    temporal = f'{base}_restaurando'
    anterior = f'{base}_anterior'
    propietario = config.usuario if cual == 'odoo' else config.usuario_traccar
    _logger.warning('restauracion_inicio base=%s archivo=%s usuario=%s', base, ruta.name, quien)

    # 1) Respaldo automático de lo que hay ahora (si existe).
    respaldo_previo = respaldar(config, cual, etiqueta='antes-de-restaurar').name if _existe(config, base) else None

    # 2) Restaurar en una base temporal.
    filestore_temporal = _filestore(config, temporal)
    try:
        _sql(config, f'DROP DATABASE IF EXISTS "{temporal}" WITH (FORCE)')
        shutil.rmtree(filestore_temporal, ignore_errors=True)
        _sql(config, f'CREATE DATABASE "{temporal}" OWNER "{propietario}" TEMPLATE template0 ENCODING \'UTF8\'')
        if tipo == 'pgdump':
            _ejecutar(config, ['pg_restore', '--no-owner', f'--role={propietario}', '--exit-on-error',
                               '--single-transaction', '-d', temporal, str(ruta)], 'Restauración')
        else:
            with zipfile.ZipFile(ruta) as z, tempfile.TemporaryDirectory(prefix='restaurar_') as tmp:
                dump = Path(tmp) / 'dump.sql'
                with z.open('dump.sql') as origen, open(dump, 'wb') as salida:
                    shutil.copyfileobj(origen, salida, 1024 * 1024)
                _ejecutar(config, ['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '--single-transaction',
                                   '-d', temporal, '-f', str(dump)], 'Restauración')
                _extraer_filestore(z, filestore_temporal)
        _verificar(config, cual, temporal)
    except Exception:
        _sql(config, f'DROP DATABASE IF EXISTS "{temporal}" WITH (FORCE)')
        shutil.rmtree(filestore_temporal, ignore_errors=True)
        raise

    # 3) Intercambio: la base actual pasa a «_anterior» y la restaurada ocupa su nombre.
    if _existe(config, base):
        _sql(config, f'ALTER DATABASE "{base}" ALLOW_CONNECTIONS false')
        _sql(config, f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{base}'")
        _sql(config, f'DROP DATABASE IF EXISTS "{anterior}" WITH (FORCE)')
        _sql(config, f'ALTER DATABASE "{base}" RENAME TO "{anterior}"')
        _sql(config, f'ALTER DATABASE "{anterior}" ALLOW_CONNECTIONS true')
    _sql(config, f'ALTER DATABASE "{temporal}" RENAME TO "{base}"')
    if cual == 'odoo':
        actual, viejo = _filestore(config, base), _filestore(config, anterior)
        shutil.rmtree(viejo, ignore_errors=True)
        if actual.exists():
            actual.rename(viejo)
        if filestore_temporal.exists():
            filestore_temporal.rename(actual)
    segundos = round(time.monotonic() - inicio, 1)
    _logger.warning('restauracion_fin base=%s archivo=%s usuario=%s segundos=%s', base, ruta.name, quien, segundos)
    return {'base': cual, 'nombre': base, 'archivo': ruta.name, 'segundos': segundos,
            'respaldo_previo': respaldo_previo, 'base_anterior': anterior,
            'reiniciar': 'odoo' if cual == 'odoo' else 'traccar'}


def _verificar(config, cual, base):
    if cual == 'odoo':
        consulta = "SELECT count(*) FROM ir_module_module WHERE state = 'installed'"
        mensaje = 'El respaldo no contiene una base de Odoo válida (sin módulos instalados).'
    else:
        consulta = "SELECT count(*) FROM information_schema.tables WHERE table_name = 'tc_users'"
        mensaje = 'El respaldo no contiene una base de Traccar válida (falta tc_users).'
    try:
        if int(_sql(config, consulta, base=base) or 0) < 1:
            raise ErrorBD(mensaje)
    except ErrorBD as exc:
        if exc.args[0] == mensaje:
            raise
        raise ErrorBD(mensaje) from None
