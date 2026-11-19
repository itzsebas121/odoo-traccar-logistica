# -*- coding: utf-8 -*-
"""Recorridos GPS del historial de demostracion en Traccar.

El historial lo crea el modulo logistica_demo (seeds/seed.py con SEED_HISTORIAL=true): pedidos H-*, rutas cerradas
con horario y eventos de entrega. Ese modulo no envia posiciones a Traccar, asi que sin este script el DWH no tiene
recorridos para esas rutas (plan vs real, km por conductor y vinculo entrega-GPS quedan vacios).

Este script lee de Odoo las rutas cerradas del historial de los ultimos `--dias` dias (bodega -> paradas en orden ->
bodega, con la hora de llegada y de cierre de cada parada) y manda a Traccar, por OsmAnd con timestamp historico,
una posicion cada `--intervalo` segundos.

Repetir no duplica: lo enviado se anota en el parametro de Odoo `logistica_demo.gps_hasta` (ultima fecha de ruta
enviada) y se omite en la siguiente corrida; `--forzar` lo ignora. Solo biblioteca estandar.

Uso:  python seeds/gps_historico.py [--dias N] [--intervalo S] [--ruido M] [--forzar] [--plan]
"""
import argparse
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request
import xmlrpc.client
from datetime import date, datetime, timedelta, timezone

try:
    from seeds.simular import construir_url
except ImportError:  # ejecutado como script: python seeds/gps_historico.py
    from simular import construir_url

VERSION_HISTORIAL = 'historial-demo'      # optimization_version de las rutas que crea logistica_demo
PARAM_GPS_HASTA = 'logistica_demo.gps_hasta'
KNOTS_POR_KMH = 0.539957
RADIO_TIERRA_KM = 6371.0
FORMATO_ODOO = '%Y-%m-%d %H:%M:%S'


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


def _ts(texto):
    """Fecha de Odoo (UTC sin zona) -> segundos unix."""
    return datetime.strptime(texto, FORMATO_ODOO).replace(tzinfo=timezone.utc).timestamp()


