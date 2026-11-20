"""Pronostico periodico en el SERVIDOR (servicio ml-programado): corre `mlsvc.demanda.predecir --source dwh` cada
ML_PREDECIR_MIN minutos (60 por defecto). No entrena nada: usa models/demanda.joblib (entrenado en local).

Cada ciclo es independiente: si el DWH aun no existe, no tiene ventas o falta una clave, lo registra y espera al
siguiente. No termina por un fallo, para no entrar en un bucle de reinicios del contenedor.

    python -m mlsvc.demanda.programado
"""
import os
import signal
import sys
import threading
from datetime import datetime, timezone


def log(mensaje, error=False):
    print("%s  %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"), mensaje),
          file=sys.stderr if error else sys.stdout, flush=True)


def intervalo_min():
    try:
        return max(1, int(os.environ.get("ML_PREDECIR_MIN") or 60))
    except ValueError:
        log("ML_PREDECIR_MIN no es un numero; se usan 60 min.", True)
        return 60


def ciclo(argv=None):
    from . import predecir
    try:
        return predecir.main(argv if argv is not None else ["--source", "dwh"])
    except SystemExit as exc:            # predecir avisa con SystemExit (sin modelo, versiones, hash)
        if exc.code not in (None, 0):
            log("predecir: %s" % exc.code, True)
        return 1 if exc.code not in (None, 0) else 0
    except Exception as exc:             # DWH sin crear, sin conexion, falta DWH_DB_PASSWORD...
        log("predecir fallo: %s: %s" % (type(exc).__name__, str(exc).splitlines()[0] if str(exc) else ""), True)
        return 1


def main():
    parar = threading.Event()
    for senal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(senal, lambda *_: parar.set())
    minutos = intervalo_min()
    log("Pronostico de demanda programado: una corrida cada %d min (sin entrenar)." % minutos)
    while not parar.is_set():
        ok = ciclo() == 0
        # Tras un despliegue nuevo el ETL tarda en crear y llenar el DWH: si fallo, se reintenta antes.
        parar.wait((minutos if ok else min(minutos, 10)) * 60)
    log("Programador detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
