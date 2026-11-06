"""Configuracion del ETL (variables de entorno). Los secretos no tienen valor por defecto.

Una base por componente (sin esquemas):
  - staging: base STAGING_DB (logistica_staging), usuario STAGING_USER (etl_stg), clave ETL_STG_PASSWORD.
  - DWH:     base DWH_DB (logistica_dwh), usuario DWH_ETL_USER (dwh_etl), clave DWH_ETL_PASSWORD.
Las conexiones se arman por partes (host, puerto, base, usuario, clave); solo `bootstrap` usa un DSN
completo (DWH_ADMIN_DSN, usuario administrador del servidor)."""
import os

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql")
RO_ROLE = "dwh_ro"


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def env(name, default=None):
    """Variable no secreta (hosts, nombres de usuario, bases); admite valor por defecto."""
    return os.environ.get(name, default)


def require(name):
    """Variable obligatoria (secretos): sin valor por defecto; vacia cuenta como faltante."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            "Falta la variable de entorno obligatoria %s. Definala en .env (vea .env.example)." % name)
    return value


def staging_db():
    return env("STAGING_DB", "logistica_staging")


def dwh_db():
    return env("DWH_DB", "logistica_dwh")


def staging_user():
    return env("STAGING_USER", "etl_stg")


def dwh_user():
    return env("DWH_ETL_USER", "dwh_etl")


def _params(dbname, user, password_var):
    return dict(host=env("DB_HOST", "db"), port=env("DB_PORT", "5432"), dbname=dbname, user=user,
                password=require(password_var))


def staging_params():
    """Argumentos de psycopg2.connect para la base de staging."""
    return _params(staging_db(), staging_user(), "ETL_STG_PASSWORD")


def dwh_params():
    """Argumentos de psycopg2.connect para la base del DWH."""
    return _params(dwh_db(), dwh_user(), "DWH_ETL_PASSWORD")


def admin_dsn():
    """DSN del administrador del servidor (solo bootstrap: crea bases y roles)."""
    return require("DWH_ADMIN_DSN")
