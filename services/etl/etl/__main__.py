"""CLI del ETL.

  python -m etl bootstrap [--reset]              crea bases, roles y tablas
  python -m etl run [--mode full|incremental]    una corrida
  python -m etl simulate [--dias N] [--seed S]   historico SIMULADO
  python -m etl schedule                         corre periodicamente (servicio)
  python -m etl report [--lotes N]               ultimas corridas y rechazos
  python -m etl purge [--dias N]                 retencion del crudo de staging
  python -m etl health [--max-min M]             0 si hubo una corrida correcta reciente

Codigos de salida: 0 correcto; 1 fallo; 2 configuracion incompleta; 3 otra corrida en curso."""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from . import config, db, pipeline, scheduler, simulate, staging


# ---------------------------------------------------------------- fuentes
def _sources():
    """Credenciales obligatorias primero (error claro y sin tocar la red); luego se conecta a cada fuente.
    Una fuente que no responde se omite con un aviso: la otra se carga igual."""
    odoo_password = config.require("ODOO_PASSWORD")
    traccar_password = config.require("TRACCAR_PASSWORD")
    odoo = traccar = None
    try:
        from .extract.odoo import OdooSource
        odoo = OdooSource(config.env("ODOO_URL", "http://odoo:8069"), config.env("ODOO_DB", "logistica_dev"),
                          config.env("ODOO_USER", "admin"), odoo_password)
    except Exception as exc:
        print("AVISO: Odoo no disponible, se omite (%s)" % exc, file=sys.stderr)
    try:
        from .extract.traccar import TraccarSource
        traccar = TraccarSource(config.env("TRACCAR_URL", "http://traccar:8082"),
                                config.env("TRACCAR_USER", "admin@logistica.local"), traccar_password,
                                timeout=config.entero("ETL_TRACCAR_TIMEOUT_S", 30, minimo=1))
        traccar.comprobar()
    except Exception as exc:
        print("AVISO: Traccar no disponible, se omite (%s)" % exc, file=sys.stderr)
        traccar = None
    return odoo, traccar


def _resumen(modo, conteos):
    return "ETL %s: extraidos=%s cargados=%s rechazados=%s omitidos=%s" % (
        modo, conteos["extraidos"], conteos["cargados"], conteos["rechazados"] or "ninguno",
        conteos["omitidos"] or "ninguno")


# ---------------------------------------------------------------- comandos
def cmd_bootstrap(a):
    if a.reset:
        print("Se borran y recrean las bases %s y %s." % (config.staging_db(), config.dwh_db()))
    hecho = db.bootstrap(stg_password=config.env("ETL_STG_PASSWORD"), dwh_password=config.env("DWH_ETL_PASSWORD"),
                         ro_password=config.env("DWH_DB_PASSWORD"), ml_password=config.env("DWH_ML_PASSWORD"),
                         reset=a.reset)
    for clave, rol, var, efecto in (
            ("staging_owner", config.staging_user(), "ETL_STG_PASSWORD",
             "no se crea el rol; la base queda a nombre del administrador"),
            ("dwh_owner", config.dwh_user(), "DWH_ETL_PASSWORD",
             "no se crea el rol; la base queda a nombre del administrador"),
            ("ro", config.RO_ROLE, "DWH_DB_PASSWORD", "BI/ML no tendran usuario de lectura"),
            ("ml", config.ML_ROLE, "DWH_ML_PASSWORD", "el ML no podra guardar la comparativa ni los pronosticos")):
        if not hecho[clave]:
            print("AVISO: %s no definida; no se crea el rol %s (%s)" % (var, rol, efecto), file=sys.stderr)
    print("Bases listas: %s, %s (esquema v%d)" % (config.staging_db(), config.dwh_db(), db.SCHEMA_VERSION))
    return 0


def _corrida(modo, dias=None):
    """Una corrida completa: valida la configuracion, conecta a las fuentes y a las bases, y ejecuta."""
    stg_params, dwh_params = config.staging_params(), config.dwh_params()   # antes de tocar la red o las bases
    odoo, traccar = _sources()
    import psycopg2
    stg_c = psycopg2.connect(**stg_params)
    try:
        dwh_c = psycopg2.connect(**dwh_params)
        try:
            if modo == "auto":
                modo = scheduler.decidir_modo(stg_c, config.horas_entre_completas())
            return _resumen(modo, pipeline.run_etl(stg_c, dwh_c, modo, odoo, traccar, dias=dias))
        finally:
            dwh_c.close()
    finally:
        stg_c.close()


def cmd_run(a):
    print(_corrida(a.mode, a.dias))
    return 0


def cmd_schedule(_a):
    return scheduler.run(lambda: _corrida("auto"))


