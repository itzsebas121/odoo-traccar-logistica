"""Staging (base logistica_staging): crudo en JSONB, bitacora de lotes, marcas de agua, rechazados y retencion.

Todas las funciones reciben un cursor de la conexion de staging."""
import hashlib
import json

from psycopg2.extras import execute_values

# clave interna -> valor de traccar_raw.endpoint
TRACCAR_ENDPOINTS = {"devices": "devices", "positions": "reports/route", "trips": "reports/trips",
                     "stops": "reports/stops"}
# Campos que cambian sin que cambie el registro (no cuentan para decidir si hay una version nueva).
VOLATILES = ("write_date", "__last_update")
# Entidades de Odoo: se reevaluan completas en cada corrida, asi que un rechazo no repetido esta resuelto.
ENTIDADES_ODOO = ("ruta", "parada", "entrega", "venta")


def _dump(x):
    return json.dumps(x, default=str, ensure_ascii=False)


def huella(row):
    """Huella del contenido de un registro, sin los campos volatiles."""
    estable = {k: v for k, v in row.items() if k not in VOLATILES}
    return hashlib.md5(json.dumps(estable, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- lotes y marcas de agua
def new_lote(cur, modo):
    cur.execute("INSERT INTO lote (modo) VALUES (%s) RETURNING id, inicio_utc", (modo,))
    return cur.fetchone()


def close_lote(cur, lote_id, estado, conteos, error=None):
    cur.execute("UPDATE lote SET fin_utc=now(), estado=%s, conteos=%s::jsonb, error=%s WHERE id=%s RETURNING fin_utc",
                (estado, _dump(conteos), error, lote_id))
    return cur.fetchone()[0]


def get_watermark(cur, fuente):
    cur.execute("SELECT valor_utc FROM watermark WHERE fuente=%s", (fuente,))
    r = cur.fetchone()
    return r[0] if r else None


def advance_watermark(cur, fuente, valor):
    """Solo avanza (nunca retrocede)."""
    if valor is None:
        return
    cur.execute(
        """INSERT INTO watermark (fuente, valor_utc) VALUES (%s,%s)
           ON CONFLICT (fuente) DO UPDATE
           SET valor_utc = GREATEST(watermark.valor_utc, EXCLUDED.valor_utc), actualizado_utc = now()""",
        (fuente, valor))


def get_estado(cur, clave):
    """(existe, valor) del estado guardado; valor puede ser None."""
    cur.execute("SELECT valor FROM etl_estado WHERE clave=%s", (clave,))
    r = cur.fetchone()
    return (True, r[0]) if r else (False, None)


def set_estado(cur, clave, valor):
    cur.execute("""INSERT INTO etl_estado (clave, valor) VALUES (%s,%s)
                   ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, actualizado_utc=now()""", (clave, valor))


# ---------------------------------------------------------------- Odoo
def _ultimas(cur, modelo):
    """{fuente_id: (huella, eliminado)} de la ultima version guardada de cada registro del modelo."""
    cur.execute("SELECT DISTINCT ON (fuente_id) fuente_id, huella, eliminado FROM odoo_raw "
                "WHERE modelo=%s ORDER BY fuente_id, id DESC", (modelo,))
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def stage_odoo(cur, lote_id, modelo, rows):
    """Guarda una version nueva de cada registro cuyo contenido cambio. Devuelve cuantas versiones guardo."""
    ultimas = _ultimas(cur, modelo)
    nuevas = []
    for r in rows:
        fid, h = str(r.get("id")), huella(r)
        if ultimas.get(fid) == (h, False):
            continue
        ultimas[fid] = (h, False)
        nuevas.append((lote_id, modelo, fid, r.get("write_date") or None, h, _dump(r)))
    if nuevas:
        execute_values(cur, "INSERT INTO odoo_raw (lote_id, modelo, fuente_id, write_date, huella, payload) VALUES %s",
                       nuevas, template="(%s,%s,%s,%s::timestamp AT TIME ZONE 'UTC',%s,%s::jsonb)")
    return len(nuevas)


def marcar_eliminados(cur, lote_id, modelo, ids_vivos):
    """Tras una extraccion COMPLETA del modelo: los registros guardados que ya no vienen se marcan eliminados."""
    vivos = {str(i) for i in ids_vivos}
    borrados = [(lote_id, modelo, fid, "eliminado", True, _dump({"id": fid}))
                for fid, (_h, eliminado) in _ultimas(cur, modelo).items() if not eliminado and fid not in vivos]
    if borrados:
        execute_values(cur, "INSERT INTO odoo_raw (lote_id, modelo, fuente_id, huella, eliminado, payload) VALUES %s",
                       borrados, template="(%s,%s,%s,%s,%s,%s::jsonb)")
    return len(borrados)


def snapshot_odoo(cur):
    """Estado actual conocido de Odoo: {modelo: [payload, ...]} con la ultima version de cada registro vivo.
    Un modelo que se extrajo alguna vez aparece siempre (con lista vacia si ya no le quedan registros); uno que
    nunca se pudo extraer no aparece."""
    cur.execute("SELECT DISTINCT modelo FROM odoo_raw")
    out = {r[0]: [] for r in cur.fetchall()}
    cur.execute("""SELECT modelo, payload FROM (
                     SELECT DISTINCT ON (modelo, fuente_id) modelo, fuente_id, eliminado, payload, id
                     FROM odoo_raw ORDER BY modelo, fuente_id, id DESC) u
                   WHERE NOT eliminado ORDER BY modelo, (payload->>'id')::bigint""")
    for modelo, payload in cur.fetchall():
        out[modelo].append(payload)
    return out


# ---------------------------------------------------------------- Traccar
def _fuente_traccar(clave, r):
    if clave in ("devices", "positions") and r.get("id") is not None:
        return str(r["id"])
    return "%s@%s" % (r.get("deviceId"), r.get("startTime") or r.get("fixTime") or r.get("deviceTime"))


def stage_traccar(cur, lote_id, clave, rows):
    """Guarda (o refresca) la ultima lectura de cada registro y la asocia a este lote."""
    endpoint = TRACCAR_ENDPOINTS[clave]
    por_clave = {_fuente_traccar(clave, r): r for r in rows}          # sin duplicados dentro del lote
    filas = [(lote_id, endpoint, fid, _dump(r)) for fid, r in por_clave.items()]
    if filas:
        execute_values(
            cur, """INSERT INTO traccar_raw (lote_id, endpoint, fuente_id, payload) VALUES %s
                    ON CONFLICT (endpoint, fuente_id) DO UPDATE
                    SET lote_id=EXCLUDED.lote_id, payload=EXCLUDED.payload, extraido_utc=now()""",
            filas, template="(%s,%s,%s,%s::jsonb)", page_size=1000)
    return len(filas)


def read_traccar(cur, lote_id):
    """Lecturas del lote: {'devices': [...], 'positions': [...], 'trips': [...], 'stops': [...]}."""
    cur.execute("SELECT endpoint, payload FROM traccar_raw WHERE lote_id=%s ORDER BY id", (lote_id,))
    por_endpoint = {}
    for endpoint, payload in cur.fetchall():
        por_endpoint.setdefault(endpoint, []).append(payload)
    return {clave: por_endpoint.get(endpoint, []) for clave, endpoint in TRACCAR_ENDPOINTS.items()}


# ---------------------------------------------------------------- rechazados
def reject(cur, lote_id, entidad, fuente_id, motivo, payload):
    """Fila rechazada por calidad (queda en staging, no en el DWH). Una por (entidad, fuente_id, motivo):
    si vuelve a fallar se actualiza y queda otra vez sin resolver."""
    cur.execute(
        """INSERT INTO rechazados (entidad, fuente_id, motivo, payload, lote_id)
           VALUES (%s,%s,%s,%s::jsonb,%s)
           ON CONFLICT (entidad, fuente_id, motivo) DO UPDATE
           SET payload=EXCLUDED.payload, lote_id=EXCLUDED.lote_id, resuelto_utc=NULL""",
        (entidad, str(fuente_id), motivo, _dump(payload), lote_id))


def resolver_rechazos(cur, lote_id):
    """Los rechazos de entidades de Odoo que este lote no repitio estan resueltos (el registro se corrigio)."""
    cur.execute("UPDATE rechazados SET resuelto_utc=now() "
                "WHERE resuelto_utc IS NULL AND lote_id < %s AND entidad = ANY(%s)", (lote_id, list(ENTIDADES_ODOO)))
    return cur.rowcount


def resolver_rechazos_cargados(cur, entidad, fuente_ids):
    """Rechazos de Traccar (posicion, recorrido) cuyo registro ya se cargo en el DWH: quedan resueltos. Pasa cuando
    se corrige la causa (p. ej. el vehiculo recibe su dispositivo) y una corrida vuelve a traer el registro."""
    if not fuente_ids:
        return 0
    cur.execute("UPDATE rechazados SET resuelto_utc=now() "
                "WHERE resuelto_utc IS NULL AND entidad=%s AND fuente_id = ANY(%s)", (entidad, list(fuente_ids)))
    return cur.rowcount


# ---------------------------------------------------------------- retencion
def purge(cur, dias):
    """Borra crudo con mas de `dias` dias. Conserva siempre la ultima version de cada registro de Odoo (la
    transformacion la necesita) y los dispositivos de Traccar. dias <= 0: no borra. Devuelve conteos por tabla."""
    if not dias or dias <= 0:
        return {}
    out = {}
    cur.execute(
        """DELETE FROM odoo_raw o WHERE o.extraido_utc < now() - make_interval(days => %s)
           AND EXISTS (SELECT 1 FROM odoo_raw n WHERE n.modelo=o.modelo AND n.fuente_id=o.fuente_id AND n.id > o.id)""",
        (dias,))
    out["odoo_raw"] = cur.rowcount
    cur.execute("DELETE FROM traccar_raw WHERE endpoint <> 'devices' "
                "AND extraido_utc < now() - make_interval(days => %s)", (dias,))
    out["traccar_raw"] = cur.rowcount
    cur.execute("DELETE FROM rechazados WHERE detectado_utc < now() - make_interval(days => %s) "
                "AND (resuelto_utc IS NOT NULL OR entidad <> ALL(%s))", (dias, list(ENTIDADES_ODOO)))
    out["rechazados"] = cur.rowcount
    return out
