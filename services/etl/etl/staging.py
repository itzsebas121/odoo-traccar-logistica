"""Staging: guarda el dato crudo (JSONB) con lote_id y extraido_utc."""
import json


def _dump(x):
    return json.dumps(x, default=str, ensure_ascii=False)


def new_lote(cur, modo):
    cur.execute("INSERT INTO etl_control.lote (modo) VALUES (%s) RETURNING id", (modo,))
    return cur.fetchone()[0]


def close_lote(cur, lote_id, estado, conteos):
    cur.execute("UPDATE etl_control.lote SET fin_utc=now(), estado=%s, conteos=%s::jsonb WHERE id=%s",
                (estado, _dump(conteos), lote_id))


def stage_odoo(cur, lote_id, modelo, rows):
    for r in rows:
        cur.execute("INSERT INTO stg.odoo_raw (lote_id, modelo, fuente_id, payload) VALUES (%s,%s,%s,%s::jsonb)",
                    (lote_id, modelo, str(r.get("id")), _dump(r)))


def stage_traccar(cur, lote_id, endpoint, rows):
    for r in rows:
        fid = r.get("id") or "%s@%s" % (r.get("deviceId"), r.get("startTime") or r.get("fixTime"))
        cur.execute("INSERT INTO stg.traccar_raw (lote_id, endpoint, fuente_id, payload) VALUES (%s,%s,%s,%s::jsonb)",
                    (lote_id, endpoint, str(fid), _dump(r)))
