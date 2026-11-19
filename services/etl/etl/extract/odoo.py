"""Extraccion desde Odoo por XML-RPC (search_read paginado, filtro por write_date, reintentos)."""
import time
import xmlrpc.client

# modelo -> campos deseados, dominio base y campos que el dominio exige (si faltan, el modelo se omite).
# Solo se piden los campos que el DWH usa: nada de correos, telefonos ni direcciones (spec 12).
# `inactivos`: incluye registros archivados (un vehiculo o producto archivado sigue apareciendo en el historico).
MODELS = {
    "logistica.zona": dict(fields=["id", "code", "name", "latitude", "longitude", "active", "write_date"],
                           inactivos=True),
    "res.partner": dict(fields=["id", "name", "city", "is_driver", "write_date"],
                        domain=["|", ("is_driver", "=", True), ("sale_order_ids", "!=", False)],
                        need=["is_driver", "sale_order_ids"], inactivos=True),
    "traccar.device": dict(fields=["id", "name", "unique_id", "traccar_id", "write_date"]),
    "fleet.vehicle": dict(fields=["id", "license_plate", "name", "model_id", "driver_id", "traccar_device_id",
                                  "logistica_capacidad", "write_date"], inactivos=True),
    "product.product": dict(fields=["id", "display_name", "default_code", "categ_id", "lst_price", "write_date"],
                            inactivos=True),
    "sale.order": dict(fields=["id", "name", "client_order_ref", "partner_id", "date_order", "state", "amount_total",
                               "delivery_latitude", "delivery_longitude", "write_date"]),
    "sale.order.line": dict(fields=["id", "order_id", "product_id", "product_uom_qty", "price_unit",
                                    "price_subtotal", "price_total", "display_type", "write_date"]),
    "logistica.ruta": dict(fields=["id", "name", "date", "vehicle_id", "driver_id", "state", "confirmed_load_at",
                                   "started_at", "finished_at", "planned_distance_km", "planned_duration_min",
                                   "distance_source", "optimization_version", "write_date"]),
    "logistica.ruta.parada": dict(fields=["id", "route_id", "sequence", "entrega_id", "state",
                                          "arrival_candidate_at", "actual_arrival_at", "completed_at",
                                          "failed_reason", "write_date"]),
    "logistica.entrega": dict(fields=["id", "name", "sale_order_id", "partner_id", "latitude", "longitude", "state",
                                      "route_id", "create_date", "write_date"]),
    "logistica.entrega.evento": dict(fields=["id", "entrega_id", "event_type", "event_time", "route_id",
                                             "failure_reason", "write_date"]),
}
PAGINA = 500
REINTENTOS = 3
ESPERA_S = 2.0
# Errores transitorios de red o del servidor: se reintenta. Un Fault (error de Odoo) no se reintenta.
TRANSITORIOS = (OSError, xmlrpc.client.ProtocolError)


def con_reintentos(fn, intentos=REINTENTOS, espera=ESPERA_S, dormir=time.sleep):
    """Ejecuta fn(); ante un error transitorio espera (1x, 2x, ...) y reintenta hasta `intentos` veces."""
    for n in range(1, intentos + 1):
        try:
            return fn()
        except TRANSITORIOS:
            if n == intentos:
                raise
            dormir(espera * n)


class OdooSource:
    def __init__(self, url, db, user, password, common=None, models=None, dormir=time.sleep):
        """`common` y `models` permiten inyectar los proxys (pruebas); por defecto son los de XML-RPC."""
        self.db, self.password, self.dormir = db, password, dormir
        base = url.rstrip("/")
        self.common = common or xmlrpc.client.ServerProxy(base + "/xmlrpc/2/common")
        self.models = models or xmlrpc.client.ServerProxy(base + "/xmlrpc/2/object", allow_none=True)
        self.uid = con_reintentos(lambda: self.common.authenticate(db, user, password, {}), dormir=dormir)
        if not self.uid:
            raise RuntimeError("Autenticacion Odoo fallida para el usuario %s" % user)

    def _call(self, model, method, *args, **kw):
        return con_reintentos(
            lambda: self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kw),
            dormir=self.dormir)

    def model_exists(self, model):
        return bool(self._call("ir.model", "search", [("model", "=", model)], limit=1))

    def contar(self, model, domain):
        """search_count (incluye archivados no: cuenta lo activo, como lo ve el usuario)."""
        return self._call(model, "search_count", list(domain))

    def parametro(self, clave):
        """Valor de un ir.config_parameter, o None si no existe o el usuario no puede leerlo."""
        try:
            filas = self._call("ir.config_parameter", "search_read", [("key", "=", clave)], fields=["value"], limit=1)
        except xmlrpc.client.Fault:
            return None
        return filas[0]["value"] if filas else None

    def fetch(self, model, since=None):
        """Filas del modelo (todas las paginas); None si el modelo o un campo que su dominio exige no existe.
        since: solo registros con write_date >= since (inclusivo: repetir un registro es inocuo, saltarlo no)."""
        spec = MODELS[model]
        if not self.model_exists(model):
            return None
        avail = self._call(model, "fields_get", attributes=["type"])
        if any(f not in avail for f in spec.get("need", [])):
            return None
        domain = list(spec.get("domain", []))
        if since is not None:
            domain.append(("write_date", ">=", since.strftime("%Y-%m-%d %H:%M:%S")))
        kw = dict(fields=[f for f in spec["fields"] if f in avail], order="id", limit=PAGINA)
        if spec.get("inactivos") and "active" in avail:
            kw["context"] = {"active_test": False}
        filas, offset = [], 0
        while True:
            pagina = self._call(model, "search_read", domain, offset=offset, **kw)
            filas += pagina
            if len(pagina) < PAGINA:
                return filas
            offset += PAGINA
