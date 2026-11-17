"""Escenarios de funcionamiento completo: varias corridas a lo largo de una jornada, con fuentes que solo muestran
lo ocurrido hasta el reloj de cada corrida (como las reales), comparadas con una corrida completa unica.

Propiedad central: una secuencia de corridas incrementales deja el DWH igual que una sola corrida completa hecha al
final. Si no, el incremental pierde o duplica datos."""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FixtureOdoo, FixtureTraccar, TZ, _admin_dsn, Dbs, correr, q1, qall
from etl import simulate, staging
from etl.transform import normalize as n

UTC = timezone.utc


def ts(h, m, dia=5):
    return datetime(2026, 11, dia, h, m, tzinfo=UTC)


# ---------------------------------------------------------------- fuentes con reloj
class OdooConReloj(FixtureOdoo):
    """Solo existen los registros escritos hasta `reloj` (write_date <= reloj)."""
    reloj = None

    def fetch(self, model, since=None):
        filas = super().fetch(model, since)
        if filas is None or self.reloj is None:
            return filas
        return [r for r in filas if n.parse_ts(r["write_date"]) <= self.reloj]


class TraccarConReloj(FixtureTraccar):
    """Como Traccar: lo posterior a `hasta` no existe todavia y un viaje en marcha sale cortado en `hasta`."""

    def fetch(self, desde, hasta, desde_viajes=None):
        d = super().fetch(desde, hasta, desde_viajes)
        for clave in ("trips", "stops"):
            vivos = []
            for t in d[clave]:
                fin = n.parse_ts(t.get("endTime"))
                if fin is not None and fin > hasta:
                    t = dict(t, endTime=hasta.isoformat())
                vivos.append(t)
            d[clave] = vivos
        return d


def jornada():
    """Dia de operacion mas completo que los fixtures base: el vehiculo 10 hace un segundo viaje (15:05-15:20) que
    empieza mientras el 11 sigue en marcha (15:00-15:30), y llegan posiciones durante toda la tarde."""
    odoo, traccar = OdooConReloj(), TraccarConReloj()
    traccar.data["trips"].append({"deviceId": 10, "startTime": "2026-11-05T15:05:00.000+00:00",
                                  "endTime": "2026-11-05T15:20:00.000+00:00", "distance": 1500.0,
                                  "averageSpeed": 8.0, "maxSpeed": 15.0, "startLat": -1.2230, "startLon": -78.6330,
                                  "endLat": -1.2417, "endLon": -78.6197})
    traccar.data["stops"].append({"deviceId": 10, "startTime": "2026-11-05T15:10:00.000+00:00",
                                  "endTime": "2026-11-05T15:12:00.000+00:00"})
    for i, (h, m) in enumerate(((15, 8), (15, 15), (15, 20))):
        traccar.data["positions"].append({"id": 1100 + i, "deviceId": 10,
                                          "fixTime": ts(h, m).isoformat(), "latitude": -1.2300 + i * 0.003,
                                          "longitude": -78.6300 + i * 0.003, "speed": 8.0})
    traccar.data["positions"].append({"id": 1200, "deviceId": 11, "fixTime": ts(15, 25).isoformat(),
                                      "latitude": -1.2700, "longitude": -78.6290, "speed": 7.0})
    return odoo, traccar


