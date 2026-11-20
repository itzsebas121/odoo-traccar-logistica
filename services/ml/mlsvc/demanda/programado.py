"""Pronostico de demanda en el SERVIDOR (servicio ml-programado), detras de cada corrida del ETL. No entrena nada:
usa models/demanda.joblib (entrenado en local) y corre `mlsvc.demanda.predecir --source dwh`.

Cada ML_REVISAR_MIN minutos (5 por defecto) mira en el DWH la ultima corrida correcta del ETL (etl_ejecucion).
Recalcula el pronostico cuando hay una corrida nueva (03:00, 12:00 o al desplegar) o cuando cambia el dia local
(el pronostico empieza siempre hoy). Si el DWH todavia no existe o no tiene ventas, lo registra una vez y vuelve a
mirar en la siguiente revision: tras un despliegue, el pronostico aparece minutos despues de la primera carga.
No termina por un fallo, para no entrar en un bucle de reinicios del contenedor.

    python -m mlsvc.demanda.programado
"""
import os
import signal
import sys
import threading
from contextlib import closing
from datetime import datetime, timezone


def log(mensaje, error=False):
    print("%s  %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"), mensaje),
          file=sys.stderr if error else sys.stdout, flush=True)


def revisar_min():
    try:
        return max(1, int(os.environ.get("ML_REVISAR_MIN") or 5))
    except ValueError:
        log("ML_REVISAR_MIN no es un numero; se usan 5 min.", True)
        return 5


def ultima_etl():
    """Fin (UTC) de la ultima corrida correcta del ETL, o None si aun no hubo ninguna."""
    from . import datos
    with closing(datos.conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT max(fin_utc) FROM etl_ejecucion WHERE estado = 'ok' AND modo <> 'simulate'")
        return cur.fetchone()[0]


def dia_local():
    from .predecir import hoy_local
    return hoy_local().date()


def ciclo(argv=None):
    """0 = pronostico nuevo guardado; 3 = el DWH aun no tiene ventas; 1 = fallo (se registra)."""
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


class Seguimiento:
    """Decide cuando recalcular: una vez por cada (ultima corrida del ETL, dia local) distinta."""

    def __init__(self, marca=ultima_etl, dia=dia_local, correr=ciclo, registrar=log):
        self.marca, self.dia, self.correr, self.registrar = marca, dia, correr, registrar
        self.hecho, self.ultimo_aviso = None, None

    def _avisar(self, mensaje):
        if mensaje != self.ultimo_aviso:         # el mismo aviso no se repite cada 5 minutos
            self.registrar(mensaje, True)
            self.ultimo_aviso = mensaje

    def revisar(self):
        """Una revision. Devuelve True si se guardo un pronostico nuevo."""
        try:
            marca = self.marca()
        except Exception as exc:
            self._avisar("DWH no disponible todavia (%s: %s); se reintenta." % (
                type(exc).__name__, str(exc).splitlines()[0] if str(exc) else ""))
            return False
        if marca is None:
            self._avisar("El ETL aun no termino ninguna corrida; se espera a la primera carga.")
            return False
        clave = (marca, self.dia())
        if clave == self.hecho:
            return False
        self.registrar("Corrida del ETL de %s: se recalcula el pronostico." % marca)
        resultado = self.correr()
        if resultado == 0:
            self.hecho, self.ultimo_aviso = clave, None
            return True
        return False


def main():
    parar = threading.Event()
    for senal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(senal, lambda *_: parar.set())
    minutos = revisar_min()
    log("Pronostico de demanda detras del ETL: revisa cada %d min (sin entrenar)." % minutos)
    seguimiento = Seguimiento()
    while not parar.is_set():
        seguimiento.revisar()
        parar.wait(minutos * 60)
    log("Programador detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
