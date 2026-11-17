"""Carga de hechos en el DWH. `dcur` es un cursor del DWH y `scur` uno de staging (para los rechazados).

Los hechos de Odoo se recalculan en cada corrida a partir del estado actual completo (ultima version de cada
registro): por eso un cambio en una ruta refresca sus entregas, y lo que ya no existe o deja de ser valido se
quita del DWH. Los hechos de Traccar se cargan solo con lo extraido en el lote."""
from datetime import timedelta

from psycopg2.extras import execute_values

from .. import staging
from ..transform import normalize as n
from ..transform import quality as q
from . import link
from .dimensions import ensure_tiempo

ESTADO_RESULTADO = {
    "entregado": "entregado",
    "no_entregado": "no_entregado",
    "pendiente_reprogramacion": "no_entregado",
    "devuelto_bodega": "no_entregado",
}
EVENTOS_CIERRE = ("entregado", "no_entregado")
# Rutas que no cuentan como intento de entrega.
RUTAS_SIN_EFECTO = ("cancelada",)
# Pedidos confirmados: los unicos que son venta.
PEDIDOS_VENTA = ("sale", "done")
# Un viaje que termino hace menos de esto puede seguir en curso (Traccar lo devuelve cortado en `ahora`):
# se deja para una corrida posterior, cuando ya este completo.
CIERRE_RECORRIDO = timedelta(minutes=10)
# Un viaje "en curso" retiene la marca de agua solo si empezo hace menos de esto: un GPS con deriva estando
# aparcado (o un equipo con el reloj mal) daria un viaje que nunca termina y la marca no avanzaria nunca.
MAX_EN_CURSO = timedelta(hours=12)


def _rechazar(scur, ctx, entidad, fuente_id, motivo, payload):
    staging.reject(scur, ctx.lote_id, entidad, fuente_id, motivo, payload)
    ctx.rechazados[motivo] = ctx.rechazados.get(motivo, 0) + 1


def _podar(dcur, tabla, columna, ids_validos):
    """Quita los hechos REALES cuyo registro de origen ya no existe o dejo de ser valido."""
    dcur.execute("DELETE FROM %s WHERE procedencia='REAL' AND %s <> ALL(%%s)" % (tabla, columna),
                 (list(ids_validos),))


# ---------------------------------------------------------------- Traccar
def _norm_position(p):
    return dict(
        id=p.get("id"), device=p.get("deviceId"), time=n.parse_ts(p.get("fixTime") or p.get("deviceTime")),
        lat=n.numero(p.get("latitude")), lon=n.numero(p.get("longitude")),
        speed_kmh=n.knots_to_kmh(p["speed"]) if n.numero(p.get("speed")) is not None else None)


def _norm_trip(t):
    def kmh(k):
        return n.knots_to_kmh(t[k]) if n.numero(t.get(k)) is not None else None
    return dict(
        device=t.get("deviceId"), inicio=n.parse_ts(t.get("startTime")), fin=n.parse_ts(t.get("endTime")),
        lat_ini=n.numero(t.get("startLat")), lon_ini=n.numero(t.get("startLon")),
        lat_fin=n.numero(t.get("endLat")), lon_fin=n.numero(t.get("endLon")),
        distancia_km=n.meters_to_km(t["distance"]) if n.numero(t.get("distance")) is not None else None,
        avg_kmh=kmh("averageSpeed"), max_kmh=kmh("maxSpeed"))


def _max(a, b):
    return b if a is None or (b is not None and b > a) else a


