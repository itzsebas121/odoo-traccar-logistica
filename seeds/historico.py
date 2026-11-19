# -*- coding: utf-8 -*-
"""Sembrado del historico de demostracion (pedidos, entregas, rutas y GPS) para entrenar el pronostico de demanda.

Solo biblioteca estandar. Los datos de negocio salen de seeds/data/historico.json (clientes por parroquia de Ambato,
productos de alimentos y de uso domestico, calendario de Ecuador) y de seeds/data/odoo.json (vehiculos, conductores
y bodega). Nada de eso se repite en este archivo.

Flujo:
  1. Instala en Odoo el modulo logistica_demo_historico si falta.
  2. Asegura categorias, productos y clientes (idempotente).
  3. Por cada dia: pedidos del dia y rutas que entregan los pedidos del dia anterior (y los fallidos), en una sola
     llamada a logistica.demo.historico.registrar_dia, que fecha todo en el pasado.
  4. Envia a Traccar (OsmAnd, con timestamp historico) el GPS de las rutas de los ultimos `dias_gps` dias.

El plan es determinista: cada dia de calendario sale igual con la misma semilla, se corra cuando se corra. Repetir
no duplica (Odoo omite pedidos y rutas que ya existen; Traccar si recibiria otra vez las posiciones, asi que
--sin-gps evita reenviarlas).

Uso:  python seeds/historico.py [--dias N] [--dias-gps N] [--semilla S] [--sin-gps] [--plan]
"""
import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
import xmlrpc.client
from datetime import datetime, timedelta, timezone

try:
    from seeds import schema
except ImportError:  # ejecutado como script: python seeds/historico.py
    import schema

MODULO = 'logistica_demo_historico'
KNOTS_POR_KMH = 0.539957
RADIO_TIERRA_KM = 6371.0
PARADAS_POR_RUTA = 9


# ---------------------------------------------------------------------------------------------------- geometria
def haversine_km(lat1, lon1, lat2, lon2):
    f1, f2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((f2 - f1) / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))


