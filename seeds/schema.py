# -*- coding: utf-8 -*-
"""Esquema de los JSON de seeds/data/ (solo biblioteca estandar).

Los nombres de las claves coinciden con los campos de Odoo (name, is_company, function, license_plate)
o con la API REST de Traccar (name, uniqueId, attributes, area) cuando reflejan esos sistemas.
Las claves que empiezan por "_" son documentacion: no se validan y el seeder no las usa.
"""
import json
import os
import re

DIRECTORIO_DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
ARCHIVO_ODOO = 'odoo.json'
ARCHIVO_TRACCAR = 'traccar.json'
ARCHIVO_SIMULACION = 'simulacion.json'

_AREA_CIRCULO = re.compile(r'^CIRCLE \((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?), (\d+(?:\.\d+)?)\)$')


class ErrorEsquema(ValueError):
    """Un archivo de seeds/data no cumple el esquema. El mensaje nombra el archivo y el campo."""


def _campo(objeto, campo, donde):
    if campo not in objeto:
        raise ErrorEsquema(f"{donde}: falta el campo obligatorio '{campo}'")
    return objeto[campo]


def _objeto(valor, donde):
    if not isinstance(valor, dict):
        raise ErrorEsquema(f'{donde}: se esperaba un objeto JSON')
    return valor


def _lista(valor, donde):
    if not isinstance(valor, list) or not valor:
        raise ErrorEsquema(f'{donde}: se esperaba una lista con al menos un elemento')
    return valor


def _texto(objeto, campo, donde):
    valor = _campo(objeto, campo, donde)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorEsquema(f"{donde}: '{campo}' debe ser un texto no vacio")
    return valor


def _numero(objeto, campo, donde, minimo, maximo=None, exclusivo_minimo=False):
    valor = _campo(objeto, campo, donde)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorEsquema(f"{donde}: '{campo}' debe ser un numero")
    fuera_inferior = valor <= minimo if exclusivo_minimo else valor < minimo
    if fuera_inferior or (maximo is not None and valor > maximo):
        raise ErrorEsquema(f"{donde}: '{campo}' fuera de rango ({valor})")
    return valor


def _sin_repetidos(valores, donde, campo):
    vistos = set()
    for valor in valores:
        if valor in vistos:
            raise ErrorEsquema(f"{donde}: '{campo}' repetido: {valor!r}")
        vistos.add(valor)


def validar_odoo(datos):
    donde = ARCHIVO_ODOO
    raiz = _objeto(datos, donde)

    servidor = _objeto(_campo(raiz, 'traccar_server', donde), f'{donde}: traccar_server')
    _texto(servidor, 'name', f'{donde}: traccar_server')

    bodega = _objeto(_campo(raiz, 'bodega', donde), f'{donde}: bodega')
    _texto(bodega, 'name', f'{donde}: bodega')

    _texto(raiz, 'marca', donde)
    _texto(raiz, 'modelo', donde)

    conductores = _lista(_campo(raiz, 'conductores', donde), f'{donde}: conductores')
    for i, conductor in enumerate(conductores):
        _texto(_objeto(conductor, f'{donde}: conductores[{i}]'), 'name', f'{donde}: conductores[{i}]')
    _sin_repetidos([c['name'] for c in conductores], donde, 'conductores.name')

    vehiculos = _lista(_campo(raiz, 'vehiculos', donde), f'{donde}: vehiculos')
    for i, vehiculo in enumerate(vehiculos):
        donde_v = f'{donde}: vehiculos[{i}]'
        _objeto(vehiculo, donde_v)
        _texto(vehiculo, 'license_plate', donde_v)
        _texto(vehiculo, 'conductor', donde_v)
        _texto(vehiculo, 'uniqueId', donde_v)
    _sin_repetidos([v['license_plate'] for v in vehiculos], donde, 'vehiculos.license_plate')
    _sin_repetidos([v['uniqueId'] for v in vehiculos], donde, 'vehiculos.uniqueId')