def cmd_simulate(a):
    stg_params, dwh_params = config.staging_params(), config.dwh_params()
    import psycopg2
    stg_c, dwh_c = psycopg2.connect(**stg_params), psycopg2.connect(**dwh_params)
    try:
        with stg_c.cursor() as scur:
            lote, inicio = staging.new_lote(scur, "simulate")
        stg_c.commit()
        with dwh_c.cursor() as dcur:
            insertados = simulate.generar(dcur, lote, a.dias, a.seed, tz=config.zona_horaria())
            conteos = {"cargados": {"fact_recorridos_simulados": insertados}}
            with stg_c.cursor() as scur:
                fin = staging.close_lote(scur, lote, "ok", conteos)
            pipeline.registrar_ejecucion(dcur, lote, "simulate", inicio, fin, "ok", conteos)
        dwh_c.commit()
        stg_c.commit()
    finally:
        stg_c.close()
        dwh_c.close()
    print("Recorridos SIMULADO insertados: %d" % insertados)
    return 0


def cmd_report(a):
    conn = db.conectar_staging()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, modo, estado, inicio_utc, fin_utc, conteos, error FROM lote "
                        "ORDER BY id DESC LIMIT %s", (a.lotes,))
            print("== Ultimas corridas")
            for lote, modo, estado, inicio, fin, conteos, error in cur.fetchall():
                duracion = "%.1fs" % (fin - inicio).total_seconds() if fin else "en curso"
                print("  lote %-4d %-11s %-8s %s  %s" % (lote, modo, estado, inicio.strftime("%Y-%m-%d %H:%M:%SZ"),
                                                         duracion))
                if conteos.get("cargados"):
                    print("       cargados:   %s" % conteos["cargados"])
                if conteos.get("rechazados"):
                    print("       rechazados: %s" % conteos["rechazados"])
                if conteos.get("omitidos"):
                    print("       omitidos:   %s" % conteos["omitidos"])
                if error:
                    print("       error:      %s" % error)
            cur.execute("SELECT entidad, motivo, count(*) FROM rechazados WHERE resuelto_utc IS NULL "
                        "GROUP BY entidad, motivo ORDER BY entidad, motivo")
            filas = cur.fetchall()
            print("== Rechazos sin resolver" + ("" if filas else ": ninguno"))
            for entidad, motivo, cantidad in filas:
                print("  %-10s %-26s %d" % (entidad, motivo, cantidad))
            cur.execute("SELECT fuente, valor_utc FROM watermark ORDER BY fuente")
            print("== Marcas de agua")
            for fuente, valor in cur.fetchall():
                print("  %-32s %s" % (fuente, valor.strftime("%Y-%m-%d %H:%M:%SZ")))
    finally:
        conn.close()
    return 0


def cmd_purge(a):
    dias = a.dias if a.dias is not None else config.dias_retencion()
    conn = db.conectar_staging()
    try:
        with conn.cursor() as cur:
            borrados = staging.purge(cur, dias)
        conn.commit()
    finally:
        conn.close()
    print("Retencion de %d dias: %s" % (dias, borrados or "nada que borrar"))
    return 0


def cmd_health(a):
    limite = a.max_min if a.max_min is not None else 3 * config.intervalo_min()
    conn = db.conectar_dwh()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(fin_utc) FROM etl_ejecucion WHERE estado='ok' AND modo <> 'simulate'")
            ultima = cur.fetchone()[0]
    finally:
        conn.close()
    if ultima is None or datetime.now(timezone.utc) - ultima > timedelta(minutes=limite):
        print("Sin corrida correcta en los ultimos %d min (ultima: %s)" % (limite, ultima or "ninguna"),
              file=sys.stderr)
        return 1
    print("ok: ultima corrida correcta %s" % ultima.strftime("%Y-%m-%d %H:%M:%SZ"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="etl", description="ETL Odoo + Traccar -> staging -> DWH")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="crea bases, roles y tablas")
    b.add_argument("--reset", action="store_true", help="borra y recrea las dos bases (datos derivados)")
    b.set_defaults(fn=cmd_bootstrap)
    r = sub.add_parser("run", help="una corrida del ETL")
    r.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    r.add_argument("--dias", type=int, default=None, help="ventana inicial de Traccar (por defecto ETL_TRACCAR_DAYS)")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("simulate", help="historico SIMULADO de recorridos")
    s.add_argument("--dias", type=int, default=30)
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(fn=cmd_simulate)
    sub.add_parser("schedule", help="corre periodicamente (ETL_INTERVAL_MIN)").set_defaults(fn=cmd_schedule)
    rep = sub.add_parser("report", help="ultimas corridas, rechazos y marcas de agua")
    rep.add_argument("--lotes", type=int, default=10)
    rep.set_defaults(fn=cmd_report)
    p = sub.add_parser("purge", help="aplica la retencion del crudo de staging")
    p.add_argument("--dias", type=int, default=None, help="por defecto ETL_RETENTION_DAYS")
    p.set_defaults(fn=cmd_purge)
    h = sub.add_parser("health", help="0 si hubo una corrida correcta reciente")
    h.add_argument("--max-min", type=int, default=None, help="por defecto 3 x ETL_INTERVAL_MIN")
    h.set_defaults(fn=cmd_health)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except config.ConfigError as exc:
        print("ERROR de configuracion: %s" % exc, file=sys.stderr)
        return 2
    except db.EsquemaIncompatible as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    except db.Ocupado as exc:
        print("AVISO: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