def desplazar(lat, lon, dist_km, rumbo_rad):
    """Punto a `dist_km` en direccion `rumbo_rad` (aproximacion plana, valida para pocos km)."""
    dlat = dist_km * math.cos(rumbo_rad) / 111.32
    dlon = dist_km * math.sin(rumbo_rad) / (111.32 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def rumbo(lat0, lon0, lat, lon):
    return math.atan2((lon - lon0) * math.cos(math.radians(lat0)), lat - lat0)


# ---------------------------------------------------------------------------------------------------- clientes
def construir_clientes(datos, semilla):
    """Clientes deterministas: nombre unico, parroquia, coordenada dentro del radio, tienda o hogar."""
    cfg = datos['clientes']
    rng = random.Random(f'{semilla}:clientes')
    usados, clientes = set(), []
    for parroquia in datos['parroquias']:
        for _ in range(parroquia['clientes']):
            tienda = rng.random() < cfg['fraccion_tiendas']
            while True:
                nombre = f"{rng.choice(cfg['nombres'])} {rng.choice(cfg['apellidos'])}"
                if tienda:
                    nombre = f"{rng.choice(cfg['tipos_tienda'])} {nombre}"
                if nombre not in usados:
                    usados.add(nombre)
                    break
            dist = parroquia['radio_km'] * math.sqrt(rng.random())
            lat, lon = desplazar(parroquia['lat'], parroquia['lon'], dist, rng.uniform(0, 2 * math.pi))
            clientes.append({
                'name': nombre,
                'parroquia': parroquia['nombre'],
                'tipo': parroquia['tipo'],
                'peso': parroquia['peso'] * (cfg['factor_tienda'] if tienda else 1.0),
                'tienda': tienda,
                'lat': round(lat, 6), 'lon': round(lon, 6),
                'street': f"{rng.choice(cfg['calles'])} y {rng.choice(cfg['calles'])}",
                'phone': cfg['prefijo_telefono'] + ''.join(str(rng.randint(0, 9)) for _ in range(8)),
                'city': cfg['ciudad'],
            })
    return clientes


# ---------------------------------------------------------------------------------------------------- demanda
def _hash01(*partes):
    """Numero estable en [0, 1) a partir de textos (no depende de PYTHONHASHSEED)."""
    h = hashlib.sha1(':'.join(str(p) for p in partes).encode('utf-8')).hexdigest()
    return int(h[:8], 16) / 0x100000000


def afinidad(producto, cliente, categorias, semilla):
    """Peso del producto para un cliente: afinidad de la categoria por tipo de parroquia por un factor local
    estable (0,6 a 1,6) del producto en la parroquia. Es lo que hace que la demanda dependa de la ubicacion."""
    cat = categorias[producto['categoria']]
    local = 0.6 + _hash01(semilla, producto['default_code'], cliente['parroquia'])
    return producto['demanda_dia'] * cat['afinidad'][cliente['tipo']] * local


def factor_dia(dia, calendario):
    """Multiplicador de la demanda del dia: dia de la semana, quincena, feriado o vispera y tendencia (contada
    desde fecha_base_tendencia, fija: asi un dia sale igual sea cual sea la ventana que se siembre)."""
    f = calendario['peso_dia_semana'][dia.weekday()]
    if dia.day in calendario['quincena']['dias']:
        f *= calendario['quincena']['factor']
    feriados = {x['fecha']: x for x in calendario['feriados']}
    hoy, manana = dia.isoformat(), (dia + timedelta(days=1)).isoformat()
    if hoy in feriados:
        f *= feriados[hoy]['factor']
    elif manana in feriados:
        f *= feriados[manana]['factor_vispera']
    base = datetime.strptime(calendario['fecha_base_tendencia'], '%Y-%m-%d').date()
    f *= 1.0 + calendario['tendencia_anual'] * (dia - base).days / 365.0
    return f


def _poisson(rng, lam):
    """Poisson por el metodo de Knuth (lam moderado) o aproximacion normal (lam grande)."""
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def _elegir(rng, items, pesos):
    total = sum(pesos)
    x, acum = rng.random() * total, 0.0
    for item, peso in zip(items, pesos):
        acum += peso
        if x <= acum:
            return item
    return items[-1]


# ---------------------------------------------------------------------------------------------------- plan
def _utc(dia, hora_local, offset_h):
    """Fecha y hora local (horas decimales) -> datetime UTC naive (formato de Odoo)."""
    local = datetime(dia.year, dia.month, dia.day) + timedelta(hours=hora_local)
    return local - timedelta(hours=offset_h)


def _fmt(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def pedidos_del_dia(datos, clientes, dia, semilla):
    op, categorias = datos['operacion'], {c['nombre']: c for c in datos['categorias']}
    rng = random.Random(f'{semilla}:pedidos:{dia.isoformat()}')
    n = _poisson(rng, op['pedidos_dia_base'] * factor_dia(dia, datos['calendario']))
    pesos_clientes = [c['peso'] for c in clientes]
    productos = datos['productos']
    h0, h1 = op['hora_pedidos']
    horas = sorted(rng.uniform(h0, h1) for _ in range(n))
    pedidos = []
    for i, hora in enumerate(horas, 1):
        ci = _elegir(rng, list(range(len(clientes))), pesos_clientes)
        cliente = clientes[ci]
        pesos = [afinidad(p, cliente, categorias, semilla) for p in productos]
        n_lineas = rng.randint(*op['lineas_por_pedido'])
        elegidos = []
        for _ in range(n_lineas):
            pi = _elegir(rng, list(range(len(productos))), pesos)
            if pi not in elegidos:
                elegidos.append(pi)
        escala = datos['clientes']['factor_tienda'] if cliente['tienda'] else 1.0
        lineas = [(pi, 1 + _poisson(rng, 0.6 * escala)) for pi in elegidos]
        # Ruido de GPS del selector de mapa (unos metros): el pedido no cae exactamente en la casa.
        lat, lon = desplazar(cliente['lat'], cliente['lon'], rng.uniform(0, 0.02), rng.uniform(0, 2 * math.pi))
        pedidos.append({
            'ref': f"{op['prefijo_pedido']}-{dia.strftime('%Y%m%d')}-{i:03d}",
            'cliente': ci,
            'lat': round(lat, 6), 'lon': round(lon, 6),
            'fecha': _fmt(_utc(dia, hora, op['utc_offset_h'])),
            'lineas': lineas,
        })
    return pedidos


def _orden_vecino(bodega, puntos):
    """Orden de visita por vecino mas cercano desde la bodega."""
    pendientes, orden, actual = list(puntos), [], bodega
    while pendientes:
        sig = min(pendientes, key=lambda p: haversine_km(actual[0], actual[1], p['lat'], p['lon']))
        pendientes.remove(sig)
        orden.append(sig)
        actual = (sig['lat'], sig['lon'])
    return orden


def rutas_del_dia(datos, vehiculos, bodega, dia, por_entregar, semilla):
    """Reparte las entregas pendientes entre los vehiculos (sectores angulares desde la bodega) y calcula los tiempos
    de cada parada. Devuelve (rutas, fallidas): las fallidas se vuelven a intentar al dia siguiente."""
    if not por_entregar:
        return [], []
    op = datos['operacion']
    rng = random.Random(f'{semilla}:rutas:{dia.isoformat()}')
    ordenadas = sorted(por_entregar, key=lambda p: rumbo(bodega[0], bodega[1], p['lat'], p['lon']))
    k = min(len(vehiculos), max(1, math.ceil(len(ordenadas) / PARADAS_POR_RUTA)))
    tam = math.ceil(len(ordenadas) / k)
    giro = dia.toordinal() % len(vehiculos)
    rutas, fallidas = [], []
    for j in range(k):
        grupo = ordenadas[j * tam:(j + 1) * tam]
        if not grupo:
            continue
        vi = (j + giro) % len(vehiculos)
        veh = vehiculos[vi]
        salida = op['hora_salida_ruta'] + rng.uniform(0, 0.4)
        t = _utc(dia, salida, op['utc_offset_h'])
        carga = t - timedelta(minutes=25)
        inicio, actual, km_total, paradas = t, bodega, 0.0, []
        for p in _orden_vecino(bodega, grupo):
            km = haversine_km(actual[0], actual[1], p['lat'], p['lon']) * op['factor_via']
            km_total += km
            t += timedelta(minutes=km / op['velocidad_kmh'] * 60 * rng.uniform(0.9, 1.25) + 1)
            llegada = t
            t += timedelta(minutes=rng.uniform(*op['minutos_parada']))
            falla = rng.random() < op['tasa_no_entrega']
            paradas.append({'ref': p['ref'], 'lat': p['lat'], 'lon': p['lon'],
                            'llegada': _fmt(llegada), 'cierre': _fmt(t),
                            'resultado': 'no_entregado' if falla else 'entregado',
                            'motivo': rng.choice(op['motivos_no_entrega']) if falla else None})
            if falla:
                fallidas.append(p)
            actual = (p['lat'], p['lon'])
        km = haversine_km(actual[0], actual[1], bodega[0], bodega[1]) * op['factor_via']
        km_total += km
        t += timedelta(minutes=km / op['velocidad_kmh'] * 60 * rng.uniform(0.9, 1.2) + 1)
        rutas.append({
            'clave': f"{dia.isoformat()}:{veh['license_plate']}",
            'vehiculo': vi,
            'fecha': dia.isoformat(),
            'carga': _fmt(carga), 'inicio': _fmt(inicio), 'fin': _fmt(t),
            'km': round(km_total, 2),
            'min': round((t - inicio).total_seconds() / 60.0, 1),
            'paradas': paradas,
        })
    return rutas, fallidas


def planificar(datos, vehiculos, bodega, hoy, dias=None, semilla=None):
    """Plan completo: [{'fecha', 'pedidos', 'rutas'}] para los `dias` dias anteriores a `hoy` (fecha local).
    Los pedidos de un dia se entregan al dia siguiente; los fallidos, al otro."""
    op = datos['operacion']
    dias = op['dias_ventas'] if dias is None else dias
    semilla = op['semilla'] if semilla is None else semilla
    clientes = construir_clientes(datos, semilla)
    inicio = hoy - timedelta(days=dias)
    plan, por_entregar = [], []
    for d in range(dias):
        dia = inicio + timedelta(days=d)
        rutas, fallidas = rutas_del_dia(datos, vehiculos, bodega, dia, por_entregar, semilla)
        pedidos = pedidos_del_dia(datos, clientes, dia, semilla)
        plan.append({'fecha': dia.isoformat(), 'pedidos': pedidos, 'rutas': rutas})
        por_entregar = pedidos + fallidas
    return clientes, plan


# ---------------------------------------------------------------------------------------------------- GPS
def puntos_gps(ruta, bodega, op, semilla):
    """Posiciones de la ruta cada `intervalo_gps_s`: bodega -> paradas -> bodega, con espera en cada parada.
    Devuelve [{'lat','lon','speed' (nudos),'timestamp' (unix)}] en orden cronologico."""
    rng = random.Random(f"{semilla}:gps:{ruta['clave']}")
    paso = op['intervalo_gps_s']
    ruido = op['ruido_gps_m'] / 1000.0

    def ts(texto):
        return datetime.strptime(texto, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()

    tramos, t, actual = [], ts(ruta['inicio']), bodega
    for p in ruta['paradas']:
        tramos.append((actual, (p['lat'], p['lon']), t, ts(p['llegada'])))
        tramos.append(((p['lat'], p['lon']), (p['lat'], p['lon']), ts(p['llegada']), ts(p['cierre'])))
        actual, t = (p['lat'], p['lon']), ts(p['cierre'])
    tramos.append((actual, bodega, t, ts(ruta['fin'])))
    puntos = []
    for (a, b, t0, t1) in tramos:
        dur = max(t1 - t0, 1.0)
        km = haversine_km(a[0], a[1], b[0], b[1])
        vel = km / (dur / 3600.0) if km > 0.01 else 0.0
        n = max(1, int(dur // paso))
        for i in range(n):
            f = i / n
            lat = a[0] + (b[0] - a[0]) * f
            lon = a[1] + (b[1] - a[1]) * f
            lat, lon = desplazar(lat, lon, rng.uniform(0, ruido), rng.uniform(0, 2 * math.pi))
            v = vel * rng.uniform(0.8, 1.2) if vel else 0.0
            puntos.append({'lat': round(lat, 6), 'lon': round(lon, 6), 'speed': round(v * KNOTS_POR_KMH, 1),
                           'timestamp': int(t0 + f * dur)})
    puntos.append({'lat': bodega[0], 'lon': bodega[1], 'speed': 0, 'timestamp': int(ts(ruta['fin']))})
    return puntos


# ---------------------------------------------------------------------------------------------------- Odoo
class ErrorHistorico(RuntimeError):
    """Fallo con mensaje listo para mostrar (sin credenciales)."""


class Odoo:
    def __init__(self, url, base, usuario, clave):
        self._base, self._clave = base, clave
        comun = xmlrpc.client.ServerProxy(url.rstrip('/') + '/xmlrpc/2/common', allow_none=True)
        self._uid = comun.authenticate(base, usuario, clave, {})
        if not self._uid:
            raise ErrorHistorico('autenticacion de Odoo fallida (revise ODOO_DB, ODOO_USER y ODOO_PASSWORD)')
        self._obj = xmlrpc.client.ServerProxy(url.rstrip('/') + '/xmlrpc/2/object', allow_none=True)

    def __call__(self, modelo, metodo, args, kwargs=None):
        return self._obj.execute_kw(self._base, self._uid, self._clave, modelo, metodo, args, kwargs or {})


def _asegurar(odoo, modelo, dominio, valores):
    ids = odoo(modelo, 'search', [dominio], {'limit': 1, 'context': {'active_test': False}})
    if ids:
        return ids[0], False
    return odoo(modelo, 'create', [valores]), True


def instalar_modulo(odoo):
    mod = odoo('ir.module.module', 'search_read', [[('name', '=', MODULO)]], {'fields': ['state']})
    if not mod:
        odoo('ir.module.module', 'update_list', [])
        mod = odoo('ir.module.module', 'search_read', [[('name', '=', MODULO)]], {'fields': ['state']})
    if not mod:
        raise ErrorHistorico(f'Odoo no encuentra el modulo {MODULO} (revise el montaje de odoo/addons)')
    if mod[0]['state'] != 'installed':
        odoo('ir.module.module', 'button_immediate_install', [[mod[0]['id']]])
        return True
    return False


def sembrar_catalogo(odoo, datos, clientes, informe):
    """Categorias, productos y clientes. Devuelve (ids de product.product por indice, ids de partner por indice)."""
    grupos, cats = {}, {}
    for c in datos['categorias']:
        if c['grupo'] not in grupos:
            grupos[c['grupo']], nuevo = _asegurar(odoo, 'product.category', [('name', '=', c['grupo']),
                                                                              ('parent_id', '=', False)],
                                                  {'name': c['grupo']})
            informe['categorias'] += int(nuevo)
        cats[c['nombre']], nuevo = _asegurar(odoo, 'product.category',
                                             [('name', '=', c['nombre']), ('parent_id', '=', grupos[c['grupo']])],
                                             {'name': c['nombre'], 'parent_id': grupos[c['grupo']]})
        informe['categorias'] += int(nuevo)
    productos = []
    for p in datos['productos']:
        tmpl, nuevo = _asegurar(odoo, 'product.template', [('default_code', '=', p['default_code'])], {
            'name': p['name'], 'default_code': p['default_code'], 'list_price': p['list_price'],
            'categ_id': cats[p['categoria']], 'type': 'consu', 'sale_ok': True, 'website_published': True})
        informe['productos'] += int(nuevo)
        variante = odoo('product.product', 'search', [[('product_tmpl_id', '=', tmpl)]],
                        {'limit': 1, 'context': {'active_test': False}})
        productos.append(variante[0])
    partners = []
    for c in clientes:
        pid, nuevo = _asegurar(odoo, 'res.partner', [('name', '=', c['name'])], {
            'name': c['name'], 'street': c['street'], 'city': c['city'], 'phone': c['phone'],
            'is_company': c['tienda'], 'delivery_latitude': c['lat'], 'delivery_longitude': c['lon']})
        informe['clientes'] += int(nuevo)
        partners.append(pid)
    return productos, partners


def leer_vehiculos(odoo):
    """Flota que reparte: los vehiculos de Odoo con conductor, en orden de placa. uniqueId es el del dispositivo
    Traccar vinculado (None si no tiene: esas rutas quedan sin GPS)."""
    filas = odoo('fleet.vehicle', 'search_read', [[('driver_id', '!=', False)]],
                 {'fields': ['license_plate', 'driver_id', 'traccar_device_id'], 'order': 'license_plate'})
    if not filas:
        raise ErrorHistorico('no hay vehiculos con conductor en Odoo: corra antes seeds/seed.py')
    dispositivos = {d['id']: d['unique_id'] for d in odoo('traccar.device', 'search_read', [[]],
                                                          {'fields': ['unique_id']})}
    return [{'license_plate': f['license_plate'], 'vehicle_id': f['id'], 'driver_id': f['driver_id'][0],
             'uniqueId': dispositivos.get(f['traccar_device_id'][0]) if f['traccar_device_id'] else None}
            for f in filas]


def leer_bodega(odoo, por_defecto):
    """Coordenadas de la bodega activa de Odoo (de donde salen las rutas); si no hay, las de odoo.json."""
    filas = odoo('logistica.bodega', 'search_read', [[('active', '=', True)]],
                 {'fields': ['latitude', 'longitude'], 'limit': 1})
    if filas and (filas[0]['latitude'] or filas[0]['longitude']):
        return float(filas[0]['latitude']), float(filas[0]['longitude'])
    return por_defecto


def carga_del_dia(dia, productos, partners, vehiculos):
    """Plan de un dia -> argumentos de registrar_dia (ids de Odoo)."""
    return {
        'pedidos': [{'ref': p['ref'], 'partner_id': partners[p['cliente']], 'lat': p['lat'], 'lon': p['lon'],
                     'fecha': p['fecha'], 'lineas': [[productos[i], q] for i, q in p['lineas']]}
                    for p in dia['pedidos']],
        'rutas': [{'clave': r['clave'], 'vehicle_id': vehiculos[r['vehiculo']]['vehicle_id'],
                   'driver_id': vehiculos[r['vehiculo']]['driver_id'], 'fecha': r['fecha'], 'carga': r['carga'],
                   'inicio': r['inicio'], 'fin': r['fin'], 'km': r['km'], 'min': r['min'],
                   'paradas': [{k: s[k] for k in ('ref', 'llegada', 'cierre', 'resultado', 'motivo')}
                               for s in r['paradas']]}
                  for r in dia['rutas']],
    }


# ---------------------------------------------------------------------------------------------------- Traccar
def enviar_gps(base, unique_id, puntos, construir_url):
    for punto in puntos:
        peticion = urllib.request.Request(construir_url(base, unique_id, punto), method='GET')
        try:
            with urllib.request.urlopen(peticion, timeout=10) as respuesta:
                if respuesta.status != 200:
                    raise ErrorHistorico(f'OsmAnd respondio HTTP {respuesta.status}')
        except urllib.error.HTTPError as error:
            raise ErrorHistorico(f'OsmAnd respondio HTTP {error.code}') from None
        except urllib.error.URLError as error:
            raise ErrorHistorico(f'no hay respuesta de OsmAnd ({error.reason})') from None
    return len(puntos)


# ---------------------------------------------------------------------------------------------------- main
def _argumentos(argv):
    a = argparse.ArgumentParser(description='Historico de demostracion (Ambato) en Odoo y Traccar')
    a.add_argument('--dias', type=int, help='dias de pedidos (por defecto operacion.dias_ventas)')
    a.add_argument('--dias-gps', type=int, help='dias con GPS en Traccar (por defecto operacion.dias_gps)')
    a.add_argument('--semilla', type=int)
    a.add_argument('--sin-gps', action='store_true', help='no envia posiciones a Traccar')
    a.add_argument('--plan', action='store_true', help='solo imprime el resumen del plan (no usa la red)')
    return a.parse_args(argv)


def main(argv=None):
    args = _argumentos(argv)
    try:
        datos = schema.cargar_historico()
        odoo_json, _traccar, _sim = schema.cargar()
    except schema.ErrorEsquema as error:
        print(f'historico: datos invalidos: {error}', file=sys.stderr)
        return 1
    op = datos['operacion']
    semilla = op['semilla'] if args.semilla is None else args.semilla
    dias = op['dias_ventas'] if args.dias is None else args.dias
    dias_gps = op['dias_gps'] if args.dias_gps is None else args.dias_gps
    tz = timezone(timedelta(hours=op['utc_offset_h']))
    hoy = datetime.now(tz).date()
    bodega = (odoo_json['bodega_logistica']['latitude'], odoo_json['bodega_logistica']['longitude'])

    def resumir(clientes, plan):
        return {'dias': len(plan), 'clientes': len(clientes),
                'pedidos': sum(len(d['pedidos']) for d in plan),
                'lineas': sum(len(p['lineas']) for d in plan for p in d['pedidos']),
                'rutas': sum(len(d['rutas']) for d in plan),
                'desde': plan[0]['fecha'] if plan else None, 'hasta': plan[-1]['fecha'] if plan else None}

    if args.plan:      # sin red: flota y bodega de odoo.json
        plantilla = [{'license_plate': v['license_plate'], 'uniqueId': v['uniqueId']} for v in odoo_json['vehiculos']]
        print(json.dumps(resumir(*planificar(datos, plantilla, bodega, hoy, dias, semilla)), indent=2,
                         ensure_ascii=False))
        return 0

    faltan = [n for n in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD') if not os.environ.get(n)]
    if faltan:
        print('historico: faltan variables de entorno (revise .env): ' + ', '.join(faltan), file=sys.stderr)
        return 1
    informe = {'modulo_instalado': False, 'categorias': 0, 'productos': 0, 'clientes': 0,
               'pedidos_creados': 0, 'pedidos_omitidos': 0, 'rutas_creadas': 0, 'rutas_omitidas': 0,
               'paradas': 0, 'posiciones_gps': 0}
    try:
        odoo = Odoo(os.environ['ODOO_URL'], os.environ['ODOO_DB'], os.environ['ODOO_USER'],
                    os.environ['ODOO_PASSWORD'])
        informe['modulo_instalado'] = instalar_modulo(odoo)
        vehiculos = leer_vehiculos(odoo)
        bodega = leer_bodega(odoo, bodega)
        clientes, plan = planificar(datos, vehiculos, bodega, hoy, dias, semilla)
        resumen = resumir(clientes, plan)
        productos, partners = sembrar_catalogo(odoo, datos, clientes, informe)
        inicio = time.time()
        for n, dia in enumerate(plan, 1):
            conteo = odoo('logistica.demo.historico', 'registrar_dia',
                          [carga_del_dia(dia, productos, partners, vehiculos)])
            for k, v in conteo.items():
                informe[k] = informe.get(k, 0) + v
            if n % 10 == 0 or n == len(plan):
                print(f"historico: {n}/{len(plan)} dias ({dia['fecha']}) en {time.time() - inicio:.0f} s",
                      file=sys.stderr)

        url_gps = os.environ.get('TRACCAR_OSMAND_URL', '').strip()
        if not args.sin_gps and dias_gps > 0:
            if not url_gps:
                print('historico: falta TRACCAR_OSMAND_URL; no se envia GPS', file=sys.stderr)
            else:
                try:
                    from seeds.simular import construir_url
                except ImportError:
                    from simular import construir_url
                for dia in plan[-dias_gps:]:
                    for r in dia['rutas']:
                        if not vehiculos[r['vehiculo']]['uniqueId']:
                            continue
                        informe['posiciones_gps'] += enviar_gps(
                            url_gps, vehiculos[r['vehiculo']]['uniqueId'], puntos_gps(r, bodega, op, semilla),
                            construir_url)
    except ErrorHistorico as error:
        print(f'historico: {error}', file=sys.stderr)
        return 1
    except xmlrpc.client.Fault as error:
        lineas = [linea for linea in str(error.faultString).splitlines() if linea.strip()]
        print(f'historico: Odoo rechazo la operacion: {lineas[-1] if lineas else "error sin detalle"}',
              file=sys.stderr)
        return 1
    except (OSError, xmlrpc.client.ProtocolError) as error:
        print(f'historico: no se pudo conectar con Odoo o Traccar: {error}', file=sys.stderr)
        return 1
    print(json.dumps(dict(resumen, **informe), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
