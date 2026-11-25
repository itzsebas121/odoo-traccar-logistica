"""Orquestacion de una corrida: fuentes -> staging -> transformacion -> DWH (spec 10.1 y 10.2).

Dos conexiones independientes, sin SQL entre bases: `stg_conn` (crudo, lotes, marcas de agua, rechazados) y
`dwh_conn` (dimensiones y hechos)."""
import json
from datetime import datetime, timedelta, timezone

from . import config, db, staging
from .extract.odoo import MODELS
from .load import dimensions, facts, link
from .transform import normalize as n

# Solape de la extraccion incremental: repetir un registro es inocuo (se compara su huella); saltarlo no.
SOLAPE_ODOO = timedelta(seconds=5)
SOLAPE_POSICIONES = timedelta(minutes=10)
# Marcas de agua de Traccar. Las posiciones se piden desde la ultima vista (menos el solape). Los viajes, desde
# el fin del ultimo viaje cargado, sin solape: ese instante cae en una parada, asi que ningun viaje sale cortado.
MARCA_POSICIONES = "traccar:posiciones"
MARCA_RECORRIDOS = "traccar:recorridos"
# Entidad del informe de calidad de cada endpoint de Traccar que llega a una tabla de hechos.
ENTIDAD_TRACCAR = {"positions": "posicion", "trips": "recorrido"}
MAX_ERROR = 2000
# Parametros de Odoo que, si cambian, obligan a una corrida completa. logistica_demo reescribe create_date/write_date
# al pasado (_fechar) y anota hasta que dia cargo el historial: lo sembrado queda por detras de la marca de agua.
PARAMETROS_FULL = ("logistica_demo.historial_hasta",)


def _max(a, b):
    return b if a is None or (b is not None and b > a) else a


def parametros_odoo(odoo_src):
    """{clave: valor} de PARAMETROS_FULL; {} si la fuente no esta o no sabe leer parametros."""
    leer = getattr(odoo_src, "parametro", None)
    if leer is None:
        return {}
    valores = {}
    for clave in PARAMETROS_FULL:
        try:
            valores[clave] = leer(clave)
        except Exception:   # sin acceso o error transitorio: no decide nada
            continue
    return valores


def motivo_full(scur, parametros):
    """Texto con los parametros que cambiaron desde la ultima corrida correcta, o None."""
    cambios = []
    for clave, valor in parametros.items():
        existe, antes = staging.get_estado(scur, "odoo:" + clave)
        if valor is not None and (not existe or antes != valor):
            cambios.append("%s: %s -> %s" % (clave, antes, valor))
    return "; ".join(cambios) or None


def extract_to_staging(scur, lote, modo, odoo_src, traccar_src, now, dias, extraidos, omitidos, duplicados=None):
    """Fase 1: fuentes -> staging. Devuelve las marcas de agua candidatas (todavia no se avanzan).
    `duplicados` recibe, por entidad, los registros repetidos que llegaron de Traccar (staging guarda uno)."""
    duplicados = {} if duplicados is None else duplicados
    incremental = modo == "incremental"
    marks = {}
    if odoo_src is None:
        omitidos.append("odoo")
    else:
        for model in MODELS:
            fuente = "odoo:" + model
            marca = staging.get_watermark(scur, fuente) if incremental else None
            try:
                data = odoo_src.fetch(model, marca - SOLAPE_ODOO if marca else None)
            except Exception as exc:  # modelo o campo inconsistente: se omite sin abortar el lote
                omitidos.append("%s (%s)" % (model, str(exc)[:80]))
                continue
            if data is None:
                omitidos.append(model)
                continue
            extraidos[model] = len(data)
            staging.stage_odoo(scur, lote, model, data)
            if marca is None:      # extraccion completa del modelo: lo que ya no viene, se borro en Odoo
                staging.marcar_eliminados(scur, lote, model, [r.get("id") for r in data])
            for r in data:
                marks[fuente] = _max(marks.get(fuente), n.parse_ts(r.get("write_date")))
    if traccar_src is None:
        omitidos.append("traccar")
    else:
        inicio = now - timedelta(days=dias)
        m_pos = staging.get_watermark(scur, MARCA_POSICIONES) if incremental else None
        m_rec = staging.get_watermark(scur, MARCA_RECORRIDOS) if incremental else None
        fetched = traccar_src.fetch(m_pos - SOLAPE_POSICIONES if m_pos else inicio, now, m_rec or inicio)
        for clave in staging.TRACCAR_ENDPOINTS:
            filas = fetched.get(clave) or []
            extraidos["traccar." + clave] = len(filas)
            unicas = staging.stage_traccar(scur, lote, clave, filas)
            if clave in ENTIDAD_TRACCAR:       # repetidos en la respuesta: staging guarda uno por registro
                duplicados[ENTIDAD_TRACCAR[clave]] = len(filas) - unicas
    return marks


def load_dwh(dcur, scur, ctx, odoo, traccar):
    """Fases 2 y 3: transforma y carga. Devuelve las marcas de agua de Traccar (None = no avanza)."""
    dimensions.load_dimensions(dcur, ctx, odoo, traccar)
    marcas = {}
    if traccar is not None:
        marcas = {MARCA_POSICIONES: facts.load_posiciones(dcur, scur, ctx, traccar),
                  MARCA_RECORRIDOS: facts.load_recorridos(dcur, scur, ctx, traccar)}
    rutas, paradas = facts.preparar_rutas(scur, ctx, odoo)
    entregas = facts.preparar_entregas(odoo)
    facts.load_rutas(dcur, ctx, odoo, rutas, paradas)
    facts.load_paradas(dcur, ctx, odoo, rutas, paradas, entregas)
    facts.load_entregas(dcur, scur, ctx, odoo, rutas, paradas, entregas)
    facts.load_ventas(dcur, scur, ctx, odoo, entregas)
    facts.medir_rutas(dcur, ctx)
    conductor_de_vehiculo = {ctx.vehiculo[vid]: ctx.conductor.get(cid)
                             for vid, cid in ctx.conductor_de_vehiculo.items() if vid in ctx.vehiculo}
    link.asignar_rutas_recorridos(dcur, ctx.now, conductor_de_vehiculo)
    link.link_entregas_recorridos(dcur, ctx.now)
    return marcas


