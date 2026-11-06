"""Staging (base logistica_staging): crudo en JSONB con lote_id y extraido_utc, bitacora de lotes y rechazados.

Todas las funciones reciben un cursor de la conexion de staging."""
import json

# clave interna -> valor de traccar_raw.endpoint
TRACCAR_ENDPOINTS = {"devices": "devices", "positions": "reports/route", "trips": "reports/trips",
                     "stops": "reports/stops"}


def _dump(x):
    return json.dumps(x, default=str, ensure_ascii=False)


def new_lote(cur, modo):
    cur.execute("INSERT INTO lote (modo) VALUES (%s) RETURNING id", (modo,))
    return cur.fetchone()[0]


def close_lote(cur, lote_id, estado, conteos):
    cur.execute("UPDATE lote SET fin_utc=now(), estado=%s, conteos=%s::jsonb WHERE id=%s",
                (estado, _dump(conteos), lote_id))


def stage_odoo(cur, lote_id, modelo, rows):
    for r in rows:
        cur.execute("INSERT INTO odoo_raw (lote_id, modelo, fuente_id, payload) VALUES (%s,%s,%s,%s::jsonb)",
                    (lote_id, modelo, str(r.get("id")), _dump(r)))


def stage_traccar(cur, lote_id, clave, rows):
    endpoint = TRACCAR_ENDPOINTS[clave]
    for r in rows:
        fid = r.get("id") or "%s@%s" % (r.get("deviceId"), r.get("startTime") or r.get("fixTime"))
        cur.execute("INSERT INTO traccar_raw (lote_id, endpoint, fuente_id, payload) VALUES (%s,%s,%s,%s::jsonb)",
                    (lote_id, endpoint, str(fid), _dump(r)))


def read_odoo(cur, lote_id):
    """Filas crudas del lote, en orden de insercion: {modelo: [payload, ...]}."""
    cur.execute("SELECT modelo, payload FROM odoo_raw WHERE lote_id=%s ORDER BY id", (lote_id,))
    out = {}
    for modelo, payload in cur.fetchall():
        out.setdefault(modelo, []).append(payload)
    return out


def read_traccar(cur, lote_id):
    """Filas crudas del lote: {'devices': [...], 'positions': [...], 'trips': [...], 'stops': [...]}."""
    cur.execute("SELECT endpoint, payload FROM traccar_raw WHERE lote_id=%s ORDER BY id", (lote_id,))
    por_endpoint = {}
    for endpoint, payload in cur.fetchall():
        por_endpoint.setdefault(endpoint, []).append(payload)
    return {clave: por_endpoint.get(endpoint, []) for clave, endpoint in TRACCAR_ENDPOINTS.items()}


def reject(cur, lote_id, entidad, fuente_id, motivo, payload):
    """Fila rechazada por calidad (queda en staging, no en el DWH). Idempotente por (entidad, fuente_id, motivo)."""
    cur.execute(
        """INSERT INTO rechazados (entidad, fuente_id, motivo, payload, lote_id)
           VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT (entidad, fuente_id, motivo) DO NOTHING""",
        (entidad, str(fuente_id), motivo, _dump(payload), lote_id))