def load_posiciones(dcur, scur, ctx, traccar):
    """fact_posicion_gps. Devuelve la fecha mas reciente vista (candidata a marca de agua)."""
    marca, filas = None, []
    crudas = [_norm_position(x) for x in traccar.get("positions") or []]
    for p in n.dedupe(crudas, key=lambda x: (x["device"], x["id"] if x["id"] is not None else x["time"])):
        fid = "pos:%s:%s" % (p["device"], p["id"] if p["id"] is not None
                             else p["time"].isoformat() if p["time"] else "?")
        motivo = q.check_position(p, ctx.now)
        if motivo != "fechas_incoherentes":    # una fecha futura no puede mover la marca (dejaria de pedir todo)
            marca = _max(marca, p["time"])     # lo rechazado tambien cuenta como visto: no se vuelve a pedir
        if motivo is None and p["device"] not in ctx.dispositivo:
            motivo = "dispositivo_sin_vehiculo"
        if motivo:
            _rechazar(scur, ctx, "posicion", fid, motivo, p)
            continue
        filas.append((ctx.dispositivo[p["device"]][0], ensure_tiempo(dcur, ctx, p["time"]), p["time"], p["lat"],
                      p["lon"], p["speed_kmh"], fid, ctx.lote_id))
    staging.resolver_rechazos_cargados(scur, "posicion", [f[6] for f in filas])
    if filas:
        execute_values(
            dcur, """INSERT INTO fact_posicion_gps (vehiculo_sk, tiempo_sk, gps_time_utc, latitud, longitud,
                                                    velocidad_kmh, fuente_id, lote_id)
                     VALUES %s ON CONFLICT (fuente_id) DO NOTHING""", filas, page_size=1000)
    ctx.contar("fact_posicion_gps", len(filas))
    return marca


def _es_tramo_de_otro(dcur, vehiculo_sk, fuente_id, inicio):
    """True si el viaje empieza dentro de otro viaje ya cargado del mismo vehiculo: es un trozo de ese viaje,
    que Traccar devuelve cuando la ventana pedida empieza con el vehiculo en movimiento."""
    dcur.execute("SELECT 1 FROM fact_recorridos WHERE vehiculo_sk=%s AND procedencia='REAL' AND fuente_id <> %s "
                 "AND inicio_utc < %s AND fin_utc > %s LIMIT 1", (vehiculo_sk, fuente_id, inicio, inicio))
    return dcur.fetchone() is not None


def _quitar_trozos(dcur, vehiculo_sk, fuente_id):
    """Quita los viajes del vehiculo que empiezan dentro del viaje `fuente_id` (tal como quedo guardado): son trozos
    suyos cargados antes como viajes aparte (p. ej. cuando el GPS subio tarde lo que guardo sin cobertura). Sus
    vinculos con entregas se sueltan; el vinculo se recalcula al final de la corrida. Devuelve cuantos quito."""
    trozos = """SELECT o.sk FROM fact_recorridos v JOIN fact_recorridos o
                  ON o.vehiculo_sk = v.vehiculo_sk AND o.procedencia = 'REAL' AND o.fuente_id <> v.fuente_id
                 AND o.inicio_utc >= v.inicio_utc AND o.inicio_utc < v.fin_utc
                WHERE v.vehiculo_sk = %(v)s AND v.fuente_id = %(f)s AND v.procedencia = 'REAL'"""
    dcur.execute("UPDATE fact_entregas SET recorrido_sk = NULL WHERE recorrido_sk IN (" + trozos + ")",
                 {"v": vehiculo_sk, "f": fuente_id})
    dcur.execute("DELETE FROM fact_recorridos WHERE sk IN (" + trozos + ")", {"v": vehiculo_sk, "f": fuente_id})
    return dcur.rowcount


