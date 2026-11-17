"""Panel BI (Streamlit) sobre el DWH. No consulta Odoo ni Traccar: solo la base del DWH (§10.3)."""
from datetime import date, timedelta

import streamlit as st

import olap

st.set_page_config(page_title="BI Logistica", layout="wide")
st.title("Analitica de rutas y entregas")

try:
    olap.params()
except olap.ConfigError as exc:
    st.error(str(exc))
    st.stop()

with st.sidebar:
    st.header("Filtros")
    rango = st.date_input("Rango de fechas", value=(date.today() - timedelta(days=30), date.today()))
    procedencia = st.multiselect("Procedencia", list(olap.PROCEDENCIAS), default=list(olap.PROCEDENCIAS))

if not procedencia:
    st.warning("Seleccione al menos una procedencia (REAL / SIMULADO).")
    st.stop()
desde, hasta = olap.rango_fechas(rango)

if olap.hay_simulados(procedencia):
    st.warning("Datos SIMULADOS: los resultados incluyen informacion generada para demostracion, no GPS real. "
               "La columna «procedencias» de cada tabla indica de donde sale cada fila.")


@st.cache_data(ttl=60, show_spinner=False)
def _cargar(desde, hasta, procedencia):
    conn = olap.conectar()
    try:
        return olap.indicadores(conn, desde, hasta, list(procedencia))
    finally:
        conn.close()


try:
    ind = _cargar(desde, hasta, tuple(procedencia))
except Exception as exc:  # conexion o permisos del rol dwh_ro
    st.error("No se pudo consultar el DWH: %s" % exc)
    st.stop()


def total(df, clave, col):
    """Valor de la fila de total del ROLLUP (clave en NULL); 0 si no hay datos."""
    return olap.total(df, clave, col)


def detalle(df, clave):
    """Filas sin la de total, indexadas por la clave (para graficar)."""
    return df.dropna(subset=[clave]).set_index(clave)


def tabla(df, **relleno):
    st.dataframe(df.fillna(relleno) if relleno else df, use_container_width=True, hide_index=True)


t_rec, t_rut, t_ent, t_ven, t_etl = st.tabs(
    ["Recorridos GPS", "Rutas: plan vs real", "Entregas", "Ventas", "Calidad del ETL"])

# ---------------------------------------------------------------- recorridos
with t_rec:
    c1, c2, c3 = st.columns(3)
    c1.metric("Distancia total (km)", total(ind["distancia_vehiculo"], "k_vehiculo", "distancia_km"))
    c2.metric("Duracion promedio (min)", total(ind["duracion_promedio"], "k_vehiculo", "duracion_min"))
    c3.metric("Paradas", total(ind["paradas"], "k_vehiculo", "paradas"))

    st.subheader("Distancia por vehiculo")
    d = ind["distancia_vehiculo"]
    if len(detalle(d, "k_vehiculo")):
        st.bar_chart(detalle(d, "k_vehiculo")["distancia_km"])
    tabla(d, k_vehiculo="TOTAL")

    st.subheader("Recorridos por dia y hora")
    h = ind["recorridos_dia_hora"]
    por_dia = h[h["k_fecha"].notna() & h["k_hora"].isna()]
    if len(por_dia):
        st.bar_chart(por_dia.set_index("k_fecha")["recorridos"])
    tabla(h[h["k_hora"].notna()])

    st.subheader("Duracion promedio y paradas por vehiculo")
    col_a, col_b = st.columns(2)
    with col_a:
        tabla(ind["duracion_promedio"], k_vehiculo="TOTAL")
    with col_b:
        tabla(ind["paradas"], k_vehiculo="TOTAL")

    st.subheader("Zonas visitadas")
    z = ind["zonas_visitadas"]
    if len(z):
        st.bar_chart(z.set_index("zona")["visitas"])
    tabla(z)