def validar_traccar(datos):
    donde = ARCHIVO_TRACCAR
    raiz = _objeto(datos, donde)

    geocercas = _lista(_campo(raiz, 'geocercas', donde), f'{donde}: geocercas')
    for i, geocerca in enumerate(geocercas):
        donde_g = f'{donde}: geocercas[{i}]'
        _objeto(geocerca, donde_g)
        _texto(geocerca, 'name', donde_g)
        area = _texto(geocerca, 'area', donde_g)
        coincidencia = _AREA_CIRCULO.match(area)
        if not coincidencia:
            raise ErrorEsquema(f"{donde_g}: 'area' debe tener la forma 'CIRCLE (lat lon, radio_m)'")
        lat, lon = float(coincidencia.group(1)), float(coincidencia.group(2))
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ErrorEsquema(f"{donde_g}: 'area' con coordenadas fuera de rango")
    _sin_repetidos([g['name'] for g in geocercas], donde, 'geocercas.name')

    dispositivos = _lista(_campo(raiz, 'dispositivos', donde), f'{donde}: dispositivos')
    for i, dispositivo in enumerate(dispositivos):
        donde_d = f'{donde}: dispositivos[{i}]'
        _objeto(dispositivo, donde_d)
        _texto(dispositivo, 'uniqueId', donde_d)
        _texto(dispositivo, 'name', donde_d)
        atributos = _objeto(_campo(dispositivo, 'attributes', donde_d), f'{donde_d}: attributes')
        _numero(atributos, 'speedLimit', f'{donde_d}: attributes', minimo=0, exclusivo_minimo=True)
        geocercas_dispositivo = _campo(dispositivo, 'geocercas', donde_d)
        if not isinstance(geocercas_dispositivo, list) or not all(
                isinstance(nombre, str) for nombre in geocercas_dispositivo):
            raise ErrorEsquema(f"{donde_d}: 'geocercas' debe ser una lista de nombres")
    _sin_repetidos([d['uniqueId'] for d in dispositivos], donde, 'dispositivos.uniqueId')

    usuarios = _lista(_campo(raiz, 'usuarios', donde), f'{donde}: usuarios')
    if len(usuarios) != 1:
        raise ErrorEsquema(f"{donde}: 'usuarios' debe tener exactamente un usuario de integracion")
    donde_u = f'{donde}: usuarios[0]'
    usuario = _objeto(usuarios[0], donde_u)
    _texto(usuario, 'name', donde_u)
    if _campo(usuario, 'readonly', donde_u) is not True:
        raise ErrorEsquema(f"{donde_u}: 'readonly' debe ser true (usuario de solo lectura, F1-D7)")
    if _campo(usuario, 'administrator', donde_u) is not False:
        raise ErrorEsquema(f"{donde_u}: 'administrator' debe ser false (F1-D7)")


def validar_simulacion(datos):
    donde = ARCHIVO_SIMULACION
    raiz = _objeto(datos, donde)
    pedidos = _lista(_campo(raiz, 'pedidos', donde), f'{donde}: pedidos')
    for i, pedido in enumerate(pedidos):
        donde_p = f'{donde}: pedidos[{i}]'
        _objeto(pedido, donde_p)
        _texto(pedido, 'ref', donde_p)
        _texto(pedido, 'cliente', donde_p)
        _numero(pedido, 'latitud', donde_p, minimo=-90, maximo=90)
        _numero(pedido, 'longitud', donde_p, minimo=-180, maximo=180)
    _sin_repetidos([p['ref'] for p in pedidos], donde, 'pedidos.ref')

    rutas = _lista(_campo(raiz, 'rutas', donde), f'{donde}: rutas')
    for i, ruta in enumerate(rutas):
        donde_r = f'{donde}: rutas[{i}]'
        _objeto(ruta, donde_r)
        _texto(ruta, 'uniqueId', donde_r)
        puntos = _lista(_campo(ruta, 'puntos', donde_r), f'{donde_r}: puntos')
        for j, punto in enumerate(puntos):
            donde_pt = f'{donde_r}: puntos[{j}]'
            _objeto(punto, donde_pt)
            _numero(punto, 'lat', donde_pt, minimo=-90, maximo=90)
            _numero(punto, 'lon', donde_pt, minimo=-180, maximo=180)
            _numero(punto, 'speed', donde_pt, minimo=0)
            marca = _campo(punto, 'timestamp', donde_pt)
            if isinstance(marca, bool) or not isinstance(marca, int) or marca < 0:
                raise ErrorEsquema(f"{donde_pt}: 'timestamp' debe ser un entero de segundos unix, mayor o igual que 0")
    _sin_repetidos([r['uniqueId'] for r in rutas], donde, 'rutas.uniqueId')


