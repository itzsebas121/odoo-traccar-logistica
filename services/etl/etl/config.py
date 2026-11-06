"""Configuracion del ETL (variables de entorno). Los secretos no tienen valor por defecto."""
import os
from urllib.parse import urlsplit, urlunsplit

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql")
RO_ROLE = "dwh_ro"


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def env(name, default=None):
    """Variable no secreta (hosts, nombres de usuario, bases); admite valor por defecto."""
    return os.environ.get(name, default)


def require(name):
    """Variable obligatoria (secretos, DSN con contrasena): sin valor por defecto; vacia cuenta como faltante."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            "Falta la variable de entorno obligatoria %s. Definala en .env (vea .env.example)." % name)
    return value


def dwh_dsn():
    return require("DWH_DSN")


def admin_dsn():
    """DSN de la base 'postgres' (para crear la base del DWH)."""
    return env("DWH_ADMIN_DSN") or with_dbname(dwh_dsn(), "postgres")


def with_dbname(dsn, dbname):
    p = urlsplit(dsn)
    return urlunsplit((p.scheme, p.netloc, "/" + dbname, p.query, p.fragment))


def dbname_of(dsn):
    return urlsplit(dsn).path.lstrip("/")
