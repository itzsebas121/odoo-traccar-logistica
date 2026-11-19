"""Vinculos verificables entre Odoo y Traccar dentro del DWH (spec 10.2): recorrido-ruta y entrega-recorrido.

Siempre exigen el mismo vehiculo (con dispositivo GPS) y el periodo de la ruta; nunca se vincula por cercania."""
from datetime import timedelta

# Viaje de llegada: el cierre de una entrega puede caer en la parada que sigue al viaje (Traccar corta el viaje
# cuando el vehiculo queda detenido mas de su `minimalParkingDuration`, 5 min por defecto). Se acepta el viaje
# que termino como mucho esto antes del cierre.
VINCULO_TOLERANCIA_MIN = 30
# Una ruta abierta (sin fin) cubre como mucho estas horas desde su inicio: una ruta que nadie cerro no se queda con
# los viajes de las noches o los dias siguientes. Es el mismo limite que usa el monitoreo de Odoo.
MAX_RUTA_ABIERTA_H = 12


def fin_ventana(alias, ahora="%(now)s"):
    """Fin de la ventana de una ruta en SQL: su fin real o, si sigue abierta, `ahora` con el tope de 12 h."""
    return ("COALESCE({a}.fin_utc, LEAST({n}, {a}.inicio_utc + interval '{h} hours'))"
            .format(a=alias, n=ahora, h=MAX_RUTA_ABIERTA_H))


def asignar_rutas_recorridos(cur, now, conductor_de_vehiculo):
    """Cada recorrido REAL recibe la ruta de despacho de su vehiculo cuyo periodo (inicio..fin; una ruta abierta
    llega hasta `now`, como mucho MAX_RUTA_ABIERTA_H horas) se solapa con el viaje; si varias, la de mayor solape.
    Sin solape, queda sin ruta.
    El conductor del recorrido es el de esa ruta (quien iba en el vehiculo). Si no hay ruta o no tiene conductor,
    se conserva el que ya tenia (el del vehiculo cuando se cargo el viaje): el historico no se reescribe cuando el
    vehiculo cambia de conductor. Solo un recorrido sin conductor toma el actual del vehiculo
    (`conductor_de_vehiculo`: {vehiculo_sk: conductor_sk})."""
    vehiculos = [int(v) for v in conductor_de_vehiculo]
    conductores = [conductor_de_vehiculo[v] for v in conductor_de_vehiculo]
    cur.execute(
        """WITH cv AS (SELECT * FROM unnest(%(vs)s::int[], %(cs)s::int[]) AS t(vsk, csk)),
           asig AS (
             SELECT r.sk, (
               SELECT w.ruta_id_odoo FROM fact_rutas w
               WHERE w.vehiculo_sk = r.vehiculo_sk AND w.inicio_utc IS NOT NULL
                 AND r.inicio_utc <= {FIN_W} AND r.fin_utc >= w.inicio_utc
               ORDER BY LEAST(r.fin_utc, {FIN_W}) - GREATEST(r.inicio_utc, w.inicio_utc) DESC,
                        w.inicio_utc DESC
               LIMIT 1) AS ruta
             FROM fact_recorridos r WHERE r.procedencia = 'REAL')
           UPDATE fact_recorridos r
           SET ruta_id_odoo = a.ruta,
               conductor_sk = COALESCE((SELECT w.conductor_sk FROM fact_rutas w WHERE w.ruta_id_odoo = a.ruta),
                                       r.conductor_sk,
                                       (SELECT cv.csk FROM cv WHERE cv.vsk = r.vehiculo_sk))
           FROM asig a WHERE a.sk = r.sk""".replace("{FIN_W}", fin_ventana("w")),
        {"vs": vehiculos, "cs": conductores, "now": now})


def link_entregas_recorridos(cur, now, tolerancia_min=VINCULO_TOLERANCIA_MIN):
    """Una entrega se vincula a un recorrido de Traccar cuando coinciden
    (1) el vehiculo, que tiene dispositivo GPS;
    (2) el periodo de la ruta: el recorrido se solapa con inicio..fin de la ruta de la entrega (ruta abierta =
        hasta `now`, como mucho MAX_RUTA_ABIERTA_H horas); y
    (3) el cierre de la entrega cae dentro del recorrido, o, si no hay ninguno asi, el recorrido es el de llegada:
        termino antes del cierre y como mucho `tolerancia_min` minutos antes.
    En cualquier otro caso recorrido_sk queda NULL (tambien si un vinculo anterior dejo de cumplirse)."""
    cur.execute(
        """UPDATE fact_entregas f SET recorrido_sk = COALESCE(
             (SELECT r.sk FROM fact_recorridos r
              JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk AND v.traccar_device_id IS NOT NULL
              JOIN fact_rutas w ON w.ruta_id_odoo = f.ruta_id_odoo AND w.inicio_utc IS NOT NULL
              WHERE r.vehiculo_sk = f.vehiculo_sk AND r.procedencia = 'REAL'
                AND f.completado_utc BETWEEN r.inicio_utc AND r.fin_utc
                AND r.inicio_utc <= {FIN_W} AND r.fin_utc >= w.inicio_utc
              ORDER BY r.inicio_utc DESC LIMIT 1),
             (SELECT r.sk FROM fact_recorridos r
              JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk AND v.traccar_device_id IS NOT NULL
              JOIN fact_rutas w ON w.ruta_id_odoo = f.ruta_id_odoo AND w.inicio_utc IS NOT NULL
              WHERE r.vehiculo_sk = f.vehiculo_sk AND r.procedencia = 'REAL'
                AND r.fin_utc <= f.completado_utc AND r.fin_utc >= f.completado_utc - %(tol)s
                AND r.inicio_utc <= {FIN_W} AND r.fin_utc >= w.inicio_utc
              ORDER BY r.fin_utc DESC LIMIT 1))
           """.replace("{FIN_W}", fin_ventana("w")), {"now": now, "tol": timedelta(minutes=tolerancia_min)})
