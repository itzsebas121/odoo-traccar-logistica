"""Configuracion del ETL (variables de entorno). Los secretos no tienen valor por defecto.

Una base por componente (sin esquemas):
  - staging: base STAGING_DB (logistica_staging), usuario STAGING_USER (etl_stg), clave ETL_STG_PASSWORD.
  - DWH:     base DWH_DB (logistica_dwh), usuario DWH_ETL_USER (dwh_etl), clave DWH_ETL_PASSWORD.
Las conexiones se arman por partes (host, puerto, base, usuario, clave); solo `bootstrap` usa un DSN
completo (DWH_ADMIN_DSN, usuario administrador del servidor)."""
import os

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql")
RO_ROLE = "dwh_ro"
# Rol del servicio ML: lee todo el DWH y escribe solo sus tablas de resultados (ml_*).
ML_ROLE = "dwh_ml"


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria o tiene un valor invalido."""


def env(name, default=None):
    """Variable no secreta (hosts, nombres de usuario, bases); admite valor por defecto. Vacia = por defecto."""
    return os.environ.get(name) or default


def require(name):
    """Variable obligatoria (secretos): sin valor por defecto; vacia cuenta como faltante."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            "Falta la variable de entorno obligatoria %s. Definala en .env (vea .env.example)." % name)
    return value


def entero(name, default, minimo=0):
    """Variable numerica no secreta. Un valor no entero o menor que `minimo` es un error de configuracion."""
    crudo = env(name)
    if crudo is None:
        return default
    try:
        valor = int(crudo)
    except ValueError:
        raise ConfigError("%s debe ser un numero entero (valor actual: %r)." % (name, crudo))
    if valor < minimo:
        raise ConfigError("%s debe ser mayor o igual que %d (valor actual: %d)." % (name, minimo, valor))
    return valor


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


def zona_horaria():
    """Zona horaria de la operacion: solo para las columnas *_local de dim_tiempo y la fecha de despacho."""
    return env("ETL_TZ", "America/Guayaquil")


def intervalo_min():
    """Minutos entre corridas del programador."""
    return entero("ETL_INTERVAL_MIN", 15, minimo=1)


def horas_entre_completas():
    """El programador hace una corrida completa cuando la ultima tiene mas de estas horas (detecta borrados)."""
    return entero("ETL_FULL_HOURS", 24, minimo=1)


def dias_retencion():
    """Dias que se conserva el crudo de staging. 0 = no se borra nada."""
    return entero("ETL_RETENTION_DAYS", 30, minimo=0)


def dias_ventana_traccar():
    """Dias hacia atras de la primera extraccion de Traccar (cuando no hay marca de agua)."""
    return entero("ETL_TRACCAR_DAYS", 30, minimo=1)
