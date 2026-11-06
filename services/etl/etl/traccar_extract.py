"""Extraccion desde Traccar (HTTP Basic). Solo backend; credenciales por entorno."""
import requests


class TraccarSource:
    def __init__(self, url, user, password, timeout=30):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.auth = (user, password)
        self.s.headers["Accept"] = "application/json"
        self.timeout = timeout

    def _get(self, path, **params):
        r = self.s.get(self.url + path, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def fetch(self, desde, hasta):
        """{'devices','positions','trips','stops','last_positions'} para la ventana [desde, hasta] (UTC)."""
        devices = self._get("/api/devices")
        out = {"devices": devices, "positions": [], "trips": [], "stops": [], "last_positions": []}
        for d in devices:
            q = {"deviceId": d["id"], "from": self._iso(desde), "to": self._iso(hasta)}
            out["positions"] += self._get("/api/reports/route", **q)
            out["trips"] += self._get("/api/reports/trips", **q)
            out["stops"] += self._get("/api/reports/stops", **q)
        out["last_positions"] = self._get("/api/positions")
        return out