def load_recorridos(dcur, scur, ctx, traccar):
    """fact_recorridos (viajes de Traccar ya terminados). Devuelve la marca de agua candidata: el fin del ultimo
    viaje visto completo (la siguiente ventana empieza ahi, en una parada), pero nunca despues del inicio de un
    viaje que sigue en curso. La marca es una sola para todos los dispositivos: si superara ese inicio, la
    corrida siguiente pediria la ventana desde mas tarde y Traccar devolveria el viaje cortado (o nada)."""
    marca, en_curso, tramos, tope, cargados, reemplazados = None, 0, 0, None, [], 0
    paradas = [(s.get("deviceId"), n.parse_ts(s.get("startTime"))) for s in traccar.get("stops") or []]
    viajes = [_norm_trip(x) for x in traccar.get("trips") or []]
    for t in n.dedupe(viajes, key=lambda x: (x["device"], x["inicio"])):
        fid = "trip:%s:%s" % (t["device"], t["inicio"].isoformat() if t["inicio"] else "?")
        motivo = q.check_trip(t, ctx.now)
        if motivo == "fechas_incoherentes":    # fin antes del inicio o en el futuro: ni marca ni tope
            _rechazar(scur, ctx, "recorrido", fid, motivo, t)
            continue
        if motivo is None and t["device"] not in ctx.dispositivo:
            motivo = "dispositivo_sin_vehiculo"
        if t["fin"] is not None and t["fin"] > ctx.now - CIERRE_RECORRIDO:
            en_curso += 1
            # retiene la marca solo un viaje que se va a cargar y que empezo hace poco
            if (motivo is None and t["inicio"] is not None and t["inicio"] >= ctx.now - MAX_EN_CURSO
                    and (tope is None or t["inicio"] < tope)):
                tope = t["inicio"]
            continue
        marca = _max(marca, t["fin"])
        if motivo:
            _rechazar(scur, ctx, "recorrido", fid, motivo, t)
            continue
        vsk, vodoo = ctx.dispositivo[t["device"]]
        if _es_tramo_de_otro(dcur, vsk, fid, t["inicio"]):
            tramos += 1
            continue
        num_paradas = sum(1 for d, ini in paradas if d == t["device"] and ini and t["inicio"] <= ini <= t["fin"])
        dcur.execute(
            """INSERT INTO fact_recorridos
                 (vehiculo_sk, conductor_sk, tiempo_inicio_sk, zona_origen_sk, zona_destino_sk, inicio_utc, fin_utc,
                  distancia_km, duracion_min, num_paradas, velocidad_media_kmh, velocidad_max_kmh, fuente_id,
                  procedencia, lote_id, lat_origen, lon_origen, lat_destino, lon_destino)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'REAL',%s,%s,%s,%s,%s)
               ON CONFLICT (fuente_id, procedencia) DO UPDATE SET
                 conductor_sk=COALESCE(fact_recorridos.conductor_sk, EXCLUDED.conductor_sk), fin_utc=EXCLUDED.fin_utc, distancia_km=EXCLUDED.distancia_km,
                 duracion_min=EXCLUDED.duracion_min, num_paradas=EXCLUDED.num_paradas,
                 zona_origen_sk=EXCLUDED.zona_origen_sk, zona_destino_sk=EXCLUDED.zona_destino_sk,
                 velocidad_media_kmh=EXCLUDED.velocidad_media_kmh, velocidad_max_kmh=EXCLUDED.velocidad_max_kmh,
                 lote_id=EXCLUDED.lote_id, lat_origen=EXCLUDED.lat_origen, lon_origen=EXCLUDED.lon_origen,
                 lat_destino=EXCLUDED.lat_destino, lon_destino=EXCLUDED.lon_destino
               WHERE EXCLUDED.fin_utc >= fact_recorridos.fin_utc""",
            (vsk, ctx.conductor.get(ctx.conductor_de_vehiculo.get(vodoo)), ensure_tiempo(dcur, ctx, t["inicio"]),
             ctx.zona(t["lat_ini"], t["lon_ini"]), ctx.zona(t["lat_fin"], t["lon_fin"]), t["inicio"], t["fin"],
             t["distancia_km"], n.minutos(t["inicio"], t["fin"]), num_paradas, t["avg_kmh"], t["max_kmh"], fid,
             ctx.lote_id, t["lat_ini"], t["lon_ini"], t["lat_fin"], t["lon_fin"]))
        reemplazados += _quitar_trozos(dcur, vsk, fid)
        cargados.append(fid)
        ctx.contar("fact_recorridos")
    staging.resolver_rechazos_cargados(scur, "recorrido", cargados)
    if en_curso:
        ctx.omitidos.append("recorridos en curso (se cargan al terminar): %d" % en_curso)
    if tramos:
        ctx.omitidos.append("tramos de recorridos ya cargados: %d" % tramos)
    if reemplazados:
        ctx.omitidos.append("trozos sustituidos por su viaje completo: %d" % reemplazados)
    if tope is not None and marca is not None and marca > tope:
        marca = tope
    return marca


