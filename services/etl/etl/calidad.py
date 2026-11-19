"""Calidad de la carga (etl report): conteos del DWH frente a Odoo y cobertura del vinculo entrega-GPS.

Una diferencia entre Odoo y el DWH no es por si sola un error: las filas rechazadas por las reglas de calidad no
llegan al DWH (ver la seccion de rechazos del reporte)."""
from . import config
from .load.facts import PEDIDOS_VENTA


def _dominio_simulado(prefijos):
    dom = []
    for i, p in enumerate(prefijos):
        if i < len(prefijos) - 1:
            dom.append("|")
        dom.append(("client_order_ref", "=like", p + "%"))
    return dom


def conteos_odoo(odoo_src):
    """{entidad: n} contados en Odoo (search_count). Lo que no se pueda contar queda fuera."""
    prefijos = list(config.prefijos_simulados())
    venta = [("state", "in", list(PEDIDOS_VENTA))]
    consultas = {
        "pedidos": ("sale.order", venta),
        "pedidos_simulados": ("sale.order", venta + _dominio_simulado(prefijos)),
        "entregas": ("logistica.entrega", []),
        "rutas": ("logistica.ruta", []),
        "rutas_simuladas": ("logistica.ruta", [("optimization_version", "in", list(config.rutas_simuladas()))]),
    }
    out = {}
    for clave, (modelo, dominio) in consultas.items():
        try:
            out[clave] = odoo_src.contar(modelo, dominio)
        except Exception:
            continue
    return out


def conteos_dwh(dcur):
    """{entidad: n} del DWH, con las mismas claves que conteos_odoo, mas la cobertura del vinculo GPS."""
    dcur.execute("""SELECT
        (SELECT count(DISTINCT pedido_id_odoo) FROM fact_ventas),
        (SELECT count(DISTINCT pedido_id_odoo) FROM fact_ventas WHERE procedencia = 'SIMULADO'),
        (SELECT count(*) FROM fact_entregas),
        (SELECT count(*) FROM fact_rutas),
        (SELECT count(*) FROM fact_rutas WHERE procedencia = 'SIMULADO'),
        (SELECT count(*) FROM fact_entregas WHERE completado_utc IS NOT NULL),
        (SELECT count(*) FROM fact_entregas WHERE completado_utc IS NOT NULL AND recorrido_sk IS NOT NULL),
        (SELECT count(*) FROM fact_rutas WHERE km_real IS NOT NULL)""")
    (pedidos, ped_sim, entregas, rutas, rutas_sim, cerradas, vinculadas, medidas) = dcur.fetchone()
    return {"pedidos": pedidos, "pedidos_simulados": ped_sim, "entregas": entregas, "rutas": rutas,
            "rutas_simuladas": rutas_sim, "entregas_cerradas": cerradas, "entregas_con_gps": vinculadas,
            "rutas_con_km_real": medidas}


def lineas(del_dwh, odoo):
    """Lineas de texto del reporte."""
    out = ["== Conteos DWH frente a Odoo" + ("" if odoo else " (Odoo no disponible: solo DWH)")]
    for clave in ("pedidos", "pedidos_simulados", "entregas", "rutas", "rutas_simuladas"):
        d = del_dwh.get(clave)
        if clave in odoo:
            marca = "ok" if odoo[clave] == d else "DIFERENTE (%+d)" % (d - odoo[clave])
            out.append("  %-18s dwh=%-7s odoo=%-7s %s" % (clave, d, odoo[clave], marca))
        else:
            out.append("  %-18s dwh=%s" % (clave, d))
    cerradas, con_gps = del_dwh["entregas_cerradas"], del_dwh["entregas_con_gps"]
    pct = "%.1f %%" % (100.0 * con_gps / cerradas) if cerradas else "sin entregas cerradas"
    out.append("== Vinculo entrega-GPS: %s de %s entregas cerradas (%s)" % (con_gps, cerradas, pct))
    out.append("== Rutas con km reales (GPS): %s de %s" % (del_dwh["rutas_con_km_real"], del_dwh["rutas"]))
    return out
