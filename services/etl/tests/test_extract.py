"""Extractores: paginacion, filtro incremental, reintentos. Sin red: los transportes son falsos."""
import xmlrpc.client
from datetime import datetime, timedelta, timezone

import pytest
import requests

from etl.extract import odoo as eo
from etl.extract import traccar as et

UTC = timezone.utc


# ---------------------------------------------------------------- Odoo
class Comun:
    def authenticate(self, db, user, password, ctx):
        return 7


class Modelos:
    """Imita /xmlrpc/2/object con un solo modelo de datos."""

    def __init__(self, filas, campos, fallos=0, existe=True):
        self.filas, self.campos, self.fallos, self.existe = filas, campos, fallos, existe
        self.llamadas = []

    def execute_kw(self, db, uid, password, model, method, args, kw):
        self.llamadas.append((model, method, args, kw))
        if self.fallos:
            self.fallos -= 1
            raise OSError("conexion reiniciada")
        if model == "ir.model":
            return [1] if self.existe else []
        if method == "fields_get":
            return {c: {"type": "char"} for c in self.campos}
        offset, limit = kw.get("offset", 0), kw["limit"]
        return self.filas[offset:offset + limit]

    def lecturas(self):
        return [c for c in self.llamadas if c[1] == "search_read"]


def fuente(modelos):
    return eo.OdooSource("http://x", "db", "admin", "clave", common=Comun(), models=modelos, dormir=lambda s: None)


CAMPOS_ZONA = ["id", "code", "name", "latitude", "longitude", "active", "write_date"]


def test_odoo_pagina_hasta_el_final(monkeypatch):
    monkeypatch.setattr(eo, "PAGINA", 2)
    m = Modelos([{"id": i} for i in range(1, 6)], CAMPOS_ZONA)
    assert [r["id"] for r in fuente(m).fetch("logistica.zona")] == [1, 2, 3, 4, 5]
    assert [c[3]["offset"] for c in m.lecturas()] == [0, 2, 4]
    assert all(c[3]["order"] == "id" for c in m.lecturas())


def test_odoo_filtro_incremental_y_archivados():
    m = Modelos([], CAMPOS_ZONA)
    fuente(m).fetch("logistica.zona", since=datetime(2026, 11, 5, 13, 0, tzinfo=UTC))
    _modelo, _metodo, args, kw = m.lecturas()[0]
    assert args[0] == [("write_date", ">=", "2026-11-05 13:00:00")]
    assert kw["context"] == {"active_test": False}        # una zona archivada sigue en el historico


def test_odoo_solo_pide_campos_que_existen():
    m = Modelos([], ["id", "name", "write_date"])
    fuente(m).fetch("logistica.ruta")
    assert m.lecturas()[0][3]["fields"] == ["id", "name", "write_date"]


def test_odoo_modelo_o_campo_del_dominio_ausente():
    assert fuente(Modelos([], CAMPOS_ZONA, existe=False)).fetch("logistica.zona") is None
    assert fuente(Modelos([], ["id", "name"])).fetch("res.partner") is None     # falta is_driver


def test_odoo_reintenta_errores_de_red():
    m = Modelos([{"id": 1}], CAMPOS_ZONA, fallos=2)
    assert fuente(m).fetch("logistica.zona") == [{"id": 1}]


def test_odoo_se_rinde_tras_tres_intentos():
    with pytest.raises(OSError):
        fuente(Modelos([], CAMPOS_ZONA, fallos=3)).fetch("logistica.zona")


def test_odoo_no_reintenta_un_error_de_odoo():
    intentos = []

    def falla():
        intentos.append(1)
        raise xmlrpc.client.Fault(1, "Access Denied")

    with pytest.raises(xmlrpc.client.Fault):
        eo.con_reintentos(falla, dormir=lambda s: None)
    assert len(intentos) == 1


def test_odoo_autenticacion_fallida():
    class Rechaza:
        def authenticate(self, *a):
            return False

    with pytest.raises(RuntimeError, match="Autenticacion Odoo fallida"):
        eo.OdooSource("http://x", "db", "admin", "mala", common=Rechaza(), models=Modelos([], []))