# ---------------------------------------------------------------- rutas
with t_rut:
    pr = ind["plan_real_vehiculo"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rutas", total(pr, "k_vehiculo", "rutas"))
    c2.metric("Km planificados", total(pr, "k_vehiculo", "km_planificado"))
    c3.metric("Km reales (GPS)", total(pr, "k_vehiculo", "km_real"))
    c4.metric("Paradas entregadas", "%s de %s" % (total(pr, "k_vehiculo", "entregadas"),
                                                 total(pr, "k_vehiculo", "paradas")))
    st.caption("Lo planificado sale del optimizador de rutas de Odoo. Lo real son las posiciones GPS del vehiculo "
               "entre el inicio y el fin de la ruta; sin al menos dos posiciones no hay distancia real.")
    st.subheader("Planificado y real por vehiculo")
    porv = detalle(pr, "k_vehiculo")
    if len(porv):
        st.bar_chart(porv[["km_planificado", "km_real"]])
    tabla(pr, k_vehiculo="TOTAL")
    st.subheader("Detalle por ruta")
    tabla(ind["rutas_plan_real"])
    st.subheader("Tiempos por parada, segun la zona de destino")
    tabla(ind["tiempos_parada"], k_zona="TOTAL")

# ---------------------------------------------------------------- entregas
with t_ent:
    cum = ind["cumplimiento"]
    e = ind["entregas_estado"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Entregas", total(e, "k_resultado", "entregas"))
    c2.metric("Cumplimiento a tiempo (%)", total(cum, "k_vehiculo", "pct_a_tiempo"))
    c3.metric("Evaluables", total(cum, "k_vehiculo", "evaluables"),
              help="Entregas hechas cuya ruta tenia inicio y duracion planificada.")
    st.subheader("Entregas por estado")
    if len(detalle(e, "k_resultado")):
        st.bar_chart(detalle(e, "k_resultado")["entregas"])
    tabla(e, k_resultado="TOTAL")
    st.subheader("Motivos de no entrega")
    tabla(ind["motivos_no_entrega"])
    st.subheader("Entregas por cliente y estado")
    tabla(ind["entregas_cliente"], k_cliente="TOTAL", k_resultado="(subtotal)")
    st.subheader("Cumplimiento de lo planificado por vehiculo")
    st.caption("A tiempo = entregada antes del limite del plan (inicio de la ruta + duracion planificada).")
    tabla(cum, k_vehiculo="TOTAL")

# ---------------------------------------------------------------- ventas
with t_ven:
    vc = ind["ventas_cliente"]
    c1, c2 = st.columns(2)
    c1.metric("Importe vendido", total(vc, "k_cliente", "importe"))
    c2.metric("Pedidos confirmados", total(vc, "k_cliente", "pedidos"))
    st.subheader("Ventas por producto")
    vp = ind["ventas_producto"]
    porp = detalle(vp, "k_producto")
    if len(porp):
        st.bar_chart(porp["importe"])
    tabla(vp, k_producto="TOTAL")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Ventas por cliente")
        tabla(vc, k_cliente="TOTAL")
    with col_b:
        st.subheader("Ventas por zona de entrega")
        tabla(ind["ventas_zona"], k_zona="TOTAL")

# ---------------------------------------------------------------- ETL
with t_etl:
    ej = ind["etl_ejecuciones"]
    if len(ej) == 0:
        st.info("No hay corridas del ETL en el periodo.")
    else:
        ultima = ej.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Ultima corrida", "%s (%s)" % (ultima["estado"], ultima["modo"]))
        c2.metric("Corridas con error", int((ej["estado"] == "error").sum()))
        c3.metric("Filas rechazadas", int(ej["filas_rechazadas"].sum()))
        st.caption("Ultima corrida iniciada: %s UTC. Las filas rechazadas no llegan al DWH; quedan en staging con "
                   "su motivo." % ultima["inicio_utc"])
        st.subheader("Rechazos por regla de calidad")
        tabla(ind["etl_rechazos"])
        st.subheader("Corridas")
        tabla(ej)