# ---------------------------------------------------------------- Odoo
def _norm_ruta(r, tz):
    km, mins = n.numero(r.get("planned_distance_km")), n.numero(r.get("planned_duration_min"))
    return dict(
        id=r.get("id"), codigo=n.texto(r.get("name")), fecha=str(r["date"])[:10] if r.get("date") else None,
        fecha_utc=n.fecha_local_a_utc(r.get("date"), tz), estado=n.texto(r.get("state")),
        vehiculo_id=n.m2o_id(r.get("vehicle_id")), conductor_id=n.m2o_id(r.get("driver_id")),
        carga=n.parse_ts(r.get("confirmed_load_at")), inicio=n.parse_ts(r.get("started_at")),
        fin=n.parse_ts(r.get("finished_at")),
        # 0 en Odoo = todavia no se calculo el plan
        km_plan=km or None, min_plan=mins or None, fuente_distancia=n.texto(r.get("distance_source")))


def _norm_parada(p):
    return dict(
        id=p.get("id"), ruta_id=n.m2o_id(p.get("route_id")), entrega_id=n.m2o_id(p.get("entrega_id")),
        orden=p.get("sequence") if isinstance(p.get("sequence"), int) else None, estado=n.texto(p.get("state")),
        posible_llegada=n.parse_ts(p.get("arrival_candidate_at")), llegada=n.parse_ts(p.get("actual_arrival_at")),
        cierre=n.parse_ts(p.get("completed_at")), motivo=n.texto(p.get("failed_reason")))


def preparar_rutas(scur, ctx, odoo):
    """Normaliza y valida rutas y paradas. Devuelve (rutas, paradas) validas, indexadas por id."""
    rutas, paradas = {}, {}
    for r in odoo.get("logistica.ruta") or []:
        v = _norm_ruta(r, ctx.tz)
        motivo = q.check_ruta(v)
        if motivo:
            _rechazar(scur, ctx, "ruta", r.get("id"), motivo, r)
            continue
        rutas[v["id"]] = v
    for p in odoo.get("logistica.ruta.parada") or []:
        v = _norm_parada(p)
        motivo = q.check_parada(v)
        if motivo:
            _rechazar(scur, ctx, "parada", p.get("id"), motivo, p)
            continue
        paradas[v["id"]] = v
    return rutas, paradas