def test_odoo_no_extrae_datos_de_contacto():
    """Spec 12: el DWH no necesita correos, telefonos ni direcciones."""
    prohibidos = {"email", "phone", "mobile", "street", "vat", "recipient_name", "destination_address",
                  "tracking_token", "password"}
    for modelo, spec in eo.MODELS.items():
        assert not prohibidos & set(spec["fields"]), modelo


# ---------------------------------------------------------------- Traccar
class Respuesta:
    def __init__(self, status, datos=None):
        self.status_code, self.datos = status, datos

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code)

    def json(self):
        return self.datos


class Sesion:
    def __init__(self, respuestas=None):
        self.headers, self.auth, self.pedidos, self.respuestas = {}, None, [], list(respuestas or [])

    def get(self, url, params=None, timeout=None):
        self.pedidos.append((url, params or {}))
        if self.respuestas:
            r = self.respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        if url.endswith("/api/devices"):
            return Respuesta(200, [{"id": 10}, {"id": 11}])
        return Respuesta(200, [{"deviceId": params["deviceId"], "desde": params["from"]}])


def traccar(sesion):
    return et.TraccarSource("http://t/", "u", "p", session=sesion, dormir=lambda s: None)


def test_tramos_cubren_la_ventana_sin_huecos():
    ini = datetime(2026, 11, 1, tzinfo=UTC)
    partes = et.tramos(ini, ini + timedelta(days=16))
    assert [(b - a).days for a, b in partes] == [7, 7, 2]
    assert partes[0][0] == ini and partes[-1][1] == ini + timedelta(days=16)
    assert all(partes[i][1] == partes[i + 1][0] for i in range(len(partes) - 1))
    assert et.tramos(ini, ini) == []


def test_traccar_pide_posiciones_por_tramo_y_viajes_de_una_vez():
    """Las posiciones (voluminosas) se piden en tramos de 7 dias. Los viajes y las paradas, en una sola peticion por
    dispositivo: Traccar los calcula dentro de la ventana pedida, y un borde de tramo partiria en dos cada viaje
    que lo cruza (con el primer trozo acortado y el segundo cargado como un viaje distinto)."""
    s = Sesion()
    ini = datetime(2026, 11, 1, tzinfo=UTC)
    datos = traccar(s).fetch(ini, ini + timedelta(days=10))
    assert [d["id"] for d in datos["devices"]] == [10, 11]
    assert len(datos["positions"]) == 4                     # 2 dispositivos x 2 tramos
    assert len(datos["trips"]) == len(datos["stops"]) == 2  # 2 dispositivos x 1 ventana
    assert len(s.pedidos) == 1 + 2 * 2 + 2 * 2
    posiciones = [p for u, p in s.pedidos if u.endswith("/reports/route")]
    assert posiciones[0] == {"deviceId": 10, "from": "2026-11-01T00:00:00.000Z", "to": "2026-11-08T00:00:00.000Z"}
    viajes = [p for u, p in s.pedidos if u.endswith("/reports/trips")]
    assert viajes[0] == {"deviceId": 10, "from": "2026-11-01T00:00:00.000Z", "to": "2026-11-11T00:00:00.000Z"}
    assert s.auth == ("u", "p")


def test_traccar_reintenta_5xx_y_cortes():
    s = Sesion([Respuesta(503), requests.ConnectionError("corte"), Respuesta(200, [{"id": 1}])])
    assert traccar(s)._get("/api/devices") == [{"id": 1}]
    assert len(s.pedidos) == 3


def test_traccar_se_rinde_tras_tres_5xx():
    s = Sesion([Respuesta(500), Respuesta(500), Respuesta(500)])
    with pytest.raises(requests.HTTPError):
        traccar(s)._get("/api/devices")


def test_traccar_no_reintenta_credenciales_rechazadas():
    s = Sesion([Respuesta(401)])
    with pytest.raises(requests.HTTPError):
        traccar(s).comprobar()
    assert len(s.pedidos) == 1
