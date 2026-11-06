"""Extraccion desde Odoo por XML-RPC (search_read con filtro write_date)."""
import xmlrpc.client

# modelo -> (campos deseados, dominio base, campos que el dominio exige, incremental?)
# Las dimensiones y rutas se leen completas en cada corrida (son pequenas y las entregas las necesitan);
# entregas y eventos son incrementales por write_date.
MODELS = {
    "res.partner": (["id", "name", "write_date", "is_driver"], [("is_driver", "=", True)], ["is_driver"], False),
    "fleet.vehicle": (["id", "license_plate", "name", "traccar_device_id", "driver_id", "write_date"], [], [], False),
    "logistica.ruta": (["id", "name", "date", "vehicle_id", "driver_id", "state", "started_at", "finished_at",
                        "confirmed_load_at", "write_date"], [], [], False),
    "logistica.ruta.parada": (["id", "route_id", "sequence", "entrega_id", "state", "completed_at",
                               "actual_arrival_at", "failed_reason", "write_date"], [], [], False),
    "logistica.entrega": (["id", "name", "sale_order_id", "partner_id", "latitude", "longitude", "state",
                           "route_id", "create_date", "write_date"], [], [], True),
    "logistica.entrega.evento": (["id", "entrega_id", "event_type", "event_time", "route_id", "failure_reason",
                                  "write_date"], [], [], True),
}
INCREMENTAL = {m for m, spec in MODELS.items() if spec[3]}


class OdooSource:
    def __init__(self, url, db, user, password):
        self.db, self.password = db, password
        self.common = xmlrpc.client.ServerProxy(url.rstrip("/") + "/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(url.rstrip("/") + "/xmlrpc/2/object", allow_none=True)
        self.uid = self.common.authenticate(db, user, password, {})
        if not self.uid:
            raise RuntimeError("Autenticacion Odoo fallida para el usuario %s" % user)

    def _call(self, model, method, *args, **kw):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kw)

    def model_exists(self, model):
        return bool(self._call("ir.model", "search", [("model", "=", model)], limit=1))

    def fetch(self, model, since=None):
        """Filas del modelo; None si el modelo (o un campo necesario) aun no existe en Odoo."""
        fields, domain, need, _ = MODELS[model]
        if not self.model_exists(model):
            return None
        avail = self._call(model, "fields_get", attributes=["type"])
        if any(f not in avail for f in need):
            return None
        domain = list(domain)
        if since is not None:
            domain.append(("write_date", ">", since.strftime("%Y-%m-%d %H:%M:%S")))
        return self._call(model, "search_read", domain, fields=[f for f in fields if f in avail], order="id")