def load_rutas(dcur, ctx, odoo, rutas, paradas):
    """fact_rutas: una fila por ruta de despacho, con lo planificado y el resultado de sus paradas."""
    if odoo.get("logistica.ruta") is None:
        return
    por_ruta = {}
    for p in paradas.values():
        por_ruta.setdefault(p["ruta_id"], []).append(p["estado"])
    for r in rutas.values():
        estados = por_ruta.get(r["id"], [])
        conductor = r["conductor_id"] or ctx.conductor_de_vehiculo.get(r["vehiculo_id"])
        dcur.execute(
            """INSERT INTO fact_rutas
                 (ruta_id_odoo, codigo, vehiculo_sk, conductor_sk, tiempo_sk, fecha, estado, carga_confirmada_utc,
                  inicio_utc, fin_utc, km_planificado, min_planificado, fuente_distancia, min_real, paradas_total,
                  paradas_entregadas, paradas_fallidas, paradas_pendientes, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (ruta_id_odoo) DO UPDATE SET
                 codigo=EXCLUDED.codigo, vehiculo_sk=EXCLUDED.vehiculo_sk, conductor_sk=EXCLUDED.conductor_sk,
                 tiempo_sk=EXCLUDED.tiempo_sk, fecha=EXCLUDED.fecha, estado=EXCLUDED.estado,
                 carga_confirmada_utc=EXCLUDED.carga_confirmada_utc, inicio_utc=EXCLUDED.inicio_utc,
                 fin_utc=EXCLUDED.fin_utc, km_planificado=EXCLUDED.km_planificado,
                 min_planificado=EXCLUDED.min_planificado, fuente_distancia=EXCLUDED.fuente_distancia,
                 min_real=EXCLUDED.min_real, paradas_total=EXCLUDED.paradas_total,
                 paradas_entregadas=EXCLUDED.paradas_entregadas, paradas_fallidas=EXCLUDED.paradas_fallidas,
                 paradas_pendientes=EXCLUDED.paradas_pendientes, lote_id=EXCLUDED.lote_id""",
            (r["id"], r["codigo"], ctx.vehiculo.get(r["vehiculo_id"]), ctx.conductor.get(conductor),
             ensure_tiempo(dcur, ctx, r["inicio"] or r["fecha_utc"]), r["fecha"], r["estado"], r["carga"],
             r["inicio"], r["fin"], r["km_plan"], r["min_plan"], r["fuente_distancia"],
             n.minutos(r["inicio"], r["fin"]), len(estados), estados.count("entregado"),
             estados.count("no_entregado"), estados.count("pendiente"), ctx.lote_id))
        ctx.contar("fact_rutas")
    _podar(dcur, "fact_rutas", "ruta_id_odoo", rutas)


def medir_rutas(dcur, ctx):
    """km reales y numero de posiciones de cada ruta: posiciones GPS de su vehiculo dentro de su ventana
    (inicio..fin; una ruta abierta llega hasta `ahora`, como mucho link.MAX_RUTA_ABIERTA_H horas). Con menos de
    dos posiciones no hay distancia."""
    dcur.execute(
        """WITH seg AS (
             SELECT r.sk, g.latitud AS la, g.longitud AS lo,
                    lag(g.latitud) OVER w AS la0, lag(g.longitud) OVER w AS lo0
             FROM fact_rutas r
             JOIN fact_posicion_gps g ON g.vehiculo_sk = r.vehiculo_sk
                  AND g.gps_time_utc >= r.inicio_utc AND g.gps_time_utc <= """ + link.fin_ventana("r") + """
             WHERE r.inicio_utc IS NOT NULL
             WINDOW w AS (PARTITION BY r.sk ORDER BY g.gps_time_utc, g.sk)),
           tot AS (
             SELECT sk, count(*) AS posiciones,
                    sum(CASE WHEN la0 IS NULL THEN 0 ELSE 2 * 6371.0088 * asin(least(1, sqrt(
                          power(sin(radians(la - la0) / 2), 2)
                          + cos(radians(la0)) * cos(radians(la)) * power(sin(radians(lo - lo0) / 2), 2)))) END) AS km
             FROM seg GROUP BY sk)
           UPDATE fact_rutas r
           SET posiciones_gps = COALESCE(t.posiciones, 0),
               km_real = CASE WHEN t.posiciones >= 2 THEN round(t.km::numeric, 3) END
           FROM fact_rutas r2 LEFT JOIN tot t ON t.sk = r2.sk
           WHERE r2.sk = r.sk AND r.procedencia = 'REAL'""", {"now": ctx.now})


