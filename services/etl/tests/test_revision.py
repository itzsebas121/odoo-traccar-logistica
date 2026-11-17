"""Casos de la revision independiente del ETL (2026-11-16): cada prueba reproduce un hallazgo.

1 viajes partidos por bordes de tramo · 2 simulate repetido con otra ventana · 3 marca de viajes retenida sin
limite · 4 fechas futuras · 5 trozo de viaje tardio · 6 conductor del historico · 7 ruta abierta sin limite ·
8 coordenadas fuera de ruta en la vista del ML."""
from datetime import datetime, timedelta, timezone

from conftest import TZ, correr, q1, qall
from etl import simulate, staging

UTC = timezone.utc


def ts(h, m, dia=5):
    return datetime(2026, 11, dia, h, m, tzinfo=UTC)


def wm(conn, fuente):
    return q1(conn, "select valor_utc from watermark where fuente=%s", fuente)


def viaje(device, inicio, fin, km=1.0):
    return {"deviceId": device, "startTime": inicio.isoformat(), "endTime": fin.isoformat(), "distance": km * 1000,
            "averageSpeed": 8.0, "maxSpeed": 15.0, "startLat": -1.2417, "startLon": -78.6197,
            "endLat": -1.2230, "endLon": -78.6330}


# ---------------------------------------------------------------- 1
def test_un_viaje_recortado_no_acorta_el_ya_cargado(stg_con, dwh_con, odoo, traccar):
    """Traccar devuelve un viaje cortado cuando la ventana termina con el vehiculo en marcha. Ese trozo tiene el
    mismo inicio (mismo fuente_id) que el viaje completo ya cargado: no puede acortarlo."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    traccar.data["trips"][0].update(endTime="2026-11-05T13:45:00.000+00:00", distance=2000.0)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    fin, km = qall(dwh_con, "select fin_utc, distancia_km from fact_recorridos where fuente_id like 'trip:10:%'")[0]
    assert (fin, float(km)) == (ts(14, 0), 5.2)


# ---------------------------------------------------------------- 2
def test_simulate_con_otra_ventana_u_otro_dia_no_duplica(stg_con, dwh_con):
    """Correr `simulate --dias 5` hoy y `--dias 6` manana cubre dias comunes: cada dia de calendario debe generar
    los mismos viajes, sin dos juegos superpuestos del mismo vehiculo."""
    hoy = ts(12, 0, dia=10)
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _ = staging.new_lote(scur, "simulate")
        simulate.generar(dcur, lote, dias=5, seed=42, now=hoy, tz=TZ)
        simulate.generar(dcur, lote, dias=6, seed=42, now=hoy + timedelta(days=1), tz=TZ)
        simulate.generar(dcur, lote, dias=30, seed=42, now=hoy, tz=TZ)
    stg_con.commit()
    dwh_con.commit()
    assert q1(dwh_con, """select count(*) from fact_recorridos a join fact_recorridos b
                          on a.vehiculo_sk=b.vehiculo_sk and a.sk<b.sk
                          and a.inicio_utc < b.fin_utc and b.inicio_utc < a.fin_utc
                          where a.procedencia='SIMULADO' and b.procedencia='SIMULADO'""") == 0


def test_simulate_es_estable_por_dia(stg_con, dwh_con):
    """El dia 2026-11-08 sale igual se genere con una ventana de 3 dias o de 10."""
    def dia_8(dias, ahora):
        with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
            lote, _ = staging.new_lote(scur, "simulate")
            dcur.execute("delete from fact_recorridos where procedencia='SIMULADO'")
            simulate.generar(dcur, lote, dias=dias, seed=42, now=ahora, tz=TZ)
        stg_con.commit()
        dwh_con.commit()
        return qall(dwh_con, """select fuente_id, zona_destino_sk from fact_recorridos
                                where (inicio_utc at time zone 'America/Guayaquil')::date = date '2026-11-08'
                                order by 1""")
    corto = dia_8(3, ts(12, 0, dia=10))
    largo = dia_8(10, ts(12, 0, dia=12))
    assert corto and corto == largo


def test_simulate_corrige_un_viaje_con_el_mismo_id_y_otro_contenido(stg_con, dwh_con):
    """Una version anterior del generador pudo dejar un viaje con el mismo fuente_id (mismo vehiculo y minuto de
    inicio) pero otro destino: al regenerar, el contenido pasa a ser el del generador actual."""
    def generar():
        with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
            lote, _ = staging.new_lote(scur, "simulate")
            n = simulate.generar(dcur, lote, dias=3, seed=42, now=ts(12, 0, dia=10), tz=TZ)
        stg_con.commit()
        dwh_con.commit()
        return n
    generar()
    esperado = qall(dwh_con, "select fuente_id, zona_destino_sk, fin_utc, distancia_km from fact_recorridos order by 1")
    with dwh_con.cursor() as cur:
        cur.execute("""update fact_recorridos set zona_destino_sk = zona_origen_sk, fin_utc = fin_utc + interval '1 h',
                       distancia_km = 99 where fuente_id = (select min(fuente_id) from fact_recorridos)""")
    dwh_con.commit()
    assert generar() == 1                       # una fila corregida; las demas no se tocan
    assert qall(dwh_con, "select fuente_id, zona_destino_sk, fin_utc, distancia_km from fact_recorridos "
                         "order by 1") == esperado
    assert generar() == 0


# ---------------------------------------------------------------- 3
def test_marca_no_la_retiene_un_dispositivo_sin_vehiculo(stg_con, dwh_con, odoo, traccar):
    traccar.data["trips"].append(viaje(99, ts(15, 10), ts(15, 55)))     # dispositivo 99: ningun vehiculo
    correr(stg_con, dwh_con, "full", odoo, traccar, now=ts(16, 0))
    assert wm(stg_con, "traccar:recorridos") == ts(15, 30)


def test_marca_no_la_retiene_un_viaje_en_curso_eterno(stg_con, dwh_con, odoo, traccar):
    """Un GPS con deriva estando aparcado puede dar un viaje que nunca termina: la marca no espera mas de 12 h."""
    traccar.data["trips"].append(viaje(10, ts(1, 0), ts(15, 58)))
    correr(stg_con, dwh_con, "full", odoo, traccar, now=ts(16, 0))
    assert wm(stg_con, "traccar:recorridos") == ts(15, 30)


# ---------------------------------------------------------------- 4
def test_posicion_con_hora_futura_se_rechaza_y_no_mueve_la_marca(stg_con, dwh_con, odoo, traccar):
    """Traccar filtra `reports/route` por fixTime dentro de la ventana, asi que por ahi no deberia llegar una posicion
    futura; la regla es una defensa por si otra fuente la trae. Se inyecta despues del filtro de la fuente."""
    original = traccar.fetch

    def con_futura(*a, **kw):
        d = original(*a, **kw)
        d["positions"].append({"id": 3001, "deviceId": 10, "fixTime": "2026-11-07T09:00:00.000+00:00",
                               "latitude": -1.24, "longitude": -78.62, "speed": 1.0})
        return d
    traccar.fetch = con_futura
    correr(stg_con, dwh_con, "full", odoo, traccar)          # NOW = 2026-11-06 12:00
    assert q1(stg_con, "select motivo from rechazados where fuente_id='pos:10:3001'") == "fechas_incoherentes"
    assert wm(stg_con, "traccar:posiciones") == ts(15, 5)


def test_viaje_que_termina_en_el_futuro_se_rechaza(stg_con, dwh_con, odoo, traccar):
    traccar.data["trips"].append(viaje(10, ts(11, 0, dia=6), ts(18, 0, dia=6)))
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(stg_con, "select motivo from rechazados where entidad='recorrido'") == "fechas_incoherentes"
    assert wm(stg_con, "traccar:recorridos") == ts(15, 30)


# ---------------------------------------------------------------- 5
def test_trozo_tardio_de_un_viaje_se_limpia_al_reconstruirlo(stg_con, dwh_con, odoo, traccar):
    """El GPS pierde cobertura en marcha: primero se carga 13:30-13:50; al subir lo guardado, un incremental trae
    13:50-14:00 como viaje aparte; la completa siguiente reconstruye 13:30-14:00. El trozo debe desaparecer."""
    completo = dict(traccar.data["trips"][0])
    traccar.data["trips"][0].update(endTime="2026-11-05T13:50:00.000+00:00", distance=3500.0)
    correr(stg_con, dwh_con, "full", odoo, traccar, now=ts(14, 30))
    traccar.data["trips"][0] = viaje(10, ts(13, 50), ts(14, 0), km=1.7)
    correr(stg_con, dwh_con, "incremental", odoo, traccar, now=ts(15, 0))
    assert q1(dwh_con, "select count(*) from fact_recorridos where fuente_id like 'trip:10:%'") == 2
    traccar.data["trips"][0] = completo
    correr(stg_con, dwh_con, "full", odoo, traccar, now=ts(16, 0))
    assert qall(dwh_con, "select inicio_utc, fin_utc from fact_recorridos where fuente_id like 'trip:10:%'") == [
        (ts(13, 30), ts(14, 0))]
    assert q1(dwh_con, "select recorrido_sk is not null from fact_entregas where entrega_id_odoo=1") is True


# ---------------------------------------------------------------- 6
def test_conductor_del_historico_no_cambia_si_cambia_el_del_vehiculo(stg_con, dwh_con, odoo, traccar):
    """El viaje 15:00 del vehiculo 2 ocurre fuera de ruta (la RUTA/0002 cerro a las 14:00): su conductor es el que
    tenia el vehiculo entonces (Luis). Si despues el vehiculo pasa a Carlos, el historico no se reescribe."""
    odoo.data["logistica.ruta"][1].update(finished_at="2026-11-05 14:00:00", state="cerrada")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    sql = ("select c.nombre from fact_recorridos r join dim_conductor c on c.sk=r.conductor_sk "
           "where r.fuente_id like 'trip:11:%'")
    assert q1(dwh_con, sql) == "Luis"
    odoo.data["fleet.vehicle"][1].update(driver_id=[100, "Carlos"], write_date="2026-11-06 08:00:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert q1(dwh_con, sql) == "Luis"
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, sql) == "Luis"


# ---------------------------------------------------------------- 7
def test_ruta_que_queda_abierta_no_absorbe_los_viajes_del_dia_siguiente(stg_con, dwh_con, odoo, traccar):
    """La RUTA/0002 empezo el 5 a las 13:10 y nadie la cerro. Un viaje del vehiculo el 6 a las 10:00 (21 h despues)
    no es de esa ruta, y sus posiciones no cuentan para los km reales de la ruta."""
    traccar.data["trips"].append(viaje(11, ts(10, 0, dia=6), ts(10, 30, dia=6)))
    traccar.data["positions"].append({"id": 4001, "deviceId": 11, "fixTime": "2026-11-06T10:10:00.000+00:00",
                                      "latitude": -1.26, "longitude": -78.63, "speed": 5.0})
    correr(stg_con, dwh_con, "full", odoo, traccar)          # NOW = 2026-11-06 12:00
    assert q1(dwh_con, "select ruta_id_odoo from fact_recorridos "
                       "where fuente_id='trip:11:2026-11-06T10:00:00+00:00'") is None
    assert q1(dwh_con, "select ruta_id_odoo from fact_recorridos "
                       "where fuente_id='trip:11:2026-11-05T15:00:00+00:00'") == 2
    assert q1(dwh_con, "select posiciones_gps from fact_rutas where ruta_id_odoo=2") == 1


# ---------------------------------------------------------------- 8
def test_vista_ml_no_expone_coordenadas_fuera_de_ruta(stg_con, dwh_con, odoo, traccar):
    """Fuera de la operacion (sin ruta) el viaje puede empezar en el domicilio del conductor (spec 12): la vista que
    lee dwh_ro solo da sus zonas, no sus coordenadas."""
    odoo.data["logistica.ruta"][1].update(finished_at="2026-11-05 14:00:00", state="cerrada")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    filas = dict((r[0], r[1:]) for r in qall(
        dwh_con, "select vehiculo_codigo, en_ruta, lat_origen, lon_destino, zona_destino from v_ml_viajes"))
    assert filas["ABC-1234"] == (True, -1.2417, -78.6330, "ficoa")
    assert filas["DEF-5678"] == (False, None, None, filas["DEF-5678"][3])
    assert filas["DEF-5678"][3] is not None
