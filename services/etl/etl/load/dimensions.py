"""Carga de dimensiones en el DWH (tipo 1: el valor nuevo sobrescribe al anterior)."""
from ..transform import normalize as n
from ..transform import zonas as z


class Contexto:
    """Estado de una corrida: lote, reloj, zona horaria, conteos y los mapas id de origen -> clave del DWH."""

    def __init__(self, lote_id, now, tz):
        self.lote_id, self.now, self.tz = lote_id, now, tz
        self.cargados = {}
        self.rechazados = {}
        self.omitidos = []
        self.zonas = []
        self.vehiculo = {}             # vehiculo_id_odoo -> sk
        self.conductor = {}            # conductor_id_odoo -> sk
        self.cliente = {}              # cliente_id_odoo -> sk
        self.producto = {}             # producto_id_odoo -> sk
        self.dispositivo = {}          # id del dispositivo en Traccar -> (vehiculo_sk, vehiculo_id_odoo)
        self.conductor_de_vehiculo = {}
        self._tiempos = set()

    def contar(self, tabla, cantidad=1):
        self.cargados[tabla] = self.cargados.get(tabla, 0) + cantidad

    def zona(self, lat, lon):
        return z.zona_mas_cercana(self.zonas, lat, lon)


def ensure_tiempo(cur, ctx, dt):
    """Clave de dim_tiempo para el instante `dt` (crea la fila si falta). None si no hay fecha."""
    if dt is None:
        return None
    f = n.fila_tiempo(dt, ctx.tz)
    if f["sk"] not in ctx._tiempos:
        cur.execute(
            """INSERT INTO dim_tiempo (sk, fecha, anio, mes, dia, dia_semana, hora, fecha_local, hora_local,
                                       dia_semana_local, franja, fin_de_semana)
               VALUES (%(sk)s,%(fecha)s,%(anio)s,%(mes)s,%(dia)s,%(dia_semana)s,%(hora)s,%(fecha_local)s,
                       %(hora_local)s,%(dia_semana_local)s,%(franja)s,%(fin_de_semana)s)
               ON CONFLICT (sk) DO NOTHING""", f)
        ctx._tiempos.add(f["sk"])
    return f["sk"]


def leer_zonas(cur):
    cur.execute("SELECT sk, codigo, latitud, longitud, activa FROM dim_zona")
    return [dict(sk=r[0], codigo=r[1], lat=r[2], lon=r[3], activa=r[4]) for r in cur.fetchall()]


def asegurar_zonas_contrato(cur):
    """Crea (sin coordenadas) los codigos de zona del contrato que falten. Lo usa `simulate` cuando todavia no
    se han cargado las zonas de Odoo; la carga real las completa despues por codigo."""
    for codigo in z.CODIGOS_CONTRATO:
        cur.execute("INSERT INTO dim_zona (codigo, nombre) VALUES (%s,%s) ON CONFLICT (codigo) DO NOTHING",
                    (codigo, codigo.capitalize()))


def upsert_zonas(cur, filas):
    """dim_zona desde logistica.zona. Las zonas que Odoo ya no tiene quedan inactivas (los hechos las referencian)."""
    codigos = []
    for f in filas:
        codigo = n.texto(f.get("code"))
        if not codigo:
            continue
        lat, lon = n.coordenada(f.get("latitude"), f.get("longitude"))
        activa = f.get("active") is not False
        cur.execute(
            """INSERT INTO dim_zona (codigo, nombre, latitud, longitud, zona_id_odoo, activa)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (codigo) DO UPDATE SET nombre=EXCLUDED.nombre, latitud=EXCLUDED.latitud,
                 longitud=EXCLUDED.longitud, zona_id_odoo=EXCLUDED.zona_id_odoo, activa=EXCLUDED.activa""",
            (codigo, n.texto(f.get("name")) or codigo, lat, lon, f.get("id"), activa))
        codigos.append(codigo)
    cur.execute("UPDATE dim_zona SET activa=false WHERE zona_id_odoo IS NOT NULL AND codigo <> ALL(%s)", (codigos,))


def upsert_conductor(cur, ctx, cid, nombre):
    if cid is None:
        return None
    cur.execute(
        """INSERT INTO dim_conductor (conductor_id_odoo, nombre) VALUES (%s,%s)
           ON CONFLICT (conductor_id_odoo) DO UPDATE SET nombre = COALESCE(EXCLUDED.nombre, dim_conductor.nombre)
           RETURNING sk""", (cid, nombre))
    ctx.conductor[cid] = cur.fetchone()[0]
    return ctx.conductor[cid]


def upsert_cliente(cur, ctx, cid, nombre, ciudad=None, zona_sk=None):
    if cid is None:
        return None
    cur.execute(
        """INSERT INTO dim_cliente (cliente_id_odoo, nombre, ciudad, zona_sk) VALUES (%s,%s,%s,%s)
           ON CONFLICT (cliente_id_odoo) DO UPDATE
           SET nombre = COALESCE(EXCLUDED.nombre, dim_cliente.nombre),
               ciudad = COALESCE(EXCLUDED.ciudad, dim_cliente.ciudad),
               zona_sk = COALESCE(EXCLUDED.zona_sk, dim_cliente.zona_sk)
           RETURNING sk""", (cid, nombre, ciudad, zona_sk))
    ctx.cliente[cid] = cur.fetchone()[0]
    return ctx.cliente[cid]


