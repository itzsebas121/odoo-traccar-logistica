"""Pipeline completo contra bases desechables: dimensiones, hechos, vinculo, incremental, borrados y errores."""
import copy
from datetime import datetime, timezone

import psycopg2
import pytest

from conftest import NOW, FixtureOdoo, correr, q1, qall
from etl import db, staging
from etl.transform import normalize as n

UTC = timezone.utc


def ts(h, m, dia=5):
    return datetime(2026, 11, dia, h, m, tzinfo=UTC)


# ---------------------------------------------------------------- staging
def test_crudo_en_staging_y_bitacora(stg_con, dwh_con, odoo, traccar):
    conteos = correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(stg_con, "select count(*) from odoo_raw where modelo='logistica.entrega'") == 3
    assert q1(stg_con, "select count(*) from traccar_raw where endpoint='reports/trips'") == 2
    assert q1(stg_con, "select count(*) from traccar_raw where endpoint='reports/route'") == 4
    assert q1(stg_con, "select estado from lote") == "ok"
    assert q1(stg_con, "select count(*) from watermark") >= 10
    assert conteos["extraidos"]["logistica.entrega"] == 3 and conteos["extraidos"]["traccar.positions"] == 4
    assert conteos["cargados"] == {"fact_posicion_gps": 4, "fact_recorridos": 2, "fact_rutas": 2, "fact_paradas": 3,
                                   "fact_entregas": 3, "fact_ventas": 4}
    assert conteos["rechazados"] == {} and conteos["omitidos"] == []


def test_ejecucion_registrada_en_el_dwh(stg_con, dwh_con, odoo, traccar):
    """El BI no lee staging: la bitacora de cada corrida se copia a etl_ejecucion."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    lote = q1(stg_con, "select id from lote")
    modo, estado, cargados, fin = qall(dwh_con, "select modo, estado, cargados, fin_utc from etl_ejecucion "
                                                "where lote_id=%s", lote)[0]
    assert (modo, estado) == ("full", "ok") and fin is not None
    assert cargados["fact_entregas"] == 3


def test_staging_solo_guarda_versiones_nuevas(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    antes = q1(stg_con, "select count(*) from odoo_raw")
    correr(stg_con, dwh_con, "full", odoo, traccar)          # nada cambio: ni una fila mas
    assert q1(stg_con, "select count(*) from odoo_raw") == antes
    assert q1(stg_con, "select count(*) from traccar_raw") == 10
    odoo.data["logistica.entrega"][2].update(state="entregado", write_date="2026-11-05 14:10:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert q1(stg_con, "select count(*) from odoo_raw") == antes + 1
    assert q1(stg_con, "select count(*) from odoo_raw where modelo='logistica.entrega' and fuente_id='3'") == 2


# ---------------------------------------------------------------- dimensiones
def test_zonas_vienen_de_odoo(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    zonas = {r[0]: r[1:] for r in qall(dwh_con, "select codigo, nombre, latitud, longitud, zona_id_odoo, activa "
                                                "from dim_zona")}
    assert set(zonas) == {"centro", "ficoa", "huachi", "izamba", "otra"}
    assert zonas["ficoa"] == ("Ficoa", -1.2230, -78.6330, 2, True)
    # Odoo mueve un centroide y archiva una zona: el DWH lo refleja
    odoo.data["logistica.zona"][1].update(latitude=-1.2150, longitude=-78.6250, write_date="2026-11-06 08:00:00")
    odoo.data["logistica.zona"][3].update(active=False, write_date="2026-11-06 08:00:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert qall(dwh_con, "select latitud, longitud from dim_zona where codigo='ficoa'") == [(-1.2150, -78.6250)]
    assert q1(dwh_con, "select activa from dim_zona where codigo='izamba'") is False


def test_vehiculo_se_enlaza_por_el_id_de_traccar(stg_con, dwh_con, odoo, traccar):
    """fleet.vehicle.traccar_device_id apunta al registro traccar.device de Odoo (id 5), no al id de Traccar (10)."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert qall(dwh_con, "select placa, traccar_device_id, modelo, capacidad from dim_vehiculo order by placa") == [
        ("ABC-1234", 10, "Marca/Modelo A", 10), ("DEF-5678", 11, "Marca/Modelo A", 8)]
    assert q1(dwh_con, "select count(*) from fact_posicion_gps p join dim_vehiculo v on v.sk=p.vehiculo_sk "
                       "where v.placa='ABC-1234'") == 3


