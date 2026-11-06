"""Carga: extrae a staging, lee el crudo de staging en Python y escribe en el DWH (spec 10.2).

Dos conexiones independientes (sin SQL entre bases): `stg_conn` (base de staging: crudo, lotes, marcas de
agua, rechazados) y `dwh_conn` (base del DWH: dimensiones y hechos)."""
import math
from datetime import datetime, timedelta, timezone

from . import quality as q
from . import staging, watermark
from .odoo_extract import INCREMENTAL, MODELS

ESTADO_RESULTADO = {
    "entregado": "entregado",
    "no_entregado": "no_entregado",
    "pendiente_reprogramacion": "no_entregado",
    "devuelto_bodega": "no_entregado",
}
OTRA_KM = 4.0  # fuera de este radio de todo centroide -> zona 'otra'


# ---------------------------------------------------------------- utilidades
def _id(v):
    """Many2one XML-RPC [id, nombre] | id | False -> int | None."""
    if isinstance(v, (list, tuple)):
        return int(v[0]) if v else None
    if v in (None, False, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _name(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else None


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def load_zonas(cur):
    cur.execute("SELECT sk, codigo, latitud, longitud FROM dim_zona")
    return [dict(sk=r[0], codigo=r[1], lat=r[2], lon=r[3]) for r in cur.fetchall()]


def nearest_zone_sk(zonas, lat, lon):
    if lat is None or lon is None or not q.coords_valid(lat, lon):
        return None
    best, best_d = None, None
    for z in zonas:
        if z["lat"] is None:
            continue
        d = haversine_km(float(lat), float(lon), z["lat"], z["lon"])
        if best_d is None or d < best_d:
            best, best_d = z, d
    if best is None or best_d > OTRA_KM:
        return next((z["sk"] for z in zonas if z["codigo"] == "otra"), None)
    return best["sk"]


def ensure_tiempo(cur, dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    sk = int(dt.strftime("%Y%m%d%H"))
    cur.execute(
        """INSERT INTO dim_tiempo (sk, fecha, anio, mes, dia, dia_semana, hora)
           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (sk) DO NOTHING""",
        (sk, dt.date(), dt.year, dt.month, dt.day, dt.isoweekday(), dt.hour))
    return sk


def _max(a, b):
    return b if a is None or (b is not None and b > a) else a


# ---------------------------------------------------------------- dimensiones (DWH)
def upsert_conductor(cur, cid, nombre):
    if cid is None:
        return None
    cur.execute(
        """INSERT INTO dim_conductor (conductor_id_odoo, nombre) VALUES (%s,%s)
           ON CONFLICT (conductor_id_odoo) DO UPDATE SET nombre = COALESCE(EXCLUDED.nombre, dim_conductor.nombre)
           RETURNING sk""", (cid, nombre))
    return cur.fetchone()[0]


def upsert_vehiculo(cur, vid, placa, device_id, procedencia="REAL"):
    cur.execute(
        """INSERT INTO dim_vehiculo (vehiculo_id_odoo, placa, traccar_device_id, procedencia)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (vehiculo_id_odoo) DO UPDATE
           SET placa = COALESCE(EXCLUDED.placa, dim_vehiculo.placa),
               traccar_device_id = COALESCE(EXCLUDED.traccar_device_id, dim_vehiculo.traccar_device_id)
           RETURNING sk""", (vid, placa, device_id, procedencia))
    return cur.fetchone()[0]


def _sk_map(cur, table, keycol):
    cur.execute("SELECT %s, sk FROM %s" % (keycol, table))
    return dict(cur.fetchall())


def load_dimensions(cur, odoo, traccar, conductor_de_vehiculo):
    for p in odoo.get("res.partner") or []:
        upsert_conductor(cur, p["id"], p.get("name"))
    for v in odoo.get("fleet.vehicle") or []:
        placa = v.get("license_plate") or v.get("name") or None
        upsert_vehiculo(cur, v["id"], placa, _id(v.get("traccar_device_id")))
        cid = _id(v.get("driver_id"))
        if cid is not None:
            upsert_conductor(cur, cid, _name(v.get("driver_id")))
            conductor_de_vehiculo[v["id"]] = cid
    for r in odoo.get("logistica.ruta") or []:
        cid = _id(r.get("driver_id"))
        if cid is not None:
            upsert_conductor(cur, cid, _name(r.get("driver_id")))
    # Respaldo: dispositivo Traccar cuyo nombre coincide con la placa de un vehiculo sin device asignado
    for d in (traccar or {}).get("devices") or []:
        cur.execute(
            """UPDATE dim_vehiculo SET traccar_device_id=%s
               WHERE traccar_device_id IS NULL AND procedencia='REAL' AND upper(placa)=upper(%s)""",
            (d["id"], d.get("name")))


# ---------------------------------------------------------------- Traccar -> hechos
def _norm_position(p):
    return dict(
        id=p.get("id"), device=p.get("deviceId"), time=q.parse_ts(p.get("fixTime") or p.get("deviceTime")),
        lat=p.get("latitude"), lon=p.get("longitude"),
        speed_kmh=q.knots_to_kmh(p["speed"]) if p.get("speed") is not None else None)


def _norm_trip(t):
    return dict(
        device=t.get("deviceId"), inicio=q.parse_ts(t.get("startTime")), fin=q.parse_ts(t.get("endTime")),
        lat_ini=t.get("startLat"), lon_ini=t.get("startLon"), lat_fin=t.get("endLat"), lon_fin=t.get("endLon"),
        distancia_km=q.meters_to_km(t["distance"]) if t.get("distance") is not None else None,
        avg_kmh=q.knots_to_kmh(t["averageSpeed"]) if t.get("averageSpeed") is not None else None,
        max_kmh=q.knots_to_kmh(t["maxSpeed"]) if t.get("maxSpeed") is not None else None)


def load_traccar(dcur, scur, lote_id, traccar, conductor_de_vehiculo, counts):
    """Carga posiciones y recorridos en el DWH (`dcur`); los rechazos van a staging (`scur`).
    Devuelve la marca de agua (max tiempo cargado/visto)."""
    mark = None
    if not traccar:
        return mark
    zonas = load_zonas(dcur)
    dcur.execute("SELECT traccar_device_id, sk, vehiculo_id_odoo FROM dim_vehiculo "
                 "WHERE traccar_device_id IS NOT NULL AND procedencia='REAL'")
    dev = {r[0]: (r[1], r[2]) for r in dcur.fetchall()}

    # posiciones
    raw = traccar.get("positions") or []
    for p in q.dedupe([_norm_position(x) for x in raw],
                      key=lambda x: (x["device"], x["id"] if x["id"] is not None else x["time"])):
        fid = "pos:%s:%s" % (p["device"], p["id"] if p["id"] is not None else p["time"].isoformat() if p["time"] else "?")
        motivo = q.check_position(p)
        mark = _max(mark, p["time"])
        if motivo is None and p["device"] not in dev:
            motivo = "dispositivo_sin_vehiculo"
        if motivo:
            staging.reject(scur, lote_id, "posicion", fid, motivo, p)
            counts["rechazados"] += 1
            continue
        dcur.execute(
            """INSERT INTO fact_posicion_gps (vehiculo_sk, tiempo_sk, gps_time_utc, latitud, longitud,
                                              velocidad_kmh, fuente_id, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fuente_id) DO NOTHING""",
            (dev[p["device"]][0], ensure_tiempo(dcur, p["time"]), p["time"], p["lat"], p["lon"],
             p["speed_kmh"], fid, lote_id))
        counts["posiciones"] += 1

    # recorridos
    stops = [(s.get("deviceId"), q.parse_ts(s.get("startTime"))) for s in traccar.get("stops") or []]
    trips = [_norm_trip(x) for x in traccar.get("trips") or []]
    for t in q.dedupe(trips, key=lambda x: (x["device"], x["inicio"])):
        fid = "trip:%s:%s" % (t["device"], t["inicio"].isoformat() if t["inicio"] else "?")
        motivo = q.check_trip(t)
        mark = _max(mark, t["fin"])
        if motivo is None and t["device"] not in dev:
            motivo = "dispositivo_sin_vehiculo"
        if motivo:
            staging.reject(scur, lote_id, "recorrido", fid, motivo, t)
            counts["rechazados"] += 1
            continue
        vsk, vodoo = dev[t["device"]]
        nstops = sum(1 for d, st in stops if d == t["device"] and st and t["inicio"] <= st <= t["fin"])
        csk = None
        if conductor_de_vehiculo.get(vodoo) is not None:
            dcur.execute("SELECT sk FROM dim_conductor WHERE conductor_id_odoo=%s", (conductor_de_vehiculo[vodoo],))
            csk = dcur.fetchone()[0]
        dur = round((t["fin"] - t["inicio"]).total_seconds() / 60.0, 2)
        dcur.execute(
            """INSERT INTO fact_recorridos
                 (vehiculo_sk, conductor_sk, tiempo_inicio_sk, zona_origen_sk, zona_destino_sk, inicio_utc, fin_utc,
                  distancia_km, duracion_min, num_paradas, fuente_id, procedencia, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'REAL',%s)
               ON CONFLICT (fuente_id, procedencia) DO UPDATE SET
                 fin_utc=EXCLUDED.fin_utc, distancia_km=EXCLUDED.distancia_km, duracion_min=EXCLUDED.duracion_min,
                 num_paradas=EXCLUDED.num_paradas, zona_destino_sk=EXCLUDED.zona_destino_sk""",
            (vsk, csk, ensure_tiempo(dcur, t["inicio"]), nearest_zone_sk(zonas, t["lat_ini"], t["lon_ini"]),
             nearest_zone_sk(zonas, t["lat_fin"], t["lon_fin"]), t["inicio"], t["fin"], t["distancia_km"], dur,
             nstops, fid, lote_id))
        counts["recorridos"] += 1
    return mark


# ---------------------------------------------------------------- Odoo -> hechos
def load_rutas(dcur, scur, lote_id, odoo, counts):
    """Ventana temporal de cada ruta (completa en cada corrida) para la regla de vinculo."""
    veh = _sk_map(dcur, "dim_vehiculo", "vehiculo_id_odoo")
    for r in q.dedupe(odoo.get("logistica.ruta") or [], key=lambda x: x["id"]):
        v = dict(inicio=q.parse_ts(r.get("started_at")), fin=q.parse_ts(r.get("finished_at")))
        motivo = q.check_ruta(v)
        if motivo:
            staging.reject(scur, lote_id, "ruta", r["id"], motivo, r)
            counts["rechazados"] += 1
            dcur.execute("DELETE FROM ruta_ventana WHERE ruta_id_odoo=%s", (r["id"],))
            continue
        dcur.execute(
            """INSERT INTO ruta_ventana (ruta_id_odoo, vehiculo_sk, inicio_utc, fin_utc, lote_id)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (ruta_id_odoo) DO UPDATE SET vehiculo_sk=EXCLUDED.vehiculo_sk,
                 inicio_utc=EXCLUDED.inicio_utc, fin_utc=EXCLUDED.fin_utc, lote_id=EXCLUDED.lote_id""",
            (r["id"], veh.get(_id(r.get("vehicle_id"))), v["inicio"], v["fin"], lote_id))


def load_entregas(dcur, scur, lote_id, odoo, conductor_de_vehiculo, counts):
    rows = odoo.get("logistica.entrega")
    if not rows:
        return
    zonas = load_zonas(dcur)
    rutas = {r["id"]: r for r in odoo.get("logistica.ruta") or []}
    parada_de = {}
    for p in odoo.get("logistica.ruta.parada") or []:
        eid = _id(p.get("entrega_id"))
        if eid is not None:
            parada_de[eid] = p
    eventos = {}
    for ev in odoo.get("logistica.entrega.evento") or []:
        eventos.setdefault(_id(ev.get("entrega_id")), []).append(ev)
    veh = _sk_map(dcur, "dim_vehiculo", "vehiculo_id_odoo")
    cond = _sk_map(dcur, "dim_conductor", "conductor_id_odoo")

    for e in q.dedupe(rows, key=lambda x: x["id"]):
        par = parada_de.get(e["id"])
        ruta_id = _id(par.get("route_id")) if par else None
        ruta_id = ruta_id or _id(e.get("route_id"))
        ruta = rutas.get(ruta_id)
        inicio_ruta = q.parse_ts(ruta.get("started_at")) if ruta else None
        planificado = inicio_ruta
        if planificado is None and ruta and ruta.get("date"):
            planificado = q.parse_ts(str(ruta["date"])[:10])
        completado = q.parse_ts(par.get("completed_at")) if par else None
        motivo = (par or {}).get("failed_reason") or None
        for ev in eventos.get(e["id"], []):
            if completado is None and ev.get("event_type") in ("entregado", "no_entregado"):
                completado = q.parse_ts(ev.get("event_time"))
            motivo = motivo or ev.get("failure_reason") or None
        norm = dict(id=e["id"], lat=e.get("latitude") or None, lon=e.get("longitude") or None,
                    inicio_ruta=inicio_ruta, completado=completado)
        problema = q.check_entrega(norm)
        if problema is not None:
            staging.reject(scur, lote_id, "entrega", e["id"], problema, e)
            counts["rechazados"] += 1
            continue
        resultado = ESTADO_RESULTADO.get(e.get("state"), "pendiente")
        if resultado != "no_entregado":
            motivo = None
        cid = _id(e.get("partner_id"))
        zsk = nearest_zone_sk(zonas, norm["lat"], norm["lon"])
        csk = None
        if cid is not None:
            dcur.execute(
                """INSERT INTO dim_cliente (cliente_id_odoo, nombre, zona_sk) VALUES (%s,%s,%s)
                   ON CONFLICT (cliente_id_odoo) DO UPDATE
                   SET nombre=COALESCE(EXCLUDED.nombre, dim_cliente.nombre),
                       zona_sk=COALESCE(EXCLUDED.zona_sk, dim_cliente.zona_sk) RETURNING sk""",
                (cid, _name(e.get("partner_id")), zsk))
            csk = dcur.fetchone()[0]
        vid = _id(ruta.get("vehicle_id")) if ruta else None
        did = _id(ruta.get("driver_id")) if ruta else None
        if did is None and vid is not None:
            did = conductor_de_vehiculo.get(vid)
        tiempo = completado or planificado or q.parse_ts(e.get("create_date"))
        dcur.execute(
            """INSERT INTO fact_entregas
                 (cliente_sk, vehiculo_sk, conductor_sk, tiempo_sk, zona_sk, entrega_id_odoo, ruta_id_odoo,
                  resultado, motivo, planificado_utc, completado_utc, procedencia, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'REAL',%s)
               ON CONFLICT (entrega_id_odoo) DO UPDATE SET
                 cliente_sk=EXCLUDED.cliente_sk, vehiculo_sk=EXCLUDED.vehiculo_sk, conductor_sk=EXCLUDED.conductor_sk,
                 tiempo_sk=EXCLUDED.tiempo_sk, zona_sk=EXCLUDED.zona_sk, ruta_id_odoo=EXCLUDED.ruta_id_odoo,
                 resultado=EXCLUDED.resultado, motivo=EXCLUDED.motivo, planificado_utc=EXCLUDED.planificado_utc,
                 completado_utc=EXCLUDED.completado_utc, lote_id=EXCLUDED.lote_id""",
            (csk, veh.get(vid), cond.get(did), ensure_tiempo(dcur, tiempo), zsk, e["id"], ruta_id, resultado, motivo,
             planificado, completado, lote_id))
        counts["entregas"] += 1


def link_entregas_recorridos(cur, now):
    """Regla 10.2: solo con coincidencia verificable. Una entrega se vincula a un recorrido cuando coinciden
    (1) el vehiculo, que tiene dispositivo GPS; (2) el periodo de la ruta: el recorrido se solapa con
    started_at..finished_at de la ruta de la entrega (finished_at NULL = hasta `now`); y (3) el cierre de la
    entrega cae dentro del recorrido. Si no, recorrido_sk queda NULL."""
    cur.execute(
        """UPDATE fact_entregas f SET recorrido_sk = (
             SELECT r.sk FROM fact_recorridos r
             JOIN dim_vehiculo v ON v.sk = r.vehiculo_sk AND v.traccar_device_id IS NOT NULL
             JOIN ruta_ventana w ON w.ruta_id_odoo = f.ruta_id_odoo AND w.inicio_utc IS NOT NULL
             WHERE r.vehiculo_sk = f.vehiculo_sk AND r.procedencia = 'REAL'
               AND f.completado_utc BETWEEN r.inicio_utc AND r.fin_utc
               AND r.inicio_utc <= COALESCE(w.fin_utc, %(now)s) AND r.fin_utc >= w.inicio_utc
             ORDER BY r.inicio_utc DESC LIMIT 1)
           WHERE f.procedencia = 'REAL'
             AND f.vehiculo_sk IS NOT NULL AND f.ruta_id_odoo IS NOT NULL AND f.completado_utc IS NOT NULL""",
        {"now": now})
    # sin vinculo verificable -> NULL (incluye casos que dejaron de coincidir)
    cur.execute(
        """UPDATE fact_entregas SET recorrido_sk = NULL
           WHERE recorrido_sk IS NOT NULL AND (vehiculo_sk IS NULL OR ruta_id_odoo IS NULL OR completado_utc IS NULL)""")


# ---------------------------------------------------------------- orquestacion
def extract_to_staging(scur, lote, modo, odoo_src, traccar_src, now, dias, counts):
    """Fase 1: fuentes -> staging. Devuelve las marcas de agua candidatas (no se avanzan todavia)."""
    incremental = modo == "incremental"
    marks = {}
    if odoo_src is None:
        counts["omitidos"].append("odoo")
    else:
        for model in MODELS:
            since = watermark.get(scur, "odoo:" + model) if incremental and model in INCREMENTAL else None
            try:
                data = odoo_src.fetch(model, since)
            except Exception as exc:  # modelo/campo inconsistente: omitir sin abortar el lote
                counts["omitidos"].append("%s (%s)" % (model, str(exc)[:80]))
                continue
            if data is None:
                counts["omitidos"].append(model)
                continue
            staging.stage_odoo(scur, lote, model, data)
            if model in INCREMENTAL:
                for r in data:
                    marks["odoo:" + model] = _max(marks.get("odoo:" + model), q.parse_ts(r.get("write_date")))
    if traccar_src is None:
        counts["omitidos"].append("traccar")
    else:
        desde = watermark.get(scur, "traccar") if incremental else None
        desde = desde or now - timedelta(days=dias)
        fetched = traccar_src.fetch(desde, now)
        for clave in staging.TRACCAR_ENDPOINTS:
            staging.stage_traccar(scur, lote, clave, fetched.get(clave) or [])
    return marks


def run_etl(stg_conn, dwh_conn, modo, odoo_src, traccar_src, now=None, dias=30):
    """modo: 'full' | 'incremental'. odoo_src.fetch(modelo, since) -> filas | None (modelo ausente);
    traccar_src.fetch(desde, hasta) -> dict. Cualquiera puede ser None (fuente no disponible).

    1) extrae a staging y confirma; 2) lee el crudo del lote desde staging; 3) escribe en el DWH y confirma;
    4) avanza las marcas de agua y cierra el lote. Si el DWH falla, las marcas no avanzan y el lote queda 'error'.
    Como el DWH usa upserts, repetir un lote es idempotente."""
    now = now or datetime.now(timezone.utc)
    counts = {"posiciones": 0, "recorridos": 0, "entregas": 0, "rechazados": 0, "omitidos": []}
    scur = stg_conn.cursor()
    lote = staging.new_lote(scur, modo)
    stg_conn.commit()  # el lote existe aunque la corrida falle
    try:
        marks = extract_to_staging(scur, lote, modo, odoo_src, traccar_src, now, dias, counts)
        stg_conn.commit()

        odoo = staging.read_odoo(scur, lote)
        traccar = staging.read_traccar(scur, lote) if traccar_src is not None else None

        dcur = dwh_conn.cursor()
        conductor_de_vehiculo = {}
        load_dimensions(dcur, odoo, traccar, conductor_de_vehiculo)
        tmark = load_traccar(dcur, scur, lote, traccar, conductor_de_vehiculo, counts)
        if tmark:
            marks["traccar"] = tmark
        load_rutas(dcur, scur, lote, odoo, counts)
        load_entregas(dcur, scur, lote, odoo, conductor_de_vehiculo, counts)
        link_entregas_recorridos(dcur, now)
        dwh_conn.commit()

        for fuente, valor in marks.items():
            watermark.advance(scur, fuente, valor)
        staging.close_lote(scur, lote, "ok", counts)
        stg_conn.commit()
    except Exception:
        dwh_conn.rollback()
        stg_conn.rollback()
        scur = stg_conn.cursor()
        staging.close_lote(scur, lote, "error", {"error": True})
        stg_conn.commit()
        raise
    return counts