def upsert_producto(cur, ctx, pid, nombre, referencia=None, categoria=None, precio=None):
    if pid is None:
        return None
    cur.execute(
        """INSERT INTO dim_producto (producto_id_odoo, nombre, referencia, categoria, precio_lista)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (producto_id_odoo) DO UPDATE
           SET nombre = COALESCE(EXCLUDED.nombre, dim_producto.nombre),
               referencia = COALESCE(EXCLUDED.referencia, dim_producto.referencia),
               categoria = COALESCE(EXCLUDED.categoria, dim_producto.categoria),
               precio_lista = COALESCE(EXCLUDED.precio_lista, dim_producto.precio_lista)
           RETURNING sk""", (pid, nombre, referencia, categoria, precio))
    ctx.producto[pid] = cur.fetchone()[0]
    return ctx.producto[pid]


def upsert_vehiculo_simulado(cur, vid, placa):
    cur.execute(
        """INSERT INTO dim_vehiculo (vehiculo_id_odoo, placa, procedencia) VALUES (%s,%s,'SIMULADO')
           ON CONFLICT (vehiculo_id_odoo) DO UPDATE SET placa = EXCLUDED.placa RETURNING sk""", (vid, placa))
    return cur.fetchone()[0]


def _vehiculos(cur, ctx, odoo, traccar):
    """dim_vehiculo. El dispositivo sale de traccar.device de Odoo (traccar_device_id del vehiculo apunta a ese
    registro, cuyo campo traccar_id es el id en Traccar). Respaldo: dispositivo de Traccar con el nombre de la placa."""
    vehiculos = odoo.get("fleet.vehicle")
    if vehiculos is not None:
        id_traccar = {d["id"]: n.m2o_id(d.get("traccar_id")) for d in odoo.get("traccar.device") or []}
        por_nombre = {str(d.get("name") or "").upper(): d["id"] for d in (traccar or {}).get("devices") or []}
        for v in vehiculos:
            placa = n.texto(v.get("license_plate")) or n.texto(v.get("name"))
            dispositivo = id_traccar.get(n.m2o_id(v.get("traccar_device_id")))
            if dispositivo is None and placa:
                dispositivo = por_nombre.get(placa.upper())
            capacidad = n.numero(v.get("logistica_capacidad"))
            cur.execute(
                """INSERT INTO dim_vehiculo (vehiculo_id_odoo, placa, traccar_device_id, modelo, capacidad, procedencia)
                   VALUES (%s,%s,%s,%s,%s,'REAL')
                   ON CONFLICT (vehiculo_id_odoo) DO UPDATE
                   SET placa=EXCLUDED.placa, traccar_device_id=EXCLUDED.traccar_device_id, modelo=EXCLUDED.modelo,
                       capacidad=EXCLUDED.capacidad""",
                (v["id"], placa, dispositivo, n.m2o_nombre(v.get("model_id")),
                 int(capacidad) if capacidad is not None else None))
            cid = n.m2o_id(v.get("driver_id"))
            if cid is not None:
                upsert_conductor(cur, ctx, cid, n.m2o_nombre(v.get("driver_id")))
                ctx.conductor_de_vehiculo[v["id"]] = cid
    cur.execute("SELECT vehiculo_id_odoo, sk, traccar_device_id FROM dim_vehiculo WHERE procedencia='REAL'")
    for vid, sk, dispositivo in cur.fetchall():
        ctx.vehiculo[vid] = sk
        if dispositivo is not None:
            ctx.dispositivo[dispositivo] = (sk, vid)


def load_dimensions(cur, ctx, odoo, traccar):
    """Carga todas las dimensiones a partir del estado actual de Odoo y deja los mapas de claves en `ctx`."""
    if odoo.get("logistica.zona") is not None:
        upsert_zonas(cur, odoo["logistica.zona"])
    ctx.zonas = leer_zonas(cur)

    ciudad = {}
    for p in odoo.get("res.partner") or []:
        ciudad[p["id"]] = n.texto(p.get("city"))
        if p.get("is_driver"):
            upsert_conductor(cur, ctx, p["id"], n.texto(p.get("name")))
    _vehiculos(cur, ctx, odoo, traccar)
    for r in odoo.get("logistica.ruta") or []:
        cid = n.m2o_id(r.get("driver_id"))
        if cid is not None and cid not in ctx.conductor:
            upsert_conductor(cur, ctx, cid, n.m2o_nombre(r.get("driver_id")))

    # clientes: quien compra (pedido) y quien recibe (entrega); su zona es la del ultimo destino conocido
    for o in odoo.get("sale.order") or []:
        cid = n.m2o_id(o.get("partner_id"))
        lat, lon = n.coordenada(o.get("delivery_latitude"), o.get("delivery_longitude"))
        upsert_cliente(cur, ctx, cid, n.m2o_nombre(o.get("partner_id")), ciudad.get(cid), ctx.zona(lat, lon))
    for e in odoo.get("logistica.entrega") or []:
        cid = n.m2o_id(e.get("partner_id"))
        lat, lon = n.coordenada(e.get("latitude"), e.get("longitude"))
        upsert_cliente(cur, ctx, cid, n.m2o_nombre(e.get("partner_id")), ciudad.get(cid), ctx.zona(lat, lon))

    for p in odoo.get("product.product") or []:
        precio = n.numero(p.get("lst_price"))
        upsert_producto(cur, ctx, p["id"], n.texto(p.get("display_name")), n.texto(p.get("default_code")),
                        n.m2o_nombre(p.get("categ_id")), precio)
    for linea in odoo.get("sale.order.line") or []:
        pid = n.m2o_id(linea.get("product_id"))
        if pid is not None and pid not in ctx.producto:
            upsert_producto(cur, ctx, pid, n.m2o_nombre(linea.get("product_id")))
