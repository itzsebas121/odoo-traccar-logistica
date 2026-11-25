"""Reglas de calidad dentro del pipeline: lo que no pasa va a `rechazados` (staging) y no llega al DWH."""
import copy

from conftest import correr, q1, qall


def rechazos(stg_con, **filtro):
    cond = " and ".join("%s='%s'" % kv for kv in filtro.items()) or "true"
    return q1(stg_con, "select count(*) from rechazados where resuelto_utc is null and " + cond)


def test_rechaza_coordenadas_invalidas(stg_con, dwh_con, odoo, traccar):
    traccar.data["positions"][0]["latitude"] = 91
    res = correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, motivo="coordenadas_invalidas", entidad="posicion") == 1
    assert q1(dwh_con, "select count(*) from fact_posicion_gps") == 3
    assert res["rechazados"] == {"coordenadas_invalidas": 1}
    assert q1(dwh_con, "select rechazados->>'coordenadas_invalidas' from etl_ejecucion") == "1"


def test_rechaza_posicion_con_nulos(stg_con, dwh_con, odoo, traccar):
    traccar.data["positions"][0]["latitude"] = None
    traccar.data["positions"][1]["fixTime"] = "2026-11-05T13:35:00.000+00:00"
    del traccar.data["positions"][2]["speed"]            # la velocidad es opcional
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, motivo="nulos_obligatorios") == 1
    assert q1(dwh_con, "select count(*) from fact_posicion_gps") == 3
    assert q1(dwh_con, "select count(*) from fact_posicion_gps where velocidad_kmh is null") == 1


def test_posicion_con_desfase_horario_queda_en_utc(stg_con, dwh_con, odoo, traccar):
    """Traccar responde con desfase -05:00: 08:30 local es 13:30 UTC, dentro de la ruta 1."""
    for p, hora in zip(traccar.data["positions"][:3], ("08:30", "08:35", "08:40")):
        p["fixTime"] = "2026-11-05T%s:00.000-05:00" % hora
    traccar.data["trips"][0].update(startTime="2026-11-05T08:30:00.000-05:00", endTime="2026-11-05T09:00:00.000-05:00")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert [r[0].isoformat() for r in qall(dwh_con, "select gps_time_utc at time zone 'UTC' from fact_posicion_gps "
                                                    "where fuente_id like 'pos:10:%' order by 1")] == [
        "2026-11-05T13:30:00", "2026-11-05T13:35:00", "2026-11-05T13:40:00"]
    assert q1(dwh_con, "select posiciones_gps from fact_rutas where ruta_id_odoo=1") == 3
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is not None


def test_rechaza_fechas_incoherentes(stg_con, dwh_con, odoo, traccar):
    bad = copy.deepcopy(traccar.data["trips"][0])
    bad["startTime"], bad["endTime"] = "2026-11-05T16:00:00.000+00:00", "2026-11-05T15:30:00.000+00:00"
    traccar.data["trips"].append(bad)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, motivo="fechas_incoherentes", entidad="recorrido") == 1
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 2


def test_rechaza_velocidad_anomala(stg_con, dwh_con, odoo, traccar):
    traccar.data["positions"][1]["speed"] = 100  # nudos = 185.2 km/h
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, motivo="velocidad_anomala") == 1
    assert q1(dwh_con, "select count(*) from fact_posicion_gps where velocidad_kmh > 150") == 0


def test_rechaza_dispositivo_sin_vehiculo(stg_con, dwh_con, odoo, traccar):
    traccar.data["positions"].append({"id": 2001, "deviceId": 99, "fixTime": "2026-11-05T13:31:00.000+00:00",
                                      "latitude": -1.24, "longitude": -78.62, "speed": 1.0})
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, motivo="dispositivo_sin_vehiculo", fuente_id="pos:99:2001") == 1
    assert q1(dwh_con, "select count(*) from fact_posicion_gps") == 4


def test_rechazo_de_traccar_se_resuelve_al_cargarse(stg_con, dwh_con, odoo, traccar):
    """El vehiculo 2 todavia no tiene su dispositivo: posiciones y viajes del 11 se rechazan. Cuando se enlaza, la
    corrida completa los carga y sus rechazos quedan resueltos (ya no figuran en el informe ni en el BI)."""
    odoo.data["fleet.vehicle"][1]["traccar_device_id"] = False
    traccar.data["devices"][1]["name"] = "sin placa"
    correr(stg_con, dwh_con, "full", odoo, traccar)
    pendientes = rechazos(stg_con, motivo="dispositivo_sin_vehiculo")
    assert pendientes >= 2                                           # al menos una posicion y un viaje
    odoo.data["fleet.vehicle"][1].update(traccar_device_id=[6, "GPS DEF"], write_date="2026-11-05 16:00:00")
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, motivo="dispositivo_sin_vehiculo") == 0
    assert q1(stg_con, "select count(*) from rechazados where resuelto_utc is not null") == pendientes
    assert q1(dwh_con, "select count(*) from fact_recorridos where fuente_id like 'trip:11:%'") == 1