def registrar_ejecucion(dcur, lote, modo, inicio, fin, estado, conteos, error=None):
    """Copia la corrida a etl_ejecucion (DWH), que es lo que puede leer el BI."""
    def j(x):
        return json.dumps(x, default=str, ensure_ascii=False)
    dcur.execute(
        """INSERT INTO etl_ejecucion (lote_id, modo, inicio_utc, fin_utc, estado, extraidos, cargados, rechazados,
                                      omitidos, calidad, error)
           VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)
           ON CONFLICT (lote_id) DO UPDATE SET fin_utc=EXCLUDED.fin_utc, estado=EXCLUDED.estado,
             extraidos=EXCLUDED.extraidos, cargados=EXCLUDED.cargados, rechazados=EXCLUDED.rechazados,
             omitidos=EXCLUDED.omitidos, calidad=EXCLUDED.calidad, error=EXCLUDED.error""",
        (lote, modo, inicio, fin, estado, j(conteos.get("extraidos", {})), j(conteos.get("cargados", {})),
         j(conteos.get("rechazados", {})), j(conteos.get("omitidos", [])), j(conteos.get("calidad", {})), error))


def run_etl(stg_conn, dwh_conn, modo, odoo_src, traccar_src, now=None, dias=None, tz=None, retencion=None):
    """modo: 'full' | 'incremental'. odoo_src.fetch(modelo, since) -> filas | None (modelo ausente);
    traccar_src.fetch(desde, hasta) -> dict. Cualquiera puede ser None (fuente no disponible).

    1) toma el candado; 2) extrae a staging y confirma; 3) lee de staging el estado actual de Odoo y las lecturas
    de Traccar del lote; 4) transforma, escribe en el DWH y confirma; 5) avanza las marcas de agua, cierra el lote
    y aplica la retencion. Si algo falla, el DWH no cambia, las marcas no avanzan y el lote queda 'error'.
    Toda la carga usa upserts: repetir una corrida es idempotente. Devuelve los conteos de la corrida."""
    now = now or datetime.now(timezone.utc)
    dias = dias or config.dias_ventana_traccar()
    tz = tz or config.zona_horaria()
    retencion = config.dias_retencion() if retencion is None else retencion
    conteos = {"extraidos": {}, "cargados": {}, "rechazados": {}, "omitidos": []}

    db.tomar_candado(stg_conn)
    try:
        scur = stg_conn.cursor()
        parametros = parametros_odoo(odoo_src)
        if modo == "incremental":
            motivo = motivo_full(scur, parametros)
            if motivo:
                modo = "full"
                conteos["motivo_full"] = motivo
        lote, inicio = staging.new_lote(scur, modo)
        stg_conn.commit()  # el lote existe aunque la corrida falle
        try:
            duplicados = {}
            marks = extract_to_staging(scur, lote, modo, odoo_src, traccar_src, now, dias, conteos["extraidos"],
                                       conteos["omitidos"], duplicados)
            stg_conn.commit()

            odoo = staging.snapshot_odoo(scur)
            traccar = staging.read_traccar(scur, lote) if traccar_src is not None else None
            ctx = dimensions.Contexto(lote, now, tz)
            ctx.cargados, ctx.rechazados, ctx.omitidos = conteos["cargados"], conteos["rechazados"], conteos["omitidos"]
            for entidad, cantidad in duplicados.items():   # entraron a la extraccion y se descartaron en staging
                ctx.entrada(entidad, cantidad)
                ctx.duplicados(entidad, cantidad)

            dcur = dwh_conn.cursor()
            marks.update(load_dwh(dcur, scur, ctx, odoo, traccar))
            conteos["calidad"] = ctx.calidad()
            fin = staging.close_lote(scur, lote, "ok", conteos)
            registrar_ejecucion(dcur, lote, modo, inicio, fin, "ok", conteos)
            dwh_conn.commit()

            for fuente, valor in marks.items():
                staging.advance_watermark(scur, fuente, valor)
            for clave, valor in parametros.items():
                staging.set_estado(scur, "odoo:" + clave, valor)
            staging.resolver_rechazos(scur, lote)
            staging.purge(scur, retencion)
            stg_conn.commit()
        except Exception as exc:
            dwh_conn.rollback()
            stg_conn.rollback()
            error = ("%s: %s" % (type(exc).__name__, exc))[:MAX_ERROR]
            scur = stg_conn.cursor()
            fin = staging.close_lote(scur, lote, "error", conteos, error)
            stg_conn.commit()
            try:    # la bitacora del DWH es informativa: si tampoco se puede escribir, manda el error original
                with dwh_conn.cursor() as dcur:
                    registrar_ejecucion(dcur, lote, modo, inicio, fin, "error", conteos, error)
                dwh_conn.commit()
            except Exception:
                dwh_conn.rollback()
            raise
    finally:
        try:
            stg_conn.rollback()
            db.soltar_candado(stg_conn)
        except Exception:
            pass
    return conteos