def load_paradas(dcur, ctx, odoo, rutas, paradas, entregas):
    """fact_paradas: una fila por parada, con sus tiempos."""
    if odoo.get("logistica.ruta.parada") is None:
        return
    cargadas = []
    for p in paradas.values():
        ruta = rutas.get(p["ruta_id"])
        if ruta is None:        # su ruta fue rechazada o ya no existe
            continue
        ent = entregas.get(p["entrega_id"]) or {}
        conductor = ruta["conductor_id"] or ctx.conductor_de_vehiculo.get(ruta["vehiculo_id"])
        dcur.execute(
            """INSERT INTO fact_paradas
                 (parada_id_odoo, ruta_id_odoo, entrega_id_odoo, vehiculo_sk, conductor_sk, cliente_sk, zona_sk,
                  tiempo_sk, orden, estado, posible_llegada_utc, llegada_utc, cierre_utc, min_en_parada,
                  min_desde_inicio_ruta, motivo, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (parada_id_odoo) DO UPDATE SET
                 ruta_id_odoo=EXCLUDED.ruta_id_odoo, entrega_id_odoo=EXCLUDED.entrega_id_odoo,
                 vehiculo_sk=EXCLUDED.vehiculo_sk, conductor_sk=EXCLUDED.conductor_sk, cliente_sk=EXCLUDED.cliente_sk,
                 zona_sk=EXCLUDED.zona_sk, tiempo_sk=EXCLUDED.tiempo_sk, orden=EXCLUDED.orden, estado=EXCLUDED.estado,
                 posible_llegada_utc=EXCLUDED.posible_llegada_utc, llegada_utc=EXCLUDED.llegada_utc,
                 cierre_utc=EXCLUDED.cierre_utc, min_en_parada=EXCLUDED.min_en_parada,
                 min_desde_inicio_ruta=EXCLUDED.min_desde_inicio_ruta, motivo=EXCLUDED.motivo,
                 lote_id=EXCLUDED.lote_id""",
            (p["id"], p["ruta_id"], p["entrega_id"], ctx.vehiculo.get(ruta["vehiculo_id"]),
             ctx.conductor.get(conductor), ctx.cliente.get(ent.get("cliente_id")),
             ctx.zona(ent.get("lat"), ent.get("lon")),
             ensure_tiempo(dcur, ctx, p["cierre"] or p["llegada"] or ruta["inicio"] or ruta["fecha_utc"]),
             p["orden"], p["estado"], p["posible_llegada"], p["llegada"], p["cierre"],
             n.minutos(p["llegada"], p["cierre"]), n.minutos(ruta["inicio"], p["cierre"] or p["llegada"]),
             p["motivo"] if p["estado"] == "no_entregado" else None, ctx.lote_id))
        cargadas.append(p["id"])
        ctx.contar("fact_paradas")
    _podar(dcur, "fact_paradas", "parada_id_odoo", cargadas)


def preparar_entregas(odoo):
    """Entregas de Odoo indexadas por id, con sus coordenadas ya limpias (sirve a paradas, entregas y ventas)."""
    out = {}
    for e in odoo.get("logistica.entrega") or []:
        lat, lon = n.coordenada(e.get("latitude"), e.get("longitude"))
        out[e["id"]] = dict(id=e["id"], crudo=e, lat=lat, lon=lon, cliente_id=n.m2o_id(e.get("partner_id")),
                            pedido_id=n.m2o_id(e.get("sale_order_id")), ruta_id=n.m2o_id(e.get("route_id")),
                            estado=n.texto(e.get("state")), creado=n.parse_ts(e.get("create_date")))
    return out


