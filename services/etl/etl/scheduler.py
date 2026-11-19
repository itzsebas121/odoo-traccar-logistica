"""Programador: corre el ETL cada cierto intervalo dentro de un contenedor de larga duracion.

Cada ciclo es independiente: un error (configuracion incompleta, fuente caida, base sin crear) se registra y el
programador espera al siguiente ciclo. No termina por un fallo, para no entrar en un bucle de reinicios."""
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone

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


def bucle(ciclo, intervalo_s, parar, registrar=log):
    """Ejecuta `ciclo()` y espera `intervalo_s` segundos, hasta que `parar` (threading.Event) se active.
    Devuelve cuantos ciclos corrio."""
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
        parar.wait(intervalo_s)
    return corridos


def run(ciclo):
    """Punto de entrada de `etl schedule`: corre hasta recibir SIGTERM o SIGINT."""
    parar = threading.Event()
    for senal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(senal, lambda *_: parar.set())
    intervalo = config.intervalo_min()
    log("Programador del ETL: una corrida cada %d min (completa cada %d h)." % (
        intervalo, config.horas_entre_completas()))
    bucle(ciclo, intervalo * 60, parar)
    log("Programador detenido.")
    return 0