# ---------------------------------------------------------------- foto del DWH (independiente de las claves sk)
def foto(stg_con, dwh_con):
    """Contenido de negocio del DWH con las claves sustitutas traducidas a claves de origen."""
    return {
        "recorridos": qall(dwh_con, """
            select r.fuente_id, r.procedencia, v.placa, c.nombre, zo.codigo, zd.codigo, r.inicio_utc, r.fin_utc,
                   r.distancia_km, r.duracion_min, r.num_paradas, r.velocidad_media_kmh, r.velocidad_max_kmh,
                   r.ruta_id_odoo, r.lat_origen, r.lon_origen, r.lat_destino, r.lon_destino, r.tiempo_inicio_sk
            from fact_recorridos r join dim_vehiculo v on v.sk=r.vehiculo_sk
            left join dim_conductor c on c.sk=r.conductor_sk
            left join dim_zona zo on zo.sk=r.zona_origen_sk left join dim_zona zd on zd.sk=r.zona_destino_sk
            order by 1, 2"""),
        "posiciones": qall(dwh_con, """
            select g.fuente_id, v.placa, g.gps_time_utc, g.latitud, g.longitud, g.velocidad_kmh, g.tiempo_sk
            from fact_posicion_gps g join dim_vehiculo v on v.sk=g.vehiculo_sk order by 1"""),
        "rutas": qall(dwh_con, """
            select r.ruta_id_odoo, r.codigo, v.placa, c.nombre, r.estado, r.inicio_utc, r.fin_utc, r.km_planificado,
                   r.km_real, r.min_real, r.posiciones_gps, r.paradas_total, r.paradas_entregadas,
                   r.paradas_fallidas, r.paradas_pendientes
            from fact_rutas r left join dim_vehiculo v on v.sk=r.vehiculo_sk
            left join dim_conductor c on c.sk=r.conductor_sk order by 1"""),
        "paradas": qall(dwh_con, """
            select parada_id_odoo, ruta_id_odoo, entrega_id_odoo, orden, estado, llegada_utc, cierre_utc,
                   min_en_parada, motivo from fact_paradas order by 1"""),
        "entregas": qall(dwh_con, """
            select e.entrega_id_odoo, e.resultado, e.motivo, e.planificado_utc, e.completado_utc, e.a_tiempo,
                   e.intentos, r.fuente_id
            from fact_entregas e left join fact_recorridos r on r.sk=e.recorrido_sk order by 1"""),
        "ventas": qall(dwh_con, "select linea_id_odoo, pedido_ref, cantidad, subtotal from fact_ventas order by 1"),
        "ml_viajes": qall(dwh_con, """
            select vehiculo_codigo, fecha_hora, hora_local, zona_origen, zona_destino, ruta_id_odoo,
                   entregas_vinculadas from v_ml_viajes order by 1, 2"""),
        "rechazos_abiertos": qall(stg_con, "select entidad, fuente_id, motivo from rechazados "
                                           "where resuelto_utc is null order by 1, 2, 3"),
    }


@pytest.fixture
def otras_bases():
    """Un segundo par de bases desechables, para la corrida de referencia."""
    d = Dbs(_admin_dsn())
    d.bootstrap()
    stg_c, dwh_c = d.connect(d.stg_db), d.connect(d.dwh_db)
    try:
        yield stg_c, dwh_c
    finally:
        stg_c.close()
        dwh_c.close()
        d.cleanup()


RELOJES = [ts(13, 0), ts(13, 20), ts(13, 45), ts(14, 15), ts(15, 10), ts(15, 33), ts(16, 0), ts(17, 0)]


def test_jornada_de_incrementales_equivale_a_una_completa(stg_con, dwh_con, otras_bases):
    odoo, traccar = jornada()
    for i, reloj in enumerate(RELOJES):
        odoo.reloj = reloj
        correr(stg_con, dwh_con, "full" if i == 0 else "incremental", odoo, traccar, now=reloj)
    final = foto(stg_con, dwh_con)

    stg2, dwh2 = otras_bases
    odoo2, traccar2 = jornada()
    odoo2.reloj = RELOJES[-1]
    correr(stg2, dwh2, "full", odoo2, traccar2, now=RELOJES[-1])
    referencia = foto(stg2, dwh2)

    for clave in referencia:
        assert final[clave] == referencia[clave], clave
    # y la jornada quedo completa: 3 viajes enteros (ninguno cortado), el del 11 con sus 30 minutos
    assert [(r[0], r[6], r[7]) for r in final["recorridos"]] == [
        ("trip:10:2026-11-05T13:30:00+00:00", ts(13, 30), ts(14, 0)),
        ("trip:10:2026-11-05T15:05:00+00:00", ts(15, 5), ts(15, 20)),
        ("trip:11:2026-11-05T15:00:00+00:00", ts(15, 0), ts(15, 30))]
    assert len(final["posiciones"]) == 8