def test_vehiculo_sin_dispositivo_en_odoo_usa_el_nombre_de_la_placa(stg_con, dwh_con, odoo, traccar):
    odoo.data["fleet.vehicle"][0]["traccar_device_id"] = False
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select traccar_device_id from dim_vehiculo where placa='ABC-1234'") == 10   # device 'ABC-1234'
    traccar.data["devices"][0]["name"] = "otro nombre"
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select traccar_device_id from dim_vehiculo where placa='ABC-1234'") is None


def test_clientes_productos_y_conductores(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert qall(dwh_con, "select c.cliente_id_odoo, c.nombre, c.ciudad, z.codigo from dim_cliente c "
                         "left join dim_zona z on z.sk=c.zona_sk order by 1") == [
        (200, "Cliente A", "Ambato", "centro"), (201, "Cliente B", None, "ficoa"), (202, "Cliente C", None, "huachi")]
    assert qall(dwh_con, "select producto_id_odoo, nombre, referencia, precio_lista from dim_producto order by 1") == [
        (30, "[P1] Producto Uno", "P1", 10), (31, "Producto Dos", None, 12.5)]
    assert qall(dwh_con, "select conductor_id_odoo, nombre from dim_conductor order by 1") == [
        (100, "Carlos"), (101, "Luis")]


# ---------------------------------------------------------------- hechos
def test_recorridos_y_vista_de_entrenamiento(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    km, minutos, paradas, media, maxima = qall(
        dwh_con, "select distancia_km, duracion_min, num_paradas, velocidad_media_kmh, velocidad_max_kmh "
                 "from fact_recorridos where fuente_id like 'trip:10:%'")[0]
    # unidades: 5200 m -> 5.2 km; 10 y 25 nudos -> km/h
    assert (float(km), float(minutos), paradas, float(media), float(maxima)) == (5.2, 30.0, 1, 18.52, 46.3)
    assert qall(dwh_con, "select vehiculo_codigo, fecha_hora, zona_origen, zona_destino, procedencia "
                         "from v_viajes_entrenamiento where vehiculo_codigo='ABC-1234'") == [
        ("ABC-1234", "2026-11-05T13:30:00Z", "centro", "ficoa", "REAL")]


def test_rutas_plan_contra_real(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    r1 = qall(dwh_con, "select codigo, estado, fecha::text, km_planificado, min_planificado, fuente_distancia, km_real, "
                       "min_real, posiciones_gps, paradas_total, paradas_entregadas, paradas_fallidas, "
                       "paradas_pendientes, inicio_utc from fact_rutas where ruta_id_odoo=1")[0]
    esperado_km = (n.haversine_km(-1.2417, -78.6197, -1.2350, -78.6250)
                   + n.haversine_km(-1.2350, -78.6250, -1.2300, -78.6300))
    assert r1[:6] == ("RUTA/0001", "en_recorrido", "2026-11-05", 6, 45, "osrm")
    assert float(r1[6]) == pytest.approx(esperado_km, abs=0.002)
    assert r1[7] is None                       # ruta abierta: todavia no hay duracion real
    assert r1[8:13] == (3, 2, 1, 0, 1) and r1[13] == ts(13, 10)
    # ruta 2: una sola posicion en su ventana -> no hay distancia medible
    assert qall(dwh_con, "select km_real, posiciones_gps, paradas_fallidas from fact_rutas where ruta_id_odoo=2") == [
        (None, 1, 1)]
    # al cerrarse la ruta aparece la duracion real y la desviacion frente al plan
    odoo.data["logistica.ruta"][0].update(state="cerrada", finished_at="2026-11-05 14:10:00",
                                          write_date="2026-11-05 14:10:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert qall(dwh_con, "select min_real::float, desviacion_min_pct::float, placa, conductor, pct_entregado::float "
                         "from v_ruta_plan_vs_real where ruta_id_odoo=1") == [(60.0, 33.3, "ABC-1234", "Carlos", 50.0)]


def test_paradas_con_sus_tiempos(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    filas = qall(dwh_con, "select p.parada_id_odoo, p.orden, p.estado, p.posible_llegada_utc, p.llegada_utc, "
                          "p.cierre_utc, p.min_en_parada, p.min_desde_inicio_ruta, p.motivo, z.codigo, c.nombre "
                          "from fact_paradas p left join dim_zona z on z.sk=p.zona_sk "
                          "left join dim_cliente c on c.sk=p.cliente_sk order by 1")
    assert filas[0] == (1, 1, "entregado", ts(13, 37), ts(13, 38), ts(13, 40), 2, 30, None, "centro", "Cliente A")
    assert filas[1] == (2, 1, "no_entregado", None, ts(13, 48), ts(13, 50), 2, 40, "absent", "ficoa", "Cliente B")
    assert filas[2] == (3, 2, "pendiente", None, None, None, None, None, None, "huachi", "Cliente C")


def test_entregas_resultado_fechas_y_cumplimiento(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    res = {r[0]: r[1:] for r in qall(
        dwh_con, "select entrega_id_odoo, resultado, motivo, planificado_utc, completado_utc, limite_plan_utc, "
                 "a_tiempo, intentos, pedido_id_odoo, estado_odoo from fact_entregas")}
    # plan 13:10 + 45 min -> limite 13:55; cerro 13:40 -> a tiempo
    assert res[1] == ("entregado", None, ts(13, 10), ts(13, 40), ts(13, 55), True, 1, 11, "entregado")
    assert res[2] == ("no_entregado", "absent", ts(13, 10), ts(13, 50), ts(13, 40), None, 1, 12, "no_entregado")
    assert res[3] == ("pendiente", None, ts(13, 10), None, ts(13, 55), None, 1, 13, "en_recorrido")
    assert q1(dwh_con, "select sk from dim_tiempo where sk=2026110513") == 2026110513
    assert qall(dwh_con, "select fecha_local::text, hora_local, franja from dim_tiempo where sk=2026110513") == [
        ("2026-11-05", 8, "manana")]


def test_entrega_tardia_no_cumple(stg_con, dwh_con, odoo, traccar):
    odoo.data["logistica.ruta"][0]["planned_duration_min"] = 20.0        # limite 13:30, cerro 13:40
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select a_tiempo from fact_entregas where entrega_id_odoo=1") is False


def test_ventas_solo_pedidos_confirmados(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    filas = qall(dwh_con, "select v.linea_id_odoo, v.pedido_ref, c.nombre, p.referencia, z.codigo, v.cantidad, "
                          "v.subtotal, v.entrega_id_odoo, v.fecha_pedido_utc from fact_ventas v "
                          "join dim_cliente c on c.sk=v.cliente_sk join dim_producto p on p.sk=v.producto_sk "
                          "left join dim_zona z on z.sk=v.zona_sk order by 1")
    assert [f[0] for f in filas] == [501, 502, 503, 504]       # sin la nota (505) ni el pedido en borrador (506)
    assert filas[0] == (501, "S0001", "Cliente A", "P1", "centro", 2, 20, 1, ts(12, 25))
    assert filas[3][4] == "huachi"       # el pedido no tiene coordenadas: usa las de su entrega
    # el borrador se confirma y otro pedido se cancela
    odoo.data["sale.order"][3].update(state="sale", write_date="2026-11-05 15:00:00")
    odoo.data["sale.order"][1].update(state="cancel", write_date="2026-11-05 15:00:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert [r[0] for r in qall(dwh_con, "select linea_id_odoo from fact_ventas order by 1")] == [501, 502, 504, 506]


# ---------------------------------------------------------------- vinculo entrega-recorrido
def test_vinculo_solo_con_coincidencia(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    rows = dict(qall(dwh_con, "select entrega_id_odoo, recorrido_sk from fact_entregas"))
    assert rows[1] is not None          # vehiculo 1, cierre 13:40 dentro del recorrido 13:30-14:00
    assert rows[2] is None              # cierre 13:50 dentro de la ventana, pero su vehiculo no tiene ese recorrido
    assert rows[3] is None              # sin cierre
    assert q1(dwh_con, """select count(*) from fact_entregas f join fact_recorridos r on r.sk=f.recorrido_sk
                          where f.vehiculo_sk = r.vehiculo_sk""") == 1


def _agregar_ruta_b(odoo):
    """Ruta A (id 1) termina a las 13:25; ruta B (id 3, mismo vehiculo) va de 13:28 a 14:05 con la entrega 4."""
    odoo.data["logistica.ruta"][0]["finished_at"] = "2026-11-05 13:25:00"
    odoo.data["logistica.ruta.parada"][0].update(actual_arrival_at="2026-11-05 13:20:00",
                                                 completed_at="2026-11-05 13:40:00")
    ruta_b = copy.deepcopy(odoo.data["logistica.ruta"][0])
    ruta_b.update(id=3, name="RUTA/0003", state="cerrada", started_at="2026-11-05 13:28:00",
                  finished_at="2026-11-05 14:05:00", write_date="2026-11-05 14:05:00")
    odoo.data["logistica.ruta"].append(ruta_b)
    ent = copy.deepcopy(odoo.data["logistica.entrega"][0])
    ent.update(id=4, name="ENT/0004", route_id=3, write_date="2026-11-05 13:51:00")
    odoo.data["logistica.entrega"].append(ent)
    par = copy.deepcopy(odoo.data["logistica.ruta.parada"][0])
    par.update(id=4, route_id=[3, "RUTA/0003"], entrega_id=[4, "ENT/0004"], actual_arrival_at="2026-11-05 13:48:00",
               completed_at="2026-11-05 13:50:00", write_date="2026-11-05 13:51:00")
    odoo.data["logistica.ruta.parada"].append(par)


def test_vinculo_exige_ventana_de_ruta(stg_con, dwh_con, odoo, traccar):
    """Entrega de la ruta A que cierra dentro de un recorrido de la ruta B (mismo vehiculo): NO se vincula."""
    _agregar_ruta_b(odoo)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    rows = dict(qall(dwh_con, "select entrega_id_odoo, recorrido_sk from fact_entregas"))
    # el recorrido 13:30-14:00 contiene el cierre de la entrega 1 (13:40), pero no se solapa con la ruta A (13:10-13:25)
    assert rows[1] is None
    assert rows[4] is not None          # la entrega 4 es de la ruta B (13:28-14:05), que si se solapa
    assert q1(dwh_con, "select vehiculo_sk from fact_recorridos where sk=%s", rows[4]) == \
        q1(dwh_con, "select vehiculo_sk from fact_entregas where entrega_id_odoo=4")


def test_recorrido_en_curso_se_carga_cuando_termina(stg_con, dwh_con, odoo, traccar):
    """A las 14:05 el viaje 13:30-14:00 pudo no haber terminado (Traccar lo corta en 'ahora'): se deja para
    despues. La marca de agua no lo salta y la corrida siguiente lo carga completo y vincula la entrega."""
    res = correr(stg_con, dwh_con, "full", odoo, traccar, now=ts(14, 5))
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 0
    assert "recorridos en curso (se cargan al terminar): 1" in res["omitidos"]
    assert wm(stg_con, "traccar:recorridos") is None
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is None
    correr(stg_con, dwh_con, "incremental", odoo, traccar, now=ts(14, 30))
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 1
    assert wm(stg_con, "traccar:recorridos") == ts(14, 0)
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is not None


def test_marca_de_viajes_no_salta_un_viaje_en_curso_de_otro_vehiculo(stg_con, dwh_con, odoo, traccar):
    """La marca de agua de viajes es una sola para todos los dispositivos. Si el vehiculo 11 tiene un viaje en curso
    (15:00-15:30, omitido a las 15:35) y el 10 termino otro despues de que aquel empezara (15:05-15:20), la marca
    no puede pasar de 15:00: si no, la corrida siguiente pierde el viaje del 11 (o lo carga cortado)."""
    traccar.data["trips"].append({"deviceId": 10, "startTime": "2026-11-05T15:05:00.000+00:00",
                                  "endTime": "2026-11-05T15:20:00.000+00:00", "distance": 1500.0,
                                  "averageSpeed": 8.0, "maxSpeed": 15.0, "startLat": -1.2230, "startLon": -78.6330,
                                  "endLat": -1.2417, "endLon": -78.6197})
    res = correr(stg_con, dwh_con, "full", odoo, traccar, now=ts(15, 35))
    assert "recorridos en curso (se cargan al terminar): 1" in res["omitidos"]
    assert wm(stg_con, "traccar:recorridos") == ts(15, 0)
    correr(stg_con, dwh_con, "incremental", odoo, traccar, now=ts(16, 0))
    assert qall(dwh_con, "select inicio_utc, fin_utc from fact_recorridos where fuente_id like 'trip:11:%'") == [
        (ts(15, 0), ts(15, 30))]
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 3


def test_vinculo_por_el_viaje_de_llegada(stg_con, dwh_con, odoo, traccar):
    """Una entrega larga parte el viaje: Traccar cierra el viaje al llegar (13:30-13:35) y el cierre (13:40) cae en
    la parada. Se vincula el viaje de llegada: mismo vehiculo, dentro de la ruta y terminado poco antes del cierre."""
    traccar.data["trips"][0].update(endTime="2026-11-05T13:35:00.000+00:00")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    sk = q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1")
    assert sk is not None
    assert q1(dwh_con, "select fin_utc from fact_recorridos where sk=%s", sk) == ts(13, 35)


def test_vinculo_por_llegada_exige_tolerancia_y_ventana(stg_con, dwh_con, odoo, traccar):
    # viaje terminado 35 min antes del cierre (13:40): fuera de la tolerancia de 30 min
    odoo.data["logistica.ruta"][0]["started_at"] = "2026-11-05 12:50:00"
    traccar.data["trips"][0].update(startTime="2026-11-05T12:55:00.000+00:00",
                                    endTime="2026-11-05T13:05:00.000+00:00")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is None


def test_vinculo_por_llegada_no_usa_viajes_de_antes_de_la_ruta(stg_con, dwh_con, odoo, traccar):
    # el viaje 13:00-13:08 termino antes de que empezara la ruta (13:10): no es de esta ruta
    traccar.data["trips"][0].update(startTime="2026-11-05T13:00:00.000+00:00",
                                    endTime="2026-11-05T13:08:00.000+00:00")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is None


def test_recorrido_lleva_su_ruta_conductor_y_coordenadas(stg_con, dwh_con, odoo, traccar):
    """El viaje 13:30 del vehiculo 1 empezo durante la RUTA/0001: lleva esa ruta y su conductor, aunque el vehiculo
    tenga hoy otro conductor. El viaje 15:00 del vehiculo 2 tambien cae en su ruta abierta (desde 13:10)."""
    odoo.data["fleet.vehicle"][0]["driver_id"] = [101, "Luis"]       # el vehiculo cambio de conductor despues
    correr(stg_con, dwh_con, "full", odoo, traccar)
    fila = qall(dwh_con, "select r.ruta_id_odoo, c.nombre, r.lat_origen, r.lon_origen, r.lat_destino, r.lon_destino "
                         "from fact_recorridos r left join dim_conductor c on c.sk=r.conductor_sk "
                         "where r.fuente_id like 'trip:10:%'")[0]
    assert fila == (1, "Carlos", -1.2417, -78.6197, -1.2230, -78.6330)
    assert q1(dwh_con, "select ruta_id_odoo from fact_recorridos where fuente_id like 'trip:11:%'") == 2
    # sin ruta en curso el viaje queda sin ruta y con el conductor del vehiculo
    odoo.data["logistica.ruta"][1].update(finished_at="2026-11-05 14:00:00", write_date="2026-11-05 16:00:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert qall(dwh_con, "select r.ruta_id_odoo, c.nombre from fact_recorridos r "
                         "left join dim_conductor c on c.sk=r.conductor_sk where r.fuente_id like 'trip:11:%'") == [
        (None, "Luis")]


def test_vistas_para_el_ml(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    fila = qall(dwh_con, """select vehiculo_codigo, conductor, fecha_hora, fecha_local::text, hora_local,
                                   dia_semana_local, franja, fin_de_semana, zona_origen, zona_destino,
                                   distancia_km::float, duracion_min::float, ruta_id_odoo, en_ruta,
                                   entregas_vinculadas, procedencia
                            from v_ml_viajes where vehiculo_codigo='ABC-1234'""")[0]
    assert fila == ("ABC-1234", "Carlos", "2026-11-05T13:30:00Z", "2026-11-05", 8, 4, "manana", False, "centro",
                    "ficoa", 5.2, 30.0, 1, True, 1, "REAL")
    # transiciones de parada a parada: la ruta 1 sale de la bodega (zona centro) a la parada 1 (centro)
    assert qall(dwh_con, """select ruta_id_odoo, orden, zona_origen, zona_destino, hora_local, resultado
                            from v_ml_transiciones_paradas order by ruta_id_odoo, orden""") == [
        (1, 1, None, "centro", 8, "entregado"), (2, 1, None, "ficoa", 8, "no_entregado")]


def test_tramo_de_un_recorrido_ya_cargado_no_se_duplica(stg_con, dwh_con, odoo, traccar):
    """Si la ventana pedida empieza a mitad de un viaje, Traccar devuelve solo su final, con otra hora de inicio."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    tramo = copy.deepcopy(traccar.data["trips"][0])
    tramo.update(startTime="2026-11-05T13:45:00.000+00:00", distance=2000.0)       # final del viaje 13:30-14:00
    traccar.data["trips"].append(tramo)
    res = correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 2
    assert float(q1(dwh_con, "select distancia_km from fact_recorridos where fuente_id like 'trip:10:%'")) == 5.2
    assert "tramos de recorridos ya cargados: 1" in res["omitidos"]
    assert q1(stg_con, "select count(*) from rechazados") == 0


# ---------------------------------------------------------------- incremental, borrados y errores
TABLAS = ("fact_recorridos", "fact_entregas", "fact_posicion_gps", "fact_rutas", "fact_paradas", "fact_ventas",
          "dim_vehiculo", "dim_conductor", "dim_cliente", "dim_producto", "dim_zona", "dim_tiempo")


def conteos(stg_con, dwh_con):
    c = {t: q1(dwh_con, "select count(*) from %s" % t) for t in TABLAS}
    c["rechazados"] = q1(stg_con, "select count(*) from rechazados")
    return c


def wm(conn, fuente):
    return q1(conn, "select valor_utc from watermark where fuente=%s", fuente)


def test_carga_incremental_idempotente(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    base = conteos(stg_con, dwh_con)
    w1 = wm(stg_con, "odoo:logistica.entrega")
    assert w1 == ts(13, 51)
    assert wm(stg_con, "traccar:posiciones") == ts(15, 5) and wm(stg_con, "traccar:recorridos") == ts(15, 30)

    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert conteos(stg_con, dwh_con) == base
    assert wm(stg_con, "odoo:logistica.entrega") == w1
    # el incremental pidio solo lo posterior a la marca (menos el solape), no todo otra vez
    assert dict(odoo.pedidos)["logistica.entrega"] == datetime(2026, 11, 5, 13, 50, 55, tzinfo=UTC)
    # posiciones: desde la ultima vista menos el solape; viajes: desde el fin del ultimo viaje, sin solape
    assert traccar.ventanas[-1] == (ts(14, 55), ts(15, 30), NOW)

    nueva = copy.deepcopy(odoo.data["logistica.entrega"][0])
    nueva.update(id=4, name="ENT/0004", write_date="2026-11-05 15:00:00", state="preparado", route_id=0)
    odoo.data["logistica.entrega"].append(nueva)
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert q1(dwh_con, "select count(*) from fact_entregas") == base["fact_entregas"] + 1
    assert qall(dwh_con, "select resultado, ruta_id_odoo, vehiculo_sk from fact_entregas where entrega_id_odoo=4") == [
        ("pendiente", None, None)]
    assert wm(stg_con, "odoo:logistica.entrega") > w1
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert q1(dwh_con, "select count(*) from fact_entregas") == base["fact_entregas"] + 1


def test_cambio_solo_en_la_ruta_actualiza_sus_entregas(stg_con, dwh_con, odoo, traccar):
    """Pendiente de la version anterior: si solo cambia la ruta, lo planificado de sus entregas tambien cambia."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select planificado_utc from fact_entregas where entrega_id_odoo=3") == ts(13, 10)
    odoo.data["logistica.ruta"][0].update(started_at="2026-11-05 13:20:00", planned_duration_min=10.0,
                                          write_date="2026-11-05 16:00:00")     # las entregas no se tocan
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert qall(dwh_con, "select planificado_utc, limite_plan_utc, a_tiempo from fact_entregas "
                         "where entrega_id_odoo in (1,3) order by entrega_id_odoo") == [
        (ts(13, 20), ts(13, 30), False), (ts(13, 20), ts(13, 30), None)]


def test_corrida_completa_detecta_borrados(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    del odoo.data["logistica.ruta.parada"][2]         # replanificaron: la parada 3 ya no existe
    del odoo.data["sale.order.line"][0]
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert q1(dwh_con, "select count(*) from fact_paradas") == 3      # el incremental no ve los borrados
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert [r[0] for r in qall(dwh_con, "select parada_id_odoo from fact_paradas order by 1")] == [1, 2]
    assert q1(dwh_con, "select paradas_total from fact_rutas where ruta_id_odoo=1") == 1
    assert q1(dwh_con, "select intentos from fact_entregas where entrega_id_odoo=3") == 0
    assert q1(dwh_con, "select count(*) from fact_ventas where linea_id_odoo=501") == 0
    assert q1(stg_con, "select count(*) from odoo_raw where eliminado") == 2


def test_ruta_cancelada_no_cuenta_como_intento(stg_con, dwh_con, odoo, traccar):
    odoo.data["logistica.ruta"][0].update(state="cancelada")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert qall(dwh_con, "select intentos, vehiculo_sk is null from fact_entregas where entrega_id_odoo=3") == [
        (0, False)]       # sin parada vigente; conserva la ruta que la entrega declara (route_id = 1)


def test_modelos_odoo_ausentes_se_omiten(stg_con, dwh_con, traccar):
    base = FixtureOdoo().data
    odoo = FixtureOdoo({m: base[m] for m in ("fleet.vehicle", "traccar.device", "logistica.zona")})
    res = correr(stg_con, dwh_con, "full", odoo, traccar)
    assert "logistica.entrega" in res["omitidos"] and "sale.order" in res["omitidos"]
    assert q1(dwh_con, "select count(*) from fact_entregas") == 0
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 2


def test_fuente_caida_se_omite_y_no_borra_nada(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    base = conteos(stg_con, dwh_con)
    res = correr(stg_con, dwh_con, "full", None, None)
    assert res["omitidos"] == ["odoo", "traccar"]
    assert conteos(stg_con, dwh_con) == base


def test_error_de_carga_marca_el_lote_y_no_avanza_marcas(stg_con, dwh_con, odoo, traccar):
    with dwh_con.cursor() as cur:
        cur.execute("drop table fact_posicion_gps cascade")      # fuerza un fallo en la carga del DWH
    dwh_con.commit()
    with pytest.raises(psycopg2.Error):
        correr(stg_con, dwh_con, "full", odoo, traccar)
    estado, error = qall(stg_con, "select estado, error from lote")[0]
    assert estado == "error" and "fact_posicion_gps" in error
    assert q1(stg_con, "select count(*) from watermark") == 0
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 0          # el DWH no quedo a medias
    assert qall(dwh_con, "select estado from etl_ejecucion") == [("error",)]
    # el candado se libero: la siguiente corrida puede empezar
    db.tomar_candado(stg_con)
    db.soltar_candado(stg_con)


def test_una_sola_corrida_a_la_vez(dbs, stg_con, dwh_con, odoo, traccar):
    otra = dbs.connect(dbs.stg_db)
    try:
        db.tomar_candado(otra)
        with pytest.raises(db.Ocupado):
            correr(stg_con, dwh_con, "full", odoo, traccar)
        assert q1(stg_con, "select count(*) from lote") == 0
        db.soltar_candado(otra)
        correr(stg_con, dwh_con, "full", odoo, traccar)
        assert q1(stg_con, "select estado from lote") == "ok"
    finally:
        otra.close()


def test_retencion_conserva_la_ultima_version(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    odoo.data["logistica.entrega"][2].update(state="entregado", write_date="2026-11-05 14:10:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    with stg_con.cursor() as cur:
        cur.execute("update odoo_raw set extraido_utc = now() - interval '40 days'")
        cur.execute("update traccar_raw set extraido_utc = now() - interval '40 days'")
        vivos = len([1 for filas in staging.snapshot_odoo(cur).values() for _ in filas])
        assert staging.purge(cur, 0) == {}                # 0 dias = no borra
        borrados = staging.purge(cur, 30)
        assert borrados["odoo_raw"] == 1                  # solo la version vieja de la entrega 3
        assert borrados["traccar_raw"] == 8               # posiciones, viajes y paradas; los dispositivos quedan
        assert len([1 for filas in staging.snapshot_odoo(cur).values() for _ in filas]) == vivos
    stg_con.commit()
    base = conteos(stg_con, dwh_con)
    correr(stg_con, dwh_con, "incremental", odoo, traccar)        # el DWH no pierde nada tras la purga
    assert conteos(stg_con, dwh_con) == base