def validar_referencias(odoo, traccar):
    """Comprueba que cada conductor y cada uniqueId de vehiculo, y cada geocerca de dispositivo, existan."""
    conductores = {c['name'] for c in odoo['conductores']}
    uniqueids = {d['uniqueId'] for d in traccar['dispositivos']}
    geocercas = {g['name'] for g in traccar['geocercas']}
    for i, vehiculo in enumerate(odoo['vehiculos']):
        donde = f'{ARCHIVO_ODOO}: vehiculos[{i}]'
        if vehiculo['conductor'] not in conductores:
            raise ErrorEsquema(f"{donde}: el conductor '{vehiculo['conductor']}' no esta en 'conductores'")
        if vehiculo['uniqueId'] not in uniqueids:
            raise ErrorEsquema(
                f"{donde}: el uniqueId '{vehiculo['uniqueId']}' no existe en {ARCHIVO_TRACCAR} (dispositivos)")
    for i, dispositivo in enumerate(traccar['dispositivos']):
        for nombre in dispositivo['geocercas']:
            if nombre not in geocercas:
                raise ErrorEsquema(
                    f"{ARCHIVO_TRACCAR}: dispositivos[{i}]: la geocerca '{nombre}' no existe en 'geocercas'")


def validar_rutas(simulacion, traccar):
    """Cada ruta del simulador apunta a un uniqueId que existe en traccar.json."""
    ids = {d['uniqueId'] for d in traccar['dispositivos']}
    for i, ruta in enumerate(simulacion['rutas']):
        uid = ruta['uniqueId']
        if uid not in ids:
            raise ErrorEsquema(
                f"{ARCHIVO_SIMULACION}: rutas[{i}]: el uniqueId '{uid}' no existe en "
                f"{ARCHIVO_TRACCAR} (dispositivos)")


def validar_todo(odoo, traccar, simulacion):
    validar_odoo(odoo)
    validar_traccar(traccar)
    validar_simulacion(simulacion)
    validar_referencias(odoo, traccar)
    validar_rutas(simulacion, traccar)


def cargar(directorio=DIRECTORIO_DATOS):
    """Lee y valida los tres JSON. Devuelve (odoo, traccar, simulacion)."""
    datos = {}
    for archivo in (ARCHIVO_ODOO, ARCHIVO_TRACCAR, ARCHIVO_SIMULACION):
        ruta = os.path.join(directorio, archivo)
        try:
            with open(ruta, encoding='utf-8') as fichero:
                datos[archivo] = json.load(fichero)
        except json.JSONDecodeError as error:
            raise ErrorEsquema(f'{archivo}: JSON mal formado (linea {error.lineno}: {error.msg})') from None
        except OSError as error:
            raise ErrorEsquema(f'{archivo}: no se puede leer ({error.strerror})') from None
    odoo = datos[ARCHIVO_ODOO]
    traccar = datos[ARCHIVO_TRACCAR]
    simulacion = datos[ARCHIVO_SIMULACION]
    validar_todo(odoo, traccar, simulacion)
    return odoo, traccar, simulacion
