"""Programador: corre el ETL a horas fijas (ETL_HORARIO, hora local ETL_TZ) dentro de un contenedor de larga duracion.
Por defecto a las 03:00 y a las 12:00, y ademas una vez al arrancar (un despliegue nuevo no espera al horario).

Cada ciclo es independiente: un error (configuracion incompleta, fuente caida, base sin crear) se registra y el
programador espera al siguiente ciclo. No termina por un fallo, para no entrar en un bucle de reinicios."""
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, db


def log(mensaje, error=False):
    print("%s  %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"), mensaje),
          file=sys.stderr if error else sys.stdout, flush=True)


def decidir_modo(stg_conn, horas, now=None):
    """'full' si nunca hubo una corrida completa correcta o la ultima tiene mas de `horas`; si no, 'incremental'.
    La corrida completa vuelve a leer todo y es la que detecta registros borrados en Odoo."""
    now = now or datetime.now(timezone.utc)
    with stg_conn.cursor() as cur:
        cur.execute("SELECT max(fin_utc) FROM lote WHERE modo='full' AND estado='ok'")
        ultima = cur.fetchone()[0]
    stg_conn.rollback()
    return "full" if ultima is None or now - ultima > timedelta(hours=horas) else "incremental"


def proxima(ahora, horas):
    """Siguiente momento del horario estrictamente posterior a `ahora` (datetime con zona horaria)."""
    candidatos = [(ahora + timedelta(days=d)).replace(hour=h, minute=m, second=0, microsecond=0)
                  for d in (0, 1) for h, m in horas]
    return min(c for c in candidatos if c > ahora)


def espera_hasta_horario(horas, tz, registrar=log, reloj=None):
    """Funcion para `bucle`: segundos hasta la siguiente hora del horario (y lo anota en el registro)."""
    def segundos():
        ahora = reloj() if reloj else datetime.now(ZoneInfo(tz))
        sig = proxima(ahora, horas)
        registrar("Proxima corrida: %s" % sig.strftime("%Y-%m-%d %H:%M %Z"))
        return max(1.0, (sig - ahora).total_seconds())
    return segundos


def bucle(ciclo, intervalo_s, parar, registrar=log):
    """Ejecuta `ciclo()` y espera `intervalo_s` segundos (o lo que devuelva, si es una funcion), hasta que `parar`
    (threading.Event) se active. Devuelve cuantos ciclos corrio."""
    corridos = 0
    while not parar.is_set():
        try:
            registrar(ciclo())
        except config.ConfigError as exc:
            registrar("Configuracion incompleta, no se ejecuta: %s" % exc, True)
        except db.Ocupado as exc:
            registrar(str(exc))
        except Exception as exc:
            registrar("La corrida fallo: %s: %s" % (type(exc).__name__, exc), True)
        corridos += 1
        parar.wait(intervalo_s() if callable(intervalo_s) else intervalo_s)
    return corridos


def run(ciclo):
    """Punto de entrada de `etl schedule`: corre hasta recibir SIGTERM o SIGINT."""
    parar = threading.Event()
    for senal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(senal, lambda *_: parar.set())
    horas, tz = config.horario(), config.zona_horaria()
    log("Programador del ETL: corridas a las %s (%s), y una ahora al arrancar; completa si la ultima tiene mas de "
        "%d h." % (", ".join("%02d:%02d" % hm for hm in horas), tz, config.horas_entre_completas()))
    bucle(ciclo, espera_hasta_horario(horas, tz), parar)
    log("Programador detenido.")
    return 0
