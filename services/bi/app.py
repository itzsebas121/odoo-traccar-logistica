"""Panel BI (Streamlit) sobre el DWH. No consulta Odoo ni Traccar: solo el esquema dwh (§10.3)."""
from datetime import date, timedelta

import streamlit as st

import olap

st.set_page_config(page_title="BI Logistica", layout="wide")
st.title("Analitica de rutas y entregas")

try:
    olap.dsn()
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
desde, hasta = (rango if isinstance(rango, (tuple, list)) and len(rango) == 2 else (None, None))

if olap.hay_simulados(procedencia):
    st.warning("Datos SIMULADOS: los resultados incluyen informacion generada para demostracion, no GPS real.")


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
    fila = df[df[clave].isna()]
    return fila[col].iloc[0] if len(fila) else 0


c1, c2, c3, c4 = st.columns(4)
c1.metric("Distancia total (km)", total(ind["distancia_vehiculo"], "k_vehiculo", "distancia_km"))
c2.metric("Duracion promedio (min)", total(ind["duracion_promedio"], "k_vehiculo", "duracion_min"))
c3.metric("Paradas", total(ind["paradas"], "k_vehiculo", "paradas"))
c4.metric("Cumplimiento a tiempo (%)", total(ind["cumplimiento"], "k_vehiculo", "pct_a_tiempo"))

st.subheader("Distancia por vehiculo")
d = ind["distancia_vehiculo"]
st.bar_chart(d.dropna(subset=["k_vehiculo"]).set_index("k_vehiculo")["distancia_km"])
st.dataframe(d.fillna({"k_vehiculo": "TOTAL"}), use_container_width=True)

st.subheader("Recorridos por dia y hora")
h = ind["recorridos_dia_hora"]
por_dia = h[h["k_fecha"].notna() & h["k_hora"].isna()]
st.bar_chart(por_dia.set_index("k_fecha")["recorridos"])
por_hora = h[h["k_fecha"].isna() & h["k_hora"].isna()]
st.dataframe(h.fillna({"k_fecha": "TOTAL", "k_hora": -1}), use_container_width=True)

st.subheader("Duracion promedio y paradas por vehiculo")
col_a, col_b = st.columns(2)
col_a.dataframe(ind["duracion_promedio"].fillna({"k_vehiculo": "TOTAL"}), use_container_width=True)
col_b.dataframe(ind["paradas"].fillna({"k_vehiculo": "TOTAL"}), use_container_width=True)

st.subheader("Zonas visitadas")
z = ind["zonas_visitadas"]
st.bar_chart(z.set_index("zona")["visitas"])

st.subheader("Entregas por cliente y estado")
st.dataframe(ind["entregas_cliente"].fillna({"k_cliente": "TOTAL", "k_resultado": "(subtotal)"}),
             use_container_width=True)
e = ind["entregas_estado"]
st.bar_chart(e.dropna(subset=["k_resultado"]).set_index("k_resultado")["entregas"])

st.subheader("Cumplimiento de lo planificado por vehiculo")
st.dataframe(ind["cumplimiento"].fillna({"k_vehiculo": "TOTAL"}), use_container_width=True)