def puntos_gps(ruta, bodega, intervalo_s, ruido_m, semilla=0):
    """Posiciones cada `intervalo_s`: bodega -> paradas -> bodega, quieto mientras dura cada parada.

    ruta: {'clave', 'inicio', 'fin', 'paradas': [{'lat', 'lon', 'llegada', 'cierre'}]} con fechas de Odoo (UTC).
    Devuelve [{'lat', 'lon', 'speed' (nudos), 'timestamp' (unix)}] en orden cronologico. Determinista por ruta."""
    rng = random.Random(f'{semilla}:gps:{ruta["clave"]}')
    ruido = ruido_m / 1000.0
    tramos, t, actual = [], _ts(ruta['inicio']), bodega
    for p in ruta['paradas']:
        destino = (p['lat'], p['lon'])
        tramos.append((actual, destino, t, _ts(p['llegada'])))
        tramos.append((destino, destino, _ts(p['llegada']), _ts(p['cierre'])))
        actual, t = destino, _ts(p['cierre'])
    tramos.append((actual, bodega, t, _ts(ruta['fin'])))
    puntos = []
    for (a, b, t0, t1) in tramos:
        dur = max(t1 - t0, 1.0)
        km = haversine_km(a[0], a[1], b[0], b[1])
        vel = km / (dur / 3600.0) if km > 0.01 else 0.0
        n = max(1, int(dur // intervalo_s))
        for i in range(n):
            f = i / n
            lat = a[0] + (b[0] - a[0]) * f
            lon = a[1] + (b[1] - a[1]) * f
            lat, lon = desplazar(lat, lon, rng.uniform(0, ruido), rng.uniform(0, 2 * math.pi))
            v = vel * rng.uniform(0.8, 1.2) if vel else 0.0
            puntos.append({'lat': round(lat, 6), 'lon': round(lon, 6), 'speed': round(v * KNOTS_POR_KMH, 1),
                           'timestamp': int(t0 + f * dur)})
    puntos.append({'lat': bodega[0], 'lon': bodega[1], 'speed': 0, 'timestamp': int(_ts(ruta['fin']))})
    return puntos


def armar_ruta(ruta, paradas, entregas):
    """Registro de Odoo -> ruta para puntos_gps. None si le falta horario o ninguna parada tiene hora y punto."""
    if not ruta.get('started_at') or not ruta.get('finished_at'):
        return None
    salida = []
    for p in sorted(paradas, key=lambda x: x['sequence']):
        entrega = entregas.get(p['entrega_id'][0]) if p.get('entrega_id') else None
        if not entrega or not p.get('actual_arrival_at') or not p.get('completed_at'):
            continue
        if not (entrega.get('latitude') or entrega.get('longitude')):
            continue
        salida.append({'lat': entrega['latitude'], 'lon': entrega['longitude'],
                       'llegada': p['actual_arrival_at'], 'cierre': p['completed_at']})
    if not salida:
        return None
    return {'clave': ruta['name'], 'inicio': ruta['started_at'], 'fin': ruta['finished_at'], 'paradas': salida}


# ---------------------------------------------------------------------------------------------------- Odoo
class ErrorGps(RuntimeError):
    """Fallo con mensaje listo para mostrar (sin credenciales)."""


class Odoo:
    def __init__(self, url, base, usuario, clave):
        self._base, self._clave = base, clave
        comun = xmlrpc.client.ServerProxy(url.rstrip('/') + '/xmlrpc/2/common', allow_none=True)
        self._uid = comun.authenticate(base, usuario, clave, {})
        if not self._uid:
            raise ErrorGps('autenticacion de Odoo fallida (revise ODOO_DB, ODOO_USER y ODOO_PASSWORD)')
        self._obj = xmlrpc.client.ServerProxy(url.rstrip('/') + '/xmlrpc/2/object', allow_none=True)

    def __call__(self, modelo, metodo, args, kwargs=None):
        return self._obj.execute_kw(self._base, self._uid, self._clave, modelo, metodo, args, kwargs or {})


def leer_rutas(odoo, desde, hasta_excluida=None):
    """Rutas cerradas del historial con fecha en [desde, hoy). Devuelve [(ruta_odoo, ruta_gps, unique_id)]."""
    dominio = [('optimization_version', '=', VERSION_HISTORIAL), ('state', '=', 'cerrada'),
               ('date', '>=', desde.isoformat())]
    if hasta_excluida:
        dominio.append(('date', '>', hasta_excluida.isoformat()))
    rutas = odoo('logistica.ruta', 'search_read', [dominio],
                 {'fields': ['name', 'date', 'vehicle_id', 'started_at', 'finished_at'], 'order': 'date, id'})
    if not rutas:
        return []
    paradas = odoo('logistica.ruta.parada', 'search_read', [[('route_id', 'in', [r['id'] for r in rutas])]],
                   {'fields': ['route_id', 'sequence', 'entrega_id', 'actual_arrival_at', 'completed_at']})
    ids_entrega = sorted({p['entrega_id'][0] for p in paradas if p.get('entrega_id')})
    entregas = {e['id']: e for e in odoo('logistica.entrega', 'read', [ids_entrega], {'fields': ['latitude', 'longitude']})}
    vehiculos = {v['id']: v for v in odoo('fleet.vehicle', 'search_read',
                                          [[('id', 'in', sorted({r['vehicle_id'][0] for r in rutas if r['vehicle_id']}))]],
                                          {'fields': ['traccar_device_id'], 'context': {'active_test': False}})}
    dispositivos = {d['id']: d['unique_id'] for d in odoo('traccar.device', 'search_read', [[]], {'fields': ['unique_id']})}
    por_ruta = {}
    for p in paradas:
        por_ruta.setdefault(p['route_id'][0], []).append(p)
    salida = []
    for r in rutas:
        vehiculo = vehiculos.get(r['vehicle_id'][0]) if r['vehicle_id'] else None
        dispositivo = vehiculo and vehiculo['traccar_device_id'] and dispositivos.get(vehiculo['traccar_device_id'][0])
        gps = armar_ruta(r, por_ruta.get(r['id'], []), entregas)
        salida.append((r, gps, dispositivo or None))
    return salida


def leer_bodega(odoo):
    filas = odoo('logistica.bodega', 'search_read', [[('active', '=', True)]],
                 {'fields': ['latitude', 'longitude'], 'limit': 1})
    if not filas or not (filas[0]['latitude'] or filas[0]['longitude']):
        raise ErrorGps('no hay bodega activa con coordenadas en Odoo: corra antes seeds/seed.py')
    return float(filas[0]['latitude']), float(filas[0]['longitude'])


# ---------------------------------------------------------------------------------------------------- Traccar
def enviar_gps(base, unique_id, puntos):
    for punto in puntos:
        peticion = urllib.request.Request(construir_url(base, unique_id, punto), method='GET')
        try:
            with urllib.request.urlopen(peticion, timeout=10) as respuesta:
                if respuesta.status != 200:
                    raise ErrorGps(f'OsmAnd respondio HTTP {respuesta.status}')
        except urllib.error.HTTPError as error:
            raise ErrorGps(f'OsmAnd respondio HTTP {error.code}') from None
        except urllib.error.URLError as error:
            raise ErrorGps(f'no hay respuesta de OsmAnd ({error.reason})') from None
    return len(puntos)


# ---------------------------------------------------------------------------------------------------- main
def _argumentos(argv):
    a = argparse.ArgumentParser(description='Recorridos GPS del historial de demostracion en Traccar')
    a.add_argument('--dias', type=int, default=30, help='dias hacia atras con GPS (por defecto 30)')
    a.add_argument('--intervalo', type=int, default=30, help='segundos entre posiciones (por defecto 30)')
    a.add_argument('--ruido', type=float, default=8.0, help='ruido maximo del GPS en metros (por defecto 8)')
    a.add_argument('--forzar', action='store_true', help=f'ignora {PARAM_GPS_HASTA} y reenvia todo el rango')
    a.add_argument('--plan', action='store_true', help='solo cuenta rutas y posiciones (no envia nada)')
    return a.parse_args(argv)


def main(argv=None):
    args = _argumentos(argv)
    faltan = [n for n in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD') if not os.environ.get(n)]
    url_gps = (os.environ.get('TRACCAR_OSMAND_URL') or '').strip()
    if not url_gps and not args.plan:
        faltan.append('TRACCAR_OSMAND_URL')
    if faltan:
        print('gps_historico: faltan variables de entorno (revise .env): ' + ', '.join(faltan), file=sys.stderr)
        return 1
    informe = {'rutas': 0, 'rutas_sin_horario': 0, 'rutas_sin_dispositivo': 0, 'posiciones': 0}
    try:
        odoo = Odoo(os.environ['ODOO_URL'], os.environ['ODOO_DB'], os.environ['ODOO_USER'],
                    os.environ['ODOO_PASSWORD'])
        bodega = leer_bodega(odoo)
        hecho = None if args.forzar else odoo('ir.config_parameter', 'get_param', [PARAM_GPS_HASTA])
        hecho = date.fromisoformat(hecho) if hecho else None
        desde = date.today() - timedelta(days=args.dias)
        ultima = None
        for ruta, gps, dispositivo in leer_rutas(odoo, desde, hecho):
            if gps is None:
                informe['rutas_sin_horario'] += 1
                continue
            if not dispositivo:
                informe['rutas_sin_dispositivo'] += 1
                continue
            puntos = puntos_gps(gps, bodega, args.intervalo, args.ruido)
            informe['rutas'] += 1
            informe['posiciones'] += len(puntos) if args.plan else enviar_gps(url_gps, dispositivo, puntos)
            ultima = ruta['date']
        if ultima and not args.plan:
            odoo('ir.config_parameter', 'set_param', [PARAM_GPS_HASTA, ultima])
    except ErrorGps as error:
        print(f'gps_historico: {error}', file=sys.stderr)
        return 1
    except xmlrpc.client.Fault as error:
        lineas = [linea for linea in str(error.faultString).splitlines() if linea.strip()]
        print(f'gps_historico: Odoo rechazo la operacion: {lineas[-1] if lineas else "error sin detalle"}',
              file=sys.stderr)
        return 1
    except (OSError, xmlrpc.client.ProtocolError) as error:
        print(f'gps_historico: no se pudo conectar con Odoo o Traccar: {error}', file=sys.stderr)
        return 1
    print(json.dumps(informe, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
