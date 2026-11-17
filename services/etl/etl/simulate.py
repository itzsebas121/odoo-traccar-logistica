"""Historico simulado de viajes (procedencia = 'SIMULADO', spec 10.4). Determinista por semilla.

Cada vehiculo tiene una zona preferida por franja horaria (patron aprendible); con probabilidad
(1 - RUIDO) el destino es la zona preferida, si no, una zona al azar.

La jornada y las franjas son de hora LOCAL (zona `tz`, ETL_TZ): asi las ve el ML y dim_tiempo. Al DWH se guarda
en UTC, como todo lo demas."""
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .load import dimensions
from .transform import normalize as n
from .transform.zonas import CODIGOS_CONTRATO

VEHICULOS = [(-1, "SIM-001"), (-2, "SIM-002"), (-3, "SIM-003")]
# vehiculo -> destino preferido por franja (manana, tarde, noche)
PREFERIDO = {
    "SIM-001": ["ficoa", "centro", "ingahurco"],
    "SIM-002": ["huachi", "atocha", "centro"],
    "SIM-003": ["izamba", "izamba", "otra"],
}
RUIDO = 0.2
INICIO_JORNADA_H = 7     # hora local del primer viaje del dia
FIN_JORNADA_H = 21       # no empieza ningun viaje a partir de esta hora local
VELOCIDAD_KMH = 30.0
FACTOR_VIA = 1.3   # la distancia por carretera se estima como linea recta x 1,3


def _franja(hora):
    return 0 if hora < 12 else (1 if hora < 18 else 2)


def generar(cur, lote_id, dias=30, seed=42, now=None, tz="UTC"):
    """Inserta en el DWH (cursor de la base logistica_dwh) los recorridos simulados de los ultimos `dias` dias.
    `lote_id` es el lote registrado en staging. Devuelve cuantos inserto.

    Idempotente y estable por dia: cada (semilla, vehiculo, dia local) tiene su propio generador aleatorio, asi que
    un dia de calendario sale igual sea cual sea `dias` o el dia en que se corre. Dentro de los dias que regenera,
    quita los viajes SIMULADO que ya no corresponden (otra semilla, versiones anteriores)."""
    now = now or datetime.now(timezone.utc)
    zona = ZoneInfo(tz)
    hoy = now.astimezone(zona).replace(hour=0, minute=0, second=0, microsecond=0)     # medianoche local
    # Version anterior: generaba la jornada en UTC (horas locales desplazadas) con fuente_id sin 'Z'. Se quitan
    # para no mezclar los dos patrones; ningun hecho real referencia recorridos SIMULADO.
    cur.execute("DELETE FROM fact_recorridos WHERE procedencia='SIMULADO' AND fuente_id LIKE %s "
                "AND fuente_id NOT LIKE %s", ("sim:%", "%Z"))
    dimensions.asegurar_zonas_contrato(cur)
    ctx = dimensions.Contexto(lote_id, now, tz)
    por_codigo = {z["codigo"]: z for z in dimensions.leer_zonas(cur)}
    insertados, generados, vehiculos = 0, [], []
    for vid, placa in VEHICULOS:
        vsk = dimensions.upsert_vehiculo_simulado(cur, vid, placa)
        vehiculos.append(vsk)
        for d in range(dias, 0, -1):
            # fecha de calendario local (sin aritmetica de husos: el dia d se arma en hora local)
            dia = (hoy - timedelta(days=d)).replace(tzinfo=None)
            rng = random.Random("%s:%s:%s" % (seed, placa, dia.strftime("%Y%m%d")))
            t = (dia + timedelta(hours=INICIO_JORNADA_H, minutes=rng.randint(0, 40))).replace(tzinfo=zona)
            origen = "centro"
            for _ in range(rng.randint(4, 8)):
                if t.hour >= FIN_JORNADA_H or t.date() != dia.date():
                    break
                pref = PREFERIDO[placa][_franja(t.hour)]
                destino = pref if rng.random() > RUIDO else rng.choice(CODIGOS_CONTRATO)
                zo, zd = por_codigo[origen], por_codigo[destino]
                if zo["lat"] is None or zd["lat"] is None or origen == destino:
                    km = rng.uniform(2.0, 9.0)
                else:
                    km = n.haversine_km(zo["lat"], zo["lon"], zd["lat"], zd["lon"]) * FACTOR_VIA
                minutos = max(5.0, km / VELOCIDAD_KMH * 60.0)
                fin = t + timedelta(minutes=minutos)
                fid = "sim:%s:%s" % (placa, t.astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ"))
                cur.execute(
                    """INSERT INTO fact_recorridos
                         (vehiculo_sk, conductor_sk, tiempo_inicio_sk, zona_origen_sk, zona_destino_sk, inicio_utc,
                          fin_utc, distancia_km, duracion_min, num_paradas, velocidad_media_kmh, fuente_id,
                          procedencia, lote_id)
                       VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,'SIMULADO',%s)
                       ON CONFLICT (fuente_id, procedencia) DO UPDATE SET
                         vehiculo_sk=EXCLUDED.vehiculo_sk, tiempo_inicio_sk=EXCLUDED.tiempo_inicio_sk,
                         zona_origen_sk=EXCLUDED.zona_origen_sk, zona_destino_sk=EXCLUDED.zona_destino_sk,
                         inicio_utc=EXCLUDED.inicio_utc, fin_utc=EXCLUDED.fin_utc, distancia_km=EXCLUDED.distancia_km,
                         duracion_min=EXCLUDED.duracion_min, velocidad_media_kmh=EXCLUDED.velocidad_media_kmh,
                         lote_id=EXCLUDED.lote_id
                       WHERE (fact_recorridos.vehiculo_sk, fact_recorridos.zona_origen_sk,
                              fact_recorridos.zona_destino_sk, fact_recorridos.inicio_utc, fact_recorridos.fin_utc,
                              fact_recorridos.distancia_km)
                             IS DISTINCT FROM (EXCLUDED.vehiculo_sk, EXCLUDED.zona_origen_sk, EXCLUDED.zona_destino_sk,
                                               EXCLUDED.inicio_utc, EXCLUDED.fin_utc, EXCLUDED.distancia_km)""",
                    (vsk, dimensions.ensure_tiempo(cur, ctx, t), zo["sk"], zd["sk"], t.astimezone(timezone.utc),
                     fin.astimezone(timezone.utc), round(km, 3),
                     round(minutos, 2), round(km / (minutos / 60.0), 2), fid, lote_id))
                insertados += cur.rowcount
                generados.append(fid)
                origen = destino
                t = fin + timedelta(minutes=rng.randint(20, 90))
    if dias > 0:
        desde = (hoy - timedelta(days=dias)).astimezone(timezone.utc)
        hasta = hoy.astimezone(timezone.utc)
        cur.execute("""DELETE FROM fact_recorridos WHERE procedencia='SIMULADO' AND vehiculo_sk = ANY(%s)
                       AND inicio_utc >= %s AND inicio_utc < %s AND fuente_id <> ALL(%s)""",
                    (vehiculos, desde, hasta, generados))
    return insertados