def load_entregas(dcur, scur, ctx, odoo, rutas, paradas, entregas):
    """fact_entregas: una fila por entrega, con su resultado, su ruta vigente y si se cumplio lo planificado."""
    if odoo.get("logistica.entrega") is None:
        return
    # parada vigente de cada entrega: la mas reciente en una ruta que cuente como intento
    paradas_de = {}
    for p in sorted(paradas.values(), key=lambda x: x["id"]):
        ruta = rutas.get(p["ruta_id"])
        if p["entrega_id"] is not None and ruta is not None and ruta["estado"] not in RUTAS_SIN_EFECTO:
            paradas_de.setdefault(p["entrega_id"], []).append(p)
    eventos = {}
    for ev in odoo.get("logistica.entrega.evento") or []:
        eventos.setdefault(n.m2o_id(ev.get("entrega_id")), []).append(ev)

    cargadas = []
    for e in entregas.values():
        intentos = paradas_de.get(e["id"], [])
        par = intentos[-1] if intentos else None
        ruta_id = par["ruta_id"] if par else e["ruta_id"]
        ruta = rutas.get(ruta_id)
        inicio_ruta = ruta["inicio"] if ruta else None
        planificado = inicio_ruta or (ruta["fecha_utc"] if ruta else None)
        limite = None
        if inicio_ruta is not None and ruta["min_plan"] is not None:
            limite = inicio_ruta + timedelta(minutes=ruta["min_plan"])
        completado = par["cierre"] if par else None
        motivo = par["motivo"] if par else None
        for ev in sorted(eventos.get(e["id"], []), key=lambda x: x.get("id") or 0):
            if ev.get("event_type") in EVENTOS_CIERRE:
                if par is None or par["cierre"] is None:
                    completado = n.parse_ts(ev.get("event_time")) or completado
                motivo = motivo or n.texto(ev.get("failure_reason"))
        problema = q.check_entrega(dict(id=e["id"], lat=e["lat"], lon=e["lon"], inicio_ruta=inicio_ruta,
                                        completado=completado))
        if problema is not None:
            _rechazar(scur, ctx, "entrega", e["id"], problema, e["crudo"])
            continue
        resultado = ESTADO_RESULTADO.get(e["estado"], "pendiente")
        if resultado != "no_entregado":
            motivo = None
        if resultado == "pendiente":
            completado = None    # un cierre anterior pertenece a un intento ya reprogramado
        a_tiempo = None
        if resultado == "entregado" and completado is not None and limite is not None:
            a_tiempo = completado <= limite
        vehiculo_id = ruta["vehiculo_id"] if ruta else None
        conductor_id = (ruta["conductor_id"] or ctx.conductor_de_vehiculo.get(vehiculo_id)) if ruta else None
        dcur.execute(
            """INSERT INTO fact_entregas
                 (cliente_sk, vehiculo_sk, conductor_sk, tiempo_sk, zona_sk, entrega_id_odoo, ruta_id_odoo,
                  resultado, motivo, planificado_utc, completado_utc, pedido_id_odoo, estado_odoo, creado_utc,
                  limite_plan_utc, a_tiempo, intentos, procedencia, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'REAL',%s)
               ON CONFLICT (entrega_id_odoo) DO UPDATE SET
                 cliente_sk=EXCLUDED.cliente_sk, vehiculo_sk=EXCLUDED.vehiculo_sk, conductor_sk=EXCLUDED.conductor_sk,
                 tiempo_sk=EXCLUDED.tiempo_sk, zona_sk=EXCLUDED.zona_sk, ruta_id_odoo=EXCLUDED.ruta_id_odoo,
                 resultado=EXCLUDED.resultado, motivo=EXCLUDED.motivo, planificado_utc=EXCLUDED.planificado_utc,
                 completado_utc=EXCLUDED.completado_utc, pedido_id_odoo=EXCLUDED.pedido_id_odoo,
                 estado_odoo=EXCLUDED.estado_odoo, creado_utc=EXCLUDED.creado_utc,
                 limite_plan_utc=EXCLUDED.limite_plan_utc, a_tiempo=EXCLUDED.a_tiempo, intentos=EXCLUDED.intentos,
                 lote_id=EXCLUDED.lote_id""",
            (ctx.cliente.get(e["cliente_id"]), ctx.vehiculo.get(vehiculo_id), ctx.conductor.get(conductor_id),
             ensure_tiempo(dcur, ctx, completado or planificado or e["creado"]), ctx.zona(e["lat"], e["lon"]),
             e["id"], ruta_id, resultado, motivo, planificado, completado, e["pedido_id"], e["estado"], e["creado"],
             limite, a_tiempo, len(intentos), ctx.lote_id))
        cargadas.append(e["id"])
        ctx.contar("fact_entregas")
    _podar(dcur, "fact_entregas", "entrega_id_odoo", cargadas)