def test_duplicados_por_fuente(stg_con, dwh_con, odoo, traccar):
    traccar.data["positions"].append(copy.deepcopy(traccar.data["positions"][0]))
    traccar.data["trips"].append(copy.deepcopy(traccar.data["trips"][0]))
    odoo.data["logistica.entrega"].append(copy.deepcopy(odoo.data["logistica.entrega"][0]))
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select count(*) from fact_posicion_gps") == 4
    assert q1(dwh_con, "select count(*) from fact_recorridos") == 2
    assert q1(dwh_con, "select count(*) from fact_entregas") == 3
    assert rechazos(stg_con) == 0


def test_rechaza_ruta_con_fechas_incoherentes(stg_con, dwh_con, odoo, traccar):
    odoo.data["logistica.ruta"][0]["finished_at"] = "2026-11-05 13:00:00"  # antes de started_at (13:10)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, entidad="ruta", motivo="fechas_incoherentes") == 1
    assert [r[0] for r in qall(dwh_con, "select ruta_id_odoo from fact_rutas")] == [2]
    assert [r[0] for r in qall(dwh_con, "select parada_id_odoo from fact_paradas")] == [2]
    # sin ventana verificable de su ruta, la entrega 1 se carga pero no se vincula a ningun recorrido
    assert qall(dwh_con, "select recorrido_sk, vehiculo_sk from fact_entregas where entrega_id_odoo=1") == [(None, None)]


def test_rechazo_se_resuelve_cuando_el_dato_se_corrige(stg_con, dwh_con, odoo, traccar):
    odoo.data["logistica.ruta"][0]["finished_at"] = "2026-11-05 13:00:00"
    correr(stg_con, dwh_con, "full", odoo, traccar)
    correr(stg_con, dwh_con, "incremental", odoo, traccar)        # sigue mal: sigue sin resolver, sin duplicarse
    assert rechazos(stg_con, entidad="ruta") == 1
    assert q1(stg_con, "select count(*) from rechazados") == 1
    odoo.data["logistica.ruta"][0].update(finished_at="2026-11-05 14:10:00", write_date="2026-11-05 16:00:00")
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert rechazos(stg_con, entidad="ruta") == 0
    assert q1(stg_con, "select count(*) from rechazados where resuelto_utc is not null") == 1
    assert q1(dwh_con, "select count(*) from fact_rutas") == 2
    assert q1(dwh_con, "select recorrido_sk from fact_entregas where entrega_id_odoo=1") is not None


def test_rechaza_entrega_y_parada_incoherentes(stg_con, dwh_con, odoo, traccar):
    odoo.data["logistica.entrega"][1]["latitude"] = 95.0
    odoo.data["logistica.ruta.parada"][0]["actual_arrival_at"] = "2026-11-05 13:45:00"   # llega despues de cerrar
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, entidad="entrega", motivo="coordenadas_invalidas", fuente_id="2") == 1
    assert rechazos(stg_con, entidad="parada", motivo="fechas_incoherentes", fuente_id="1") == 1
    assert [r[0] for r in qall(dwh_con, "select entrega_id_odoo from fact_entregas order by 1")] == [1, 3]
    assert [r[0] for r in qall(dwh_con, "select parada_id_odoo from fact_paradas order by 1")] == [2, 3]


def test_entrega_sin_coordenadas_se_carga_sin_zona(stg_con, dwh_con, odoo, traccar):
    """Odoo deja 0,0 cuando el destino no tiene punto: no es un error, solo no hay zona."""
    odoo.data["logistica.entrega"][2].update(latitude=0.0, longitude=0.0, partner_id=False)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert qall(dwh_con, "select zona_sk, cliente_sk from fact_entregas where entrega_id_odoo=3") == [(None, None)]
    assert rechazos(stg_con) == 0


def test_rechaza_venta_con_importe_invalido(stg_con, dwh_con, odoo, traccar):
    odoo.data["sale.order.line"][0]["product_uom_qty"] = -2.0
    odoo.data["sale.order.line"][1]["product_id"] = False
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert rechazos(stg_con, entidad="venta", motivo="importe_invalido", fuente_id="501") == 1
    assert rechazos(stg_con, entidad="venta", motivo="nulos_obligatorios", fuente_id="502") == 1
    assert [r[0] for r in qall(dwh_con, "select linea_id_odoo from fact_ventas order by 1")] == [503, 504]


def test_informe_de_calidad_por_entidad(stg_con, dwh_con, odoo, traccar):
    """Spec 5.4.7: por entidad, registros de entrada, validos, transformados, rechazados y cargados."""
    traccar.data["positions"][0]["latitude"] = 91                          # una invalida
    traccar.data["positions"].append(copy.deepcopy(traccar.data["positions"][1]))   # un duplicado
    res = correr(stg_con, dwh_con, "full", odoo, traccar)
    pos = res["calidad"]["posicion"]
    assert pos == {"entrada": 5, "duplicados": 1, "validos": 3, "rechazados": 1, "transformados": 3, "cargados": 3}
    for entidad, fila in res["calidad"].items():          # cuadra en todas las entidades
        assert fila["entrada"] == fila["duplicados"] + fila["validos"] + fila["rechazados"], entidad
        assert fila["transformados"] <= fila["validos"], entidad
    guardado = q1(dwh_con, "select calidad->'posicion'->>'rechazados' from etl_ejecucion")
    assert guardado == "1"
    vista = qall(dwh_con, "select entidad, entrada, validos, rechazados, transformados, cargados "
                          "from v_bi_etl_calidad where entidad = 'posicion'")
    assert vista == [("posicion", 5, 3, 1, 3, 3)]