def test_jornada_registra_cada_corrida_sin_errores(stg_con, dwh_con):
    odoo, traccar = jornada()
    for i, reloj in enumerate(RELOJES):
        odoo.reloj = reloj
        correr(stg_con, dwh_con, "full" if i == 0 else "incremental", odoo, traccar, now=reloj)
    assert qall(stg_con, "select estado, count(*) from lote group by 1") == [("ok", len(RELOJES))]
    assert q1(dwh_con, "select count(*) from etl_ejecucion where estado='ok'") == len(RELOJES)
    # las marcas de agua nunca retroceden y terminan en lo ultimo visto
    assert q1(stg_con, "select valor_utc from watermark where fuente='traccar:recorridos'") == ts(15, 30)
    assert q1(stg_con, "select valor_utc from watermark where fuente='traccar:posiciones'") == ts(15, 25)


def test_repetir_corridas_no_cambia_nada(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    base = foto(stg_con, dwh_con)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    correr(stg_con, dwh_con, "incremental", odoo, traccar)
    assert foto(stg_con, dwh_con) == base


def test_fuentes_caidas_no_alteran_el_dwh(stg_con, dwh_con, odoo, traccar):
    """Con Odoo y Traccar caidos el ETL trabaja con lo que ya hay en staging: no borra ni cambia nada (ni la ruta
    ni el conductor de los recorridos, ni los vinculos)."""
    correr(stg_con, dwh_con, "full", odoo, traccar)
    base = foto(stg_con, dwh_con)
    correr(stg_con, dwh_con, "incremental", None, traccar)
    assert foto(stg_con, dwh_con) == base
    correr(stg_con, dwh_con, "incremental", odoo, None)
    assert foto(stg_con, dwh_con) == base
    correr(stg_con, dwh_con, "full", None, None)
    assert foto(stg_con, dwh_con) == base


def test_dos_entregas_en_la_misma_parada_comparten_el_viaje_de_llegada(stg_con, dwh_con, odoo, traccar):
    """Dos clientes en el mismo edificio: el viaje termina al llegar (13:35) y las dos entregas cierran en la
    parada (13:40 y 13:44). Las dos se vinculan al mismo viaje de llegada."""
    traccar.data["trips"][0].update(endTime="2026-11-05T13:35:00.000+00:00")
    ent = copy.deepcopy(odoo.data["logistica.entrega"][0])
    ent.update(id=4, name="ENT/0004", write_date="2026-11-05 13:45:00")
    odoo.data["logistica.entrega"].append(ent)
    par = copy.deepcopy(odoo.data["logistica.ruta.parada"][0])
    par.update(id=4, sequence=2, entrega_id=[4, "ENT/0004"], completed_at="2026-11-05 13:44:00",
               write_date="2026-11-05 13:45:00")
    odoo.data["logistica.ruta.parada"].append(par)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    vinculos = dict(qall(dwh_con, "select entrega_id_odoo, recorrido_sk from fact_entregas"))
    assert vinculos[1] is not None and vinculos[1] == vinculos[4]
    assert q1(dwh_con, "select entregas_vinculadas from v_ml_viajes where recorrido_sk=%s", vinculos[1]) == 2


def test_viaje_entre_dos_rutas_toma_la_de_mayor_solape(stg_con, dwh_con, odoo, traccar):
    """El viaje 13:30-14:00 del vehiculo 1 pasa casi entero en la RUTA/0001 (cerrada a las 13:55: 25 min de
    solape) y apenas en la RUTA/0003 (desde 13:56: 4 min). Gana la de mayor solape aunque sea la mas antigua."""
    odoo.data["logistica.ruta"][0].update(finished_at="2026-11-05 13:55:00", state="cerrada")
    ruta = copy.deepcopy(odoo.data["logistica.ruta"][0])
    ruta.update(id=3, name="RUTA/0003", state="en_recorrido", started_at="2026-11-05 13:56:00", finished_at=False,
                driver_id=[101, "Luis"], write_date="2026-11-05 13:56:00")
    odoo.data["logistica.ruta"].append(ruta)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert qall(dwh_con, "select r.ruta_id_odoo, c.nombre from fact_recorridos r "
                         "join dim_conductor c on c.sk=r.conductor_sk where r.fuente_id like 'trip:10:%'") == [
        (1, "Carlos")]


def test_ruta_cancelada_sin_inicio_no_reclama_viajes(stg_con, dwh_con, odoo, traccar):
    odoo.data["logistica.ruta"][0].update(state="cancelada", started_at=False)
    correr(stg_con, dwh_con, "full", odoo, traccar)
    assert q1(dwh_con, "select ruta_id_odoo from fact_recorridos where fuente_id like 'trip:10:%'") is None


def test_contrato_c3_y_hora_local_son_coherentes(stg_con, dwh_con, odoo, traccar):
    """El ML calcula la hora local desde fecha_hora (UTC) restando 5 h. Debe dar la misma hora que hora_local de
    v_ml_viajes, para datos REAL y SIMULADO."""
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _ = staging.new_lote(scur, "simulate")
        simulate.generar(dcur, lote, dias=4, seed=5, now=ts(12, 0, dia=6), tz=TZ)
    stg_con.commit()
    dwh_con.commit()
    correr(stg_con, dwh_con, "full", odoo, traccar)
    filas = qall(dwh_con, "select fecha_hora, hora_local, dia_semana_local from v_ml_viajes")
    assert len(filas) > 10
    for fecha_hora, hora_local, dia_local in filas:
        local = n.parse_ts(fecha_hora) - timedelta(hours=5)
        assert (local.hour, local.isoweekday()) == (hora_local, dia_local), fecha_hora
    c3 = q1(dwh_con, "select count(*) from v_viajes_entrenamiento")
    assert c3 == q1(dwh_con, "select count(*) from v_ml_viajes where zona_origen is not null "
                             "and zona_destino is not null")


def test_simulado_respeta_la_jornada_local_con_cambio_de_hora(stg_con, dwh_con):
    """Con una zona horaria con horario de verano (Madrid cambia el 25-10-2026) la jornada sigue siendo
    07:00-21:00 local a ambos lados del cambio, y la carga es idempotente."""
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _ = staging.new_lote(scur, "simulate")
        primero = simulate.generar(dcur, lote, dias=20, seed=9, now=ts(12, 0, dia=6), tz="Europe/Madrid")
        segundo = simulate.generar(dcur, lote, dias=20, seed=9, now=ts(12, 0, dia=6), tz="Europe/Madrid")
    stg_con.commit()
    dwh_con.commit()
    assert primero > 0 and segundo == 0
    horas = qall(dwh_con, """select (r.inicio_utc at time zone 'Europe/Madrid')::date < date '2026-10-25',
                                    min(extract(hour from r.inicio_utc at time zone 'Europe/Madrid')),
                                    max(extract(hour from r.inicio_utc at time zone 'Europe/Madrid'))
                             from fact_recorridos r group by 1 order by 1""")
    assert len(horas) == 2
    for _antes, minima, maxima in horas:
        assert 7 <= minima and maxima < 21


def test_simulado_sustituye_el_formato_anterior_sin_tocar_lo_real(stg_con, dwh_con, odoo, traccar):
    correr(stg_con, dwh_con, "full", odoo, traccar)
    with dwh_con.cursor() as cur:       # una fila con el formato de la version anterior (sin 'Z')
        cur.execute("""insert into fact_recorridos (vehiculo_sk, inicio_utc, fin_utc, fuente_id, procedencia)
                       select sk, now(), now(), 'sim:SIM-001:20261101T0700', 'SIMULADO'
                       from dim_vehiculo where procedencia='REAL' limit 1""")
    dwh_con.commit()
    with stg_con.cursor() as scur, dwh_con.cursor() as dcur:
        lote, _ = staging.new_lote(scur, "simulate")
        simulate.generar(dcur, lote, dias=2, seed=1, now=ts(12, 0, dia=6), tz=TZ)
    stg_con.commit()
    dwh_con.commit()
    assert q1(dwh_con, "select count(*) from fact_recorridos where fuente_id='sim:SIM-001:20261101T0700'") == 0
    assert q1(dwh_con, "select count(*) from fact_recorridos where procedencia='REAL'") == 2
    assert q1(dwh_con, "select count(*) from fact_entregas where recorrido_sk is not null") == 1
