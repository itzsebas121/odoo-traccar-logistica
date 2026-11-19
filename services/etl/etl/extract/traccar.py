"""Extraccion desde Traccar (API REST, HTTP Basic). Solo backend; credenciales por entorno.

Los informes se piden por dispositivo. Las posiciones (voluminosas) van en tramos de pocos dias, para que una ventana
larga no agote el tiempo de espera del servidor. Los viajes y las paradas van en una sola peticion por dispositivo:
Traccar los calcula con las posiciones de la ventana pedida, asi que un borde de tramo partiria en dos cada viaje que
lo cruza (un primer trozo acortado y un segundo que pareceria otro viaje)."""
import time
from datetime import timedelta

import requests

TRAMO_DIAS = 7
REINTENTOS = 3
ESPERA_S = 2.0
INFORMES = {"positions": "/api/reports/route", "trips": "/api/reports/trips", "stops": "/api/reports/stops"}


def tramos(desde, hasta, dias=TRAMO_DIAS):
    """Parte [desde, hasta] en tramos consecutivos de `dias` dias como maximo."""
    out, ini = [], desde
    while ini < hasta:
        fin = min(ini + timedelta(days=dias), hasta)
        out.append((ini, fin))
        ini = fin
    return out


class TraccarSource:
    def __init__(self, url, user, password, timeout=30, session=None, dormir=time.sleep):
        self.url = url.rstrip("/")
        self.s = session or requests.Session()
        self.s.auth = (user, password)
        self.s.headers["Accept"] = "application/json"
        self.timeout, self.dormir = timeout, dormir

    def _get(self, path, **params):
        """GET con reintentos ante fallos de red y respuestas 5xx. Un 4xx (credenciales, permisos) falla de inmediato."""
        for n in range(1, REINTENTOS + 1):
            try:
                r = self.s.get(self.url + path, params=params, timeout=self.timeout)
                if r.status_code < 500:
                    r.raise_for_status()
                    return r.json()
                error = requests.HTTPError("Traccar respondio %s en %s" % (r.status_code, path))
            except (requests.ConnectionError, requests.Timeout) as exc:
                error = exc
            if n == REINTENTOS:
                raise error
            self.dormir(ESPERA_S * n)

    def comprobar(self):
        """Falla pronto si Traccar no responde o rechaza las credenciales."""
        self._get("/api/devices")

    @staticmethod
    def _iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def fetch(self, desde, hasta, desde_viajes=None):
        """{'devices','positions','trips','stops'} (UTC). Posiciones de [desde, hasta]; viajes y paradas de
        [desde_viajes, hasta] (por defecto la misma ventana). Las ventanas son distintas porque Traccar calcula
        los viajes con las posiciones de la ventana: si empieza a mitad de un viaje, lo devuelve cortado."""
        desde_viajes = desde_viajes or desde
        devices = self._get("/api/devices")
        out = {"devices": devices, "positions": [], "trips": [], "stops": []}
        for d in devices:
            for clave, ruta in INFORMES.items():
                inicio = desde if clave == "positions" else desde_viajes
                partes = tramos(inicio, hasta) if clave == "positions" else ([(inicio, hasta)] if inicio < hasta else [])
                for ini, fin in partes:
                    out[clave] += self._get(ruta, deviceId=d["id"], **{"from": self._iso(ini), "to": self._iso(fin)})
        return out
