"""Historico simulado de viajes (procedencia = 'SIMULADO', spec 10.4). Determinista por semilla.

Cada vehiculo tiene una zona preferida por franja horaria (patron aprendible); con probabilidad
(1 - RUIDO) el destino es la zona preferida, si no, una zona al azar."""
import random
from datetime import datetime, timedelta, timezone

from . import load

VEHICULOS = [(-1, "SIM-001"), (-2, "SIM-002"), (-3, "SIM-003")]
ZONAS = ["centro", "ficoa", "huachi", "izamba", "atocha", "ingahurco", "otra"]
# vehiculo -> destino preferido por franja (manana, tarde, noche)
PREFERIDO = {
    "SIM-001": ["ficoa", "centro", "ingahurco"],
    "SIM-002": ["huachi", "atocha", "centro"],
    "SIM-003": ["izamba", "izamba", "otra"],
}
RUIDO = 0.2


def _franja(hora):
    return 0 if hora < 12 else (1 if hora < 18 else 2)


def generar(cur, lote_id, dias=30, seed=42, now=None):
    """Inserta recorridos simulados de los ultimos `dias` dias. Idempotente (fuente_id determinista)."""
    now = now or datetime.now(timezone.utc)
    hoy = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rng = random.Random(seed)
    zonas = load.load_zonas(cur)
    por_codigo = {z["codigo"]: z for z in zonas}
    n = 0
    for vid, placa in VEHICULOS:
        vsk = load.upsert_vehiculo(cur, vid, placa, None, "SIMULADO")
        for d in range(dias, 0, -1):
            dia = hoy - timedelta(days=d)
            t = dia + timedelta(hours=7, minutes=rng.randint(0, 40))
            origen = "centro"
            for _ in range(rng.randint(4, 8)):
                if t.hour >= 21:
                    break
                pref = PREFERIDO[placa][_franja(t.hour)]
                destino = pref if rng.random() > RUIDO else rng.choice(ZONAS)
                zo, zd = por_codigo[origen], por_codigo[destino]
                if zo["lat"] is None or zd["lat"] is None or origen == destino:
                    km = rng.uniform(2.0, 9.0)
                else:
                    km = load.haversine_km(zo["lat"], zo["lon"], zd["lat"], zd["lon"]) * 1.3
                minutos = max(5.0, km / 30.0 * 60.0)
                fin = t + timedelta(minutes=minutos)
                fid = "sim:%s:%s" % (placa, t.strftime("%Y%m%dT%H%M"))
                cur.execute(
                    """INSERT INTO dwh.fact_recorridos
                         (vehiculo_sk, conductor_sk, tiempo_inicio_sk, zona_origen_sk, zona_destino_sk, inicio_utc,
                          fin_utc, distancia_km, duracion_min, num_paradas, fuente_id, procedencia, lote_id)
                       VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,1,%s,'SIMULADO',%s)
                       ON CONFLICT (fuente_id, procedencia) DO NOTHING""",
                    (vsk, load.ensure_tiempo(cur, t), zo["sk"], zd["sk"], t, fin, round(km, 3), round(minutos, 2),
                     fid, lote_id))
                n += cur.rowcount
                origen = destino
                t = fin + timedelta(minutes=rng.randint(20, 90))
    return n