def load_ventas(dcur, scur, ctx, odoo, entregas):
    """fact_ventas: una fila por linea de producto de un pedido confirmado."""
    if odoo.get("sale.order.line") is None or odoo.get("sale.order") is None:
        return
    pedidos = {o["id"]: o for o in odoo["sale.order"]}
    entrega_de = {e["pedido_id"]: e for e in entregas.values() if e["pedido_id"] is not None}
    cargadas = []
    for linea in odoo["sale.order.line"]:
        if linea.get("display_type"):      # secciones y notas: no son venta
            continue
        pedido = pedidos.get(n.m2o_id(linea.get("order_id")))
        if pedido is None or pedido.get("state") not in PEDIDOS_VENTA:
            continue                       # borrador, cotizacion o cancelado: no es un rechazo, aun no es venta
        v = dict(id=linea.get("id"), pedido_id=pedido["id"], producto_id=n.m2o_id(linea.get("product_id")),
                 cantidad=n.numero(linea.get("product_uom_qty")), precio=n.numero(linea.get("price_unit")),
                 subtotal=n.numero(linea.get("price_subtotal")), total=n.numero(linea.get("price_total")))
        motivo = q.check_venta(v)
        if motivo:
            _rechazar(scur, ctx, "venta", linea.get("id"), motivo, linea)
            continue
        ent = entrega_de.get(pedido["id"]) or {}
        lat, lon = n.coordenada(pedido.get("delivery_latitude"), pedido.get("delivery_longitude"))
        if lat is None:
            lat, lon = ent.get("lat"), ent.get("lon")
        fecha = n.parse_ts(pedido.get("date_order"))
        dcur.execute(
            """INSERT INTO fact_ventas
                 (linea_id_odoo, pedido_id_odoo, pedido_ref, cliente_sk, producto_sk, zona_sk, tiempo_sk,
                  fecha_pedido_utc, estado_pedido, cantidad, precio_unitario, subtotal, total, entrega_id_odoo, lote_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (linea_id_odoo) DO UPDATE SET
                 pedido_id_odoo=EXCLUDED.pedido_id_odoo, pedido_ref=EXCLUDED.pedido_ref,
                 cliente_sk=EXCLUDED.cliente_sk, producto_sk=EXCLUDED.producto_sk, zona_sk=EXCLUDED.zona_sk,
                 tiempo_sk=EXCLUDED.tiempo_sk, fecha_pedido_utc=EXCLUDED.fecha_pedido_utc,
                 estado_pedido=EXCLUDED.estado_pedido, cantidad=EXCLUDED.cantidad,
                 precio_unitario=EXCLUDED.precio_unitario, subtotal=EXCLUDED.subtotal, total=EXCLUDED.total,
                 entrega_id_odoo=EXCLUDED.entrega_id_odoo, lote_id=EXCLUDED.lote_id""",
            (v["id"], pedido["id"], n.texto(pedido.get("name")), ctx.cliente.get(n.m2o_id(pedido.get("partner_id"))),
             ctx.producto.get(v["producto_id"]), ctx.zona(lat, lon), ensure_tiempo(dcur, ctx, fecha), fecha,
             pedido.get("state"), v["cantidad"], v["precio"], v["subtotal"], v["total"], ent.get("id"), ctx.lote_id))
        cargadas.append(v["id"])
        ctx.contar("fact_ventas")
    _podar(dcur, "fact_ventas", "linea_id_odoo", cargadas)
