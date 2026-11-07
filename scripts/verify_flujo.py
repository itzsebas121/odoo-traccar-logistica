#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificación de extremo a extremo: los 14 criterios de §13 de docs/flujo_funcional_odoo_traccar.md.

Solo biblioteca estándar. Se ejecuta en el host, con las variables de .env cargadas (ver tests/README.md),
el stack levantado y Docker disponible en la consola:   python scripts/verify_flujo.py

Es una verificación que ACTÚA sobre la base de desarrollo, no una consulta:
  * Al empezar cancela o interrumpe las rutas activas y devuelve a «preparado» las entregas fallidas.
  * Marca como preparadas las entregas en preparación, planifica, aprueba y recorre las rutas.
  * Hace una compra web de prueba por HTTP y, si faltan entregas, crea pedidos extra con referencia VERIF-<hora>.
  * Pone el proveedor de pago por transferencia en modo de prueba y activa la confirmación automática (D5).
  * Arranca routing, ml y bi (perfil analitica) y ejecuta el ETL completo.
Salida: PASS o FAIL por criterio y «N/14 criterios cumplidos». Código de salida 0 solo si cumple los 14.
"""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from seeds import schema  # noqa: E402  (solo biblioteca estándar)

OBLIGATORIAS = ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD', 'TRACCAR_URL',
                'TRACCAR_OSMAND_URL', 'DEMO_CONDUCTOR_PASSWORD')
ESPERA_SINCRONIZACION_S = 90


class Fallo(Exception):
    """Un criterio no se cumple. El mensaje dice qué se esperaba y qué se encontró."""


def exigir(condicion, mensaje):
    if not condicion:
        raise Fallo(mensaje)


def ahora_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fecha_odoo(fecha):
    return fecha.strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------------------------
class Odoo:
    def __init__(self):
        self.base = os.environ['ODOO_DB']
        self.clave = os.environ['ODOO_PASSWORD']
        url = os.environ['ODOO_URL'].rstrip('/')
        comun = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common', allow_none=True)
        self.uid = comun.authenticate(self.base, os.environ['ODOO_USER'], self.clave, {})
        exigir(self.uid, 'No se pudo autenticar en Odoo (revise ODOO_DB, ODOO_USER y ODOO_PASSWORD).')
        self.objetos = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object', allow_none=True)

    def x(self, modelo, metodo, args, kwargs=None):
        return self.objetos.execute_kw(self.base, self.uid, self.clave, modelo, metodo, args, kwargs or {})

    def buscar(self, modelo, dominio, campos, **kw):
        return self.x(modelo, 'search_read', [dominio], dict(kw, fields=campos))

    def contar(self, modelo, dominio):
        return self.x(modelo, 'search_count', [dominio])

    def xmlid(self, modulo, nombre):
        return self.x('ir.model.data', 'check_object_reference', [modulo, nombre])[1]


def mensaje_fault(error):
    lineas = [linea for linea in str(error.faultString).splitlines() if linea.strip()]
    return lineas[-1] if lineas else 'error sin detalle'


class Navegador:
    """Cliente HTTP con cookies. ``pedir`` sigue redirecciones y devuelve (estado, url final, texto)."""

    def __init__(self, base):
        self.base = base.rstrip('/')
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def pedir(self, ruta, datos=None, timeout=30):
        url = ruta if ruta.startswith('http') else self.base + ruta
        cuerpo = urllib.parse.urlencode(datos).encode() if datos is not None else None
        try:
            with self.opener.open(urllib.request.Request(url, data=cuerpo), timeout=timeout) as r:
                return r.status, r.geturl(), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as error:
            return error.code, error.geturl(), error.read().decode('utf-8', 'replace')

    def iniciar_sesion(self, usuario, clave):
        _e, _u, html = self.pedir('/web/login')
        csrf = buscar_csrf(html)
        _e, url, html = self.pedir('/web/login', {
            'login': usuario, 'password': clave, 'csrf_token': csrf, 'redirect': ''})
        exigir('/web/login' not in url, 'No se pudo iniciar sesión con el usuario %s.' % usuario)


def buscar_csrf(html):
    for patron in (r'name="csrf_token"\s+value="([^"]+)"', r'name="csrf-token"\s+content="([^"]+)"',
                   r'name="csrf_token"[^>]*value="([^"]+)"'):
        encontrado = re.search(patron, html)
        if encontrado:
            return encontrado.group(1)
    raise Fallo('La página no trae token CSRF.')


def docker(*args, comprobar=True, mostrar=False):
    """docker compose. Con ``mostrar`` la salida va a la consola (útil en pasos largos, como construir imágenes)."""
    if mostrar:
        proceso = subprocess.run(['docker', 'compose'] + list(args), cwd=str(RAIZ))
        if comprobar and proceso.returncode != 0:
            raise Fallo('docker compose %s falló (código %s).' % (' '.join(args), proceso.returncode))
        return ''
    proceso = subprocess.run(['docker', 'compose'] + list(args), cwd=str(RAIZ), capture_output=True, text=True)
    if comprobar and proceso.returncode != 0:
        raise Fallo('docker compose %s falló: %s' % (' '.join(args), (proceso.stderr or proceso.stdout)[-500:]))
    return proceso.stdout


def http_json(url, datos=None, timeout=30):
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    peticion = urllib.request.Request(url, data=cuerpo, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, None


# ---------------------------------------------------------------------------------------------
# Contexto compartido entre criterios
# ---------------------------------------------------------------------------------------------
class Contexto:
    def __init__(self):
        self.odoo = Odoo()
        self.datos_odoo, self.datos_traccar, self.simulacion = schema.cargar()
        self.login_de = {u['conductor']: u['login'] for u in self.datos_odoo['usuarios_conductor']}
        self.clave_conductor = os.environ['DEMO_CONDUCTOR_PASSWORD']
        self.url_odoo = os.environ['ODOO_URL'].rstrip('/')
        self.url_routing = os.environ.get('ROUTING_HOST_URL', 'http://127.0.0.1:8001').rstrip('/')
        self.url_ml = os.environ.get('ML_HOST_URL', 'http://127.0.0.1:8002').rstrip('/')
        self.url_bi = os.environ.get('BI_HOST_URL', 'http://127.0.0.1:8501').rstrip('/')
        self.pedido_web = None
        self.rutas = []
        self.inicio = ahora_utc() - timedelta(minutes=2)

    # -- ayudas de datos ---------------------------------------------------------------------
    def servidor_traccar(self):
        servidores = self.odoo.x('traccar.server', 'search', [[]], {'limit': 1})
        exigir(servidores, 'No hay traccar.server en Odoo; ejecute seeds/seed.py.')
        return servidores[0]

    def sincronizar(self):
        self.odoo.x('traccar.server', 'action_sincronizar_ahora', [[self.servidor_traccar()]])

    def esperar(self, condicion, mensaje, tiempo=ESPERA_SINCRONIZACION_S):
        """Sincroniza con Traccar y repite hasta que ``condicion()`` sea verdadera."""
        limite = time.time() + tiempo
        while True:
            self.sincronizar()
            resultado = condicion()
            if resultado:
                return resultado
            if time.time() > limite:
                raise Fallo(mensaje)
            time.sleep(4)

    def crear_pedido(self, referencia, lat, lon):
        odoo = self.odoo
        variantes = odoo.buscar('product.product', [('website_published', '=', True)], ['id'], limit=1)
        exigir(variantes, 'No hay productos publicados; ejecute seeds/seed.py.')
        cliente = odoo.x('res.partner', 'create', [{'name': 'Cliente %s' % referencia}])
        orden = odoo.x('sale.order', 'create', [{
            'partner_id': cliente, 'client_order_ref': referencia,
            'delivery_latitude': lat, 'delivery_longitude': lon,
            'order_line': [(0, 0, {'product_id': variantes[0]['id'], 'product_uom_qty': 1})]}])
        odoo.x('sale.order', 'action_confirm', [[orden]])
        return orden

    def entrega_de(self, pedido_id):
        entregas = self.odoo.buscar('logistica.entrega', [('sale_order_id', '=', pedido_id)],
                                    ['name', 'state', 'latitude', 'longitude', 'tracking_token'])
        exigir(entregas, 'El pedido %s no tiene entrega logística.' % pedido_id)
        return entregas[0]

    def navegador_conductor(self, nombre):
        navegador = Navegador(self.url_odoo)
        navegador.iniciar_sesion(self.login_de[nombre], self.clave_conductor)
        return navegador


# ---------------------------------------------------------------------------------------------
# Preparación
# ---------------------------------------------------------------------------------------------
def preparar(ctx):
    odoo = ctx.odoo
    print('Preparando el entorno de verificación...')
    grupo = odoo.xmlid('fleet', 'fleet_group_manager')
    grupos = odoo.x('res.users', 'read', [[odoo.uid], ['groups_id']])[0]['groups_id']
    if grupo not in grupos:
        odoo.x('res.users', 'write', [[odoo.uid], {'groups_id': [(4, grupo)]}])
    proveedor = odoo.xmlid('payment', 'payment_provider_transfer')
    if odoo.x('payment.provider', 'read', [[proveedor], ['state']])[0]['state'] != 'test':
        odoo.x('payment.provider', 'write', [[proveedor], {'state': 'test'}])
    configuracion = odoo.x('logistica.configuracion', 'search', [[]], {'limit': 1})
    odoo.x('logistica.configuracion', 'write', [configuracion, {'checkout_auto_confirm': True}])

    print('  Arrancando routing, ml y bi (perfil analitica). La primera vez construye imágenes: puede tardar 10 minutos o más...')
    docker('--profile', 'analitica', 'up', '-d', '--build', '--wait', 'routing', 'ml', 'bi', mostrar=True)

    canceladas = odoo.buscar('logistica.ruta', [('state', 'in', ['borrador', 'planificada', 'carga_confirmada'])], ['id'])
    if canceladas:
        odoo.x('logistica.ruta', 'action_cancelar', [[r['id'] for r in canceladas], 'Limpieza previa a la verificación'])
    interrumpidas = odoo.buscar('logistica.ruta', [('state', '=', 'en_recorrido')], ['id'])
    if interrumpidas:
        odoo.x('logistica.ruta', 'action_interrumpir', [[r['id'] for r in interrumpidas], 'Limpieza previa a la verificación'])
    fallidas = odoo.buscar('logistica.entrega', [('state', 'in', ['no_entregado', 'pendiente_reprogramacion'])], ['id'])
    if fallidas:
        odoo.x('logistica.entrega', 'action_reprogramar', [[e['id'] for e in fallidas]])
    print('  Rutas canceladas: %d; rutas interrumpidas: %d; entregas reprogramadas: %d' % (
        len(canceladas), len(interrumpidas), len(fallidas)))


# ---------------------------------------------------------------------------------------------
# Criterios
# ---------------------------------------------------------------------------------------------
def criterio_1(ctx):
    """Cliente navega, compra sin cuenta y marca destino en el mapa (HTTP real hasta el pago de prueba)."""
    odoo = ctx.odoo
    web = Navegador(ctx.url_odoo)
    estado, _url, html = web.pedir('/shop')
    exigir(estado == 200, 'GET /shop respondió %s.' % estado)
    enlace = re.search(r'href="(/shop/[^"/?#]+-\d+)(?:[?#][^"]*)?"', html)
    exigir(enlace, 'La tienda no lista productos publicados.')
    estado, _url, html = web.pedir(enlace.group(1))
    exigir(estado == 200, 'La ficha del producto respondió %s.' % estado)
    producto = re.search(r'name="product_id"[^>]*value="(\d+)"', html) or re.search(
        r'value="(\d+)"[^>]*name="product_id"', html)
    exigir(producto, 'La ficha del producto no trae product_id.')
    estado, url, _html = web.pedir('/shop/cart/update', {
        'product_id': producto.group(1), 'add_qty': '1', 'csrf_token': buscar_csrf(html)})
    exigir(estado == 200 and '/shop/cart' in url, 'No se pudo agregar al carrito (estado %s, %s).' % (estado, url))

    config = odoo.buscar('logistica.configuracion', [], [
        'coverage_lat_min', 'coverage_lat_max', 'coverage_lon_min', 'coverage_lon_max'], limit=1)[0]
    if config['coverage_lat_min'] < config['coverage_lat_max'] and config['coverage_lon_min'] < config['coverage_lon_max']:
        lat = (config['coverage_lat_min'] + config['coverage_lat_max']) / 2
        lon = (config['coverage_lon_min'] + config['coverage_lon_max']) / 2
    else:
        bodega = ctx.datos_odoo['bodega_logistica']
        lat, lon = bodega['latitude'], bodega['longitude']
    pais = odoo.x('res.country', 'search', [[('code', '=', 'EC')]], {'limit': 1})
    estado, _url, html = web.pedir('/shop/address')
    exigir(estado == 200 and 'name="delivery_latitude"' in html, 'La dirección no ofrece el mapa de destino.')
    correo = 'verificacion%d@example.com' % int(time.time())
    estado, url, html = web.pedir('/shop/address', {
        'name': 'Cliente Verificación', 'email': correo, 'phone': '0991234567',
        'street': 'Av. Verificación 123', 'city': 'Ambato', 'zip': '180101',
        'country_id': str(pais[0]) if pais else '', 'submitted': '1', 'partner_id': '0', 'use_same': '1',
        'field_required': 'phone,name', 'delivery_latitude': str(lat), 'delivery_longitude': str(lon),
        'delivery_notes': 'Prueba de verificación', 'csrf_token': buscar_csrf(html)})
    exigir('/shop/payment' in url, 'El destino no fue aceptado: la compra quedó en %s.' % url)

    pedido = odoo.buscar('sale.order', [('partner_id.email', '=', correo)],
                         ['name', 'amount_total', 'currency_id', 'partner_id'], order='id desc', limit=1)
    exigir(pedido, 'El carrito no generó un pedido en Odoo.')
    pedido = pedido[0]
    proveedor = odoo.xmlid('payment', 'payment_provider_transfer')
    referencia = 'VERIF-%s-%d' % (pedido['id'], int(time.time()))
    odoo.x('payment.transaction', 'create', [{
        'provider_id': proveedor, 'reference': referencia, 'amount': pedido['amount_total'],
        'currency_id': pedido['currency_id'][0], 'partner_id': pedido['partner_id'][0],
        'operation': 'online_redirect', 'sale_order_ids': [(6, 0, [pedido['id']])]}])
    web.pedir('/payment/custom/process', {'reference': referencia})
    for _i in range(10):
        estado_pedido = odoo.x('sale.order', 'read', [[pedido['id']], ['state']])[0]['state']
        if estado_pedido == 'sale':
            break
        time.sleep(1)
    exigir(estado_pedido == 'sale', 'Tras el pago de prueba el pedido quedó «%s», no «sale».' % estado_pedido)
    ctx.pedido_web = {'id': pedido['id'], 'name': pedido['name'], 'lat': lat, 'lon': lon, 'correo': correo}


def _requiere_pedido(ctx):
    exigir(ctx.pedido_web, 'Depende del criterio 1: no hay pedido web de prueba.')


def criterio_2(ctx):
    """El pedido aparece en Odoo con productos, contacto y coordenadas."""
    _requiere_pedido(ctx)
    pedido = ctx.odoo.buscar('sale.order', [('id', '=', ctx.pedido_web['id'])], [
        'order_line', 'partner_id', 'delivery_latitude', 'delivery_longitude'])[0]
    exigir(pedido['order_line'], 'El pedido no tiene líneas de producto.')
    contacto = ctx.odoo.buscar('res.partner', [('id', '=', pedido['partner_id'][0])], ['phone', 'email'])[0]
    exigir(contacto['phone'] and contacto['email'], 'El contacto del pedido no tiene teléfono o correo.')
    exigir(abs(pedido['delivery_latitude'] - ctx.pedido_web['lat']) < 1e-4
           and abs(pedido['delivery_longitude'] - ctx.pedido_web['lon']) < 1e-4,
           'Las coordenadas del pedido no coinciden con las marcadas en el mapa.')


def criterio_3(ctx):
    """Pasa a preparación sin aprobación manual."""
    _requiere_pedido(ctx)
    entrega = ctx.entrega_de(ctx.pedido_web['id'])
    exigir(entrega['state'] == 'en_preparacion',
           'La entrega quedó en «%s» en lugar de «en_preparacion».' % entrega['state'])


def criterio_4(ctx):
    """Al menos 3 vehículos/conductores con dispositivo verificable."""
    odoo = ctx.odoo
    vehiculos = odoo.buscar('fleet.vehicle', [('traccar_device_id', '!=', False), ('driver_id', '!=', False)],
                            ['license_plate', 'traccar_device_id', 'traccar_unique_id'])
    exigir(len(vehiculos) >= 3, 'Hay %d vehículos con conductor y dispositivo; se necesitan 3.' % len(vehiculos))
    exigir(len({v['traccar_device_id'][0] for v in vehiculos}) == len(vehiculos),
           'Dos vehículos comparten el mismo dispositivo.')
    credenciales = os.environ.get('TRACCAR_ADMIN_EMAIL'), os.environ.get('TRACCAR_ADMIN_PASSWORD')
    if all(credenciales):
        import base64
        autorizacion = base64.b64encode(('%s:%s' % credenciales).encode()).decode()
        peticion = urllib.request.Request(
            os.environ['TRACCAR_URL'].rstrip('/') + '/api/devices',
            headers={'Authorization': 'Basic ' + autorizacion, 'Accept': 'application/json'})
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            en_traccar = {d['uniqueId'] for d in json.loads(respuesta.read().decode())}
        faltan = [v['license_plate'] for v in vehiculos if v['traccar_unique_id'] not in en_traccar]
        exigir(not faltan, 'Dispositivos que Traccar no conoce, de los vehículos: %s.' % ', '.join(faltan))


def _preparar_entregas(ctx, minimo=3):
    odoo = ctx.odoo
    en_preparacion = odoo.buscar('logistica.entrega', [('state', '=', 'en_preparacion')], ['id'])
    if en_preparacion:
        odoo.x('logistica.entrega', 'action_marcar_preparado', [[e['id'] for e in en_preparacion]])
    faltan = minimo - odoo.contar('logistica.entrega', [('state', '=', 'preparado')])
    pedidos = ctx.simulacion['pedidos']
    for i in range(max(faltan, 0)):
        base = pedidos[i % len(pedidos)]
        orden = ctx.crear_pedido('VERIF-%d-%d' % (int(time.time()), i), base['latitud'], base['longitud'])
        odoo.x('logistica.entrega', 'action_marcar_preparado', [[ctx.entrega_de(orden)['id']]])


def criterio_5(ctx):
    """El administrador genera y revisa una asignación desde la bodega común."""
    odoo = ctx.odoo
    _preparar_entregas(ctx)
    vehiculos = [v['id'] for v in odoo.buscar(
        'fleet.vehicle', [('traccar_device_id', '!=', False), ('driver_id', '!=', False)], ['id'])]
    asistente = odoo.x('logistica.planificador', 'create', [{'vehicle_ids': [(6, 0, vehiculos)]}])
    try:
        accion = odoo.x('logistica.planificador', 'action_proponer', [[asistente]])
    except xmlrpc.client.Fault as error:
        raise Fallo('El planificador falló: %s' % mensaje_fault(error))
    ids = accion['domain'][0][2]
    exigir(ids, 'El planificador no propuso ninguna ruta.')
    bodega = odoo.buscar('logistica.bodega', [('active', '=', True)], ['id'])
    exigir(len(bodega) == 1, 'Debe haber exactamente una bodega activa.')
    rutas = odoo.buscar('logistica.ruta', [('id', 'in', ids)], ['name', 'state', 'bodega_id', 'stop_ids', 'driver_id'])
    for ruta in rutas:
        exigir(ruta['state'] == 'borrador', 'La ruta %s no quedó en borrador.' % ruta['name'])
        exigir(ruta['bodega_id'][0] == bodega[0]['id'], 'La ruta %s no sale de la bodega común.' % ruta['name'])
        exigir(ruta['stop_ids'], 'La ruta %s no tiene paradas.' % ruta['name'])
    odoo.x('logistica.ruta', 'action_aprobar_plan', [ids])
    aprobadas = odoo.buscar('logistica.ruta', [('id', 'in', ids)], ['state'])
    exigir(all(r['state'] == 'planificada' for r in aprobadas), 'No todas las rutas quedaron planificadas.')
    ctx.rutas = odoo.buscar('logistica.ruta', [('id', 'in', ids)], ['name', 'driver_id', 'vehicle_id', 'stop_ids'])


def _requiere_rutas(ctx):
    exigir(ctx.rutas, 'Depende del criterio 5: no hay rutas planificadas.')


def criterio_6(ctx):
    """El conductor ve solo sus rutas, confirma carga e inicia (HTTP)."""
    _requiere_rutas(ctx)
    conductores = list(ctx.login_de)
    for ruta in ctx.rutas:
        propio = ruta['driver_id'][1]
        exigir(propio in ctx.login_de, 'El conductor %s no tiene usuario en los datos de demostración.' % propio)
        navegador = ctx.navegador_conductor(propio)
        _e, _u, lista = navegador.pedir('/logistica/conductor')
        exigir(ruta['name'] in lista, 'El conductor %s no ve su ruta %s.' % (propio, ruta['name']))
        otros = [c for c in conductores if c != propio]
        if otros:
            ajeno = ctx.navegador_conductor(otros[0])
            _e, _u, lista_ajena = ajeno.pedir('/logistica/conductor')
            exigir(ruta['name'] not in lista_ajena, 'El conductor %s ve la ruta de otro.' % otros[0])
            estado, _u, _t = ajeno.pedir('/logistica/conductor/ruta/%d' % ruta['id'])
            exigir(estado in (403, 404), 'Una ruta ajena respondió %s en lugar de 403 o 404.' % estado)
        estado, _u, pagina = navegador.pedir('/logistica/conductor/ruta/%d' % ruta['id'])
        exigir(estado == 200, 'El conductor no puede abrir su ruta (estado %s).' % estado)
        base = '/logistica/conductor/ruta/%d' % ruta['id']
        for accion, esperado in (('confirmar-carga', 'carga_confirmada'), ('iniciar', 'en_recorrido')):
            navegador.pedir('%s/%s' % (base, accion), {'csrf_token': buscar_csrf(pagina)})
            estado_ruta = ctx.odoo.buscar('logistica.ruta', [('id', '=', ruta['id'])], ['state'])[0]['state']
            exigir(estado_ruta == esperado, 'Tras «%s» la ruta %s quedó «%s», no «%s».' % (
                accion, ruta['name'], estado_ruta, esperado))
            _e, _u, pagina = navegador.pedir(base)


def _paradas_pendientes(ctx):
    ids = [r['id'] for r in ctx.rutas]
    return ctx.odoo.buscar('logistica.ruta.parada', [('route_id', 'in', ids), ('state', '=', 'pendiente')],
                           ['route_id', 'sequence', 'entrega_id', 'latitude', 'longitude',
                            'arrival_candidate_at'], order='route_id, sequence')


def criterio_7(ctx):
    """Posiciones de Traccar asociadas al vehículo correcto con marca de tiempo."""
    _requiere_rutas(ctx)
    ctx.inicio = ahora_utc() - timedelta(minutes=2)
    simulador = subprocess.run([sys.executable, 'seeds/simular.py'], cwd=str(RAIZ), capture_output=True, text=True)
    exigir(simulador.returncode == 0, 'El simulador falló: %s' % simulador.stderr[-300:])
    esperado = {v['license_plate']: v['uniqueId'] for v in ctx.datos_odoo['vehiculos']}

    def recibidas():
        faltan = []
        for placa, unique_id in esperado.items():
            posiciones = ctx.odoo.buscar('logistica.traccar.posicion', [
                ('vehicle_id.license_plate', '=', placa), ('fix_time', '>=', fecha_odoo(ctx.inicio))],
                ['fix_time', 'device_id'], limit=5)
            if not posiciones:
                faltan.append(placa)
                continue
            dispositivo = ctx.odoo.buscar('traccar.device', [('id', '=', posiciones[0]['device_id'][0])], ['unique_id'])[0]
            exigir(dispositivo['unique_id'] == unique_id,
                   'Las posiciones del vehículo %s llegaron del dispositivo %s, no de %s.' % (
                       placa, dispositivo['unique_id'], unique_id))
            exigir(posiciones[0]['fix_time'], 'La posición del vehículo %s no tiene marca de tiempo.' % placa)
        return not faltan

    ctx.esperar(recibidas, 'Odoo no recibió posiciones recientes de los tres vehículos tras %d s.' % ESPERA_SINCRONIZACION_S)


def criterio_8(ctx):
    """La llegada por GPS no marca entregado."""
    _requiere_rutas(ctx)
    pendientes = _paradas_pendientes(ctx)
    exigir(pendientes, 'No hay paradas pendientes para probar la llegada.')
    parada = pendientes[0]
    ruta = next(r for r in ctx.rutas if r['id'] == parada['route_id'][0])
    vehiculo = ctx.odoo.buscar('fleet.vehicle', [('id', '=', ruta['vehicle_id'][0])], ['traccar_unique_id'])[0]
    time.sleep(1)
    destino = '%s/?%s' % (os.environ['TRACCAR_OSMAND_URL'].rstrip('/'), urllib.parse.urlencode({
        'id': vehiculo['traccar_unique_id'], 'lat': parada['latitude'], 'lon': parada['longitude'],
        'speed': 0, 'timestamp': int(time.time())}))
    with urllib.request.urlopen(destino, timeout=15) as respuesta:
        exigir(respuesta.status == 200, 'OsmAnd respondió %s.' % respuesta.status)

    def con_llegada():
        actual = ctx.odoo.buscar('logistica.ruta.parada', [('id', '=', parada['id'])], ['arrival_candidate_at'])[0]
        return bool(actual['arrival_candidate_at'])

    ctx.esperar(con_llegada, 'No se registró la posible llegada de la parada tras %d s.' % ESPERA_SINCRONIZACION_S)
    entrega = ctx.odoo.buscar('logistica.entrega', [('id', '=', parada['entrega_id'][0])], ['state'])[0]
    exigir(entrega['state'] == 'en_recorrido',
           'La llegada por GPS dejó la entrega en «%s»; debía seguir «en_recorrido».' % entrega['state'])
    eventos = ctx.odoo.contar('logistica.entrega.evento', [
        ('entrega_id', '=', parada['entrega_id'][0]), ('event_type', '=', 'posible_llegada')])
    exigir(eventos >= 1, 'No quedó el evento «posible_llegada».')


def criterio_9(ctx):
    """El conductor marca Entregado y No entregado con motivo, y queda auditado."""
    _requiere_rutas(ctx)
    odoo = ctx.odoo
    pendientes = _paradas_pendientes(ctx)
    exigir(len(pendientes) >= 2, 'Se necesitan al menos 2 paradas pendientes (hay %d).' % len(pendientes))
    rutas = {r['id']: r for r in ctx.rutas}

    def registrar(parada, accion, datos=None):
        ruta = rutas[parada['route_id'][0]]
        navegador = ctx.navegador_conductor(ruta['driver_id'][1])
        _e, _u, pagina = navegador.pedir('/logistica/conductor/ruta/%d' % ruta['id'])
        envio = dict(datos or {}, csrf_token=buscar_csrf(pagina))
        estado, _u, _t = navegador.pedir('/logistica/conductor/parada/%d/%s' % (parada['id'], accion), envio)
        exigir(estado == 200, 'La acción «%s» respondió %s.' % (accion, estado))
        return ctx.login_de[ruta['driver_id'][1]]

    entregada, fallida = pendientes[0], pendientes[1]
    login = registrar(entregada, 'entregado')
    evento = odoo.buscar('logistica.entrega.evento', [
        ('entrega_id', '=', entregada['entrega_id'][0]), ('event_type', '=', 'entregado')],
        ['user_id', 'event_time'])
    exigir(len(evento) == 1, 'La entrega debe tener exactamente un evento «entregado» (hay %d).' % len(evento))
    usuario = odoo.buscar('res.users', [('login', '=', login)], ['id'])[0]['id']
    exigir(evento[0]['user_id'][0] == usuario, 'El evento «entregado» no queda a nombre del conductor.')
    estado = odoo.buscar('logistica.entrega', [('id', '=', entregada['entrega_id'][0])], ['state'])[0]['state']
    exigir(estado == 'entregado', 'La entrega quedó «%s», no «entregado».' % estado)

    registrar(fallida, 'no-entregado', {'motivo': 'absent', 'notas': 'Verificación: cliente ausente'})
    evento = odoo.buscar('logistica.entrega.evento', [
        ('entrega_id', '=', fallida['entrega_id'][0]), ('event_type', '=', 'no_entregado')], ['failure_reason'])
    exigir(len(evento) == 1 and evento[0]['failure_reason'] == 'absent',
           'El evento «no_entregado» debe traer el motivo «absent».')
    estado = odoo.buscar('logistica.entrega', [('id', '=', fallida['entrega_id'][0])], ['state'])[0]['state']
    exigir(estado == 'no_entregado', 'La entrega fallida quedó «%s», no «no_entregado».' % estado)


def criterio_10(ctx):
    """Una ruta iniciada no recibe pedidos nuevos."""
    _requiere_rutas(ctx)
    odoo = ctx.odoo
    en_recorrido = odoo.buscar('logistica.ruta', [('id', 'in', [r['id'] for r in ctx.rutas]),
                                                  ('state', '=', 'en_recorrido')], ['stop_ids'])
    exigir(en_recorrido, 'No hay una ruta en recorrido para probar.')
    ruta = en_recorrido[0]
    base = ctx.simulacion['pedidos'][0]
    orden = ctx.crear_pedido('VERIF-NUEVO-%d' % int(time.time()), base['latitud'], base['longitud'])
    entrega = ctx.entrega_de(orden)
    odoo.x('logistica.entrega', 'action_marcar_preparado', [[entrega['id']]])
    try:
        odoo.x('logistica.ruta', 'write', [[ruta['id']], {'stop_ids': [(0, 0, {'entrega_id': entrega['id']})]}])
    except xmlrpc.client.Fault:
        pass
    else:
        raise Fallo('Odoo aceptó agregar un pedido a una ruta ya iniciada.')
    despues = odoo.buscar('logistica.ruta', [('id', '=', ruta['id'])], ['stop_ids'])[0]['stop_ids']
    exigir(sorted(despues) == sorted(ruta['stop_ids']), 'Las paradas de la ruta iniciada cambiaron.')
    actual = odoo.buscar('logistica.entrega', [('id', '=', entrega['id'])], ['state'])[0]['state']
    exigir(actual == 'preparado', 'El pedido nuevo debía quedar «preparado» para la siguiente ruta (está «%s»).' % actual)


def criterio_11(ctx):
    """El cliente consulta su pedido con un enlace protegido."""
    _requiere_pedido(ctx)
    entrega = ctx.entrega_de(ctx.pedido_web['id'])
    token = entrega['tracking_token']
    exigir(token, 'La entrega no tiene token de seguimiento.')
    anonimo = Navegador(ctx.url_odoo)
    estado, _u, html = anonimo.pedir('/logistica/seguimiento/%s' % token)
    exigir(estado == 200 and ctx.pedido_web['name'] in html, 'El enlace de seguimiento no muestra el pedido (estado %s).' % estado)
    exigir(str(ctx.pedido_web['lat']) not in html, 'La página pública expone las coordenadas del destino.')
    estado, _u, _t = anonimo.pedir('/logistica/seguimiento/%sx' % token)
    exigir(estado == 404, 'Un token inválido respondió %s en lugar de 404.' % estado)


def criterio_12(ctx):
    """El ETL extrae ambas APIs, valida y carga el modelo dimensional."""
    docker('--profile', 'etl', 'run', '--rm', 'etl', 'bootstrap', mostrar=True)
    docker('--profile', 'etl', 'run', '--rm', 'etl', 'run', '--mode', 'full', mostrar=True)
    for tabla, minimo in (('dim_vehiculo', 3), ('fact_entregas', 1), ('fact_posicion_gps', 1)):
        salida = docker('exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', 'logistica_dwh', '-tAc',
                        'SELECT count(*) FROM %s' % tabla)
        filas = int(salida.strip() or 0)
        exigir(filas >= minimo, 'La tabla %s del DWH tiene %d filas; se esperaban al menos %d.' % (tabla, filas, minimo))


def criterio_13(ctx):
    """El BI usa el DWH y no depende de Odoo."""
    with urllib.request.urlopen(ctx.url_bi + '/_stcore/health', timeout=20) as respuesta:
        exigir(respuesta.status == 200 and respuesta.read().decode().strip() == 'ok', 'El BI no responde «ok».')
    prohibidos = re.compile(r'^\s*(import|from)\s+(odoo|xmlrpc)\b', re.M)
    for archivo in (RAIZ / 'services' / 'bi').rglob('*.py'):
        if 'tests' in archivo.parts:
            continue
        exigir(not prohibidos.search(archivo.read_text(encoding='utf-8')),
               '%s importa Odoo o xmlrpc.' % archivo.relative_to(RAIZ))
    requisitos = (RAIZ / 'services' / 'bi' / 'requirements.txt').read_text(encoding='utf-8').lower()
    exigir('odoo' not in requisitos, 'requirements.txt del BI menciona Odoo.')


def criterio_14(ctx):
    """El modelo predice destinos, trae métricas y presenta ruta vial."""
    odoo = ctx.odoo

    def cargado():
        estado, datos = http_json(ctx.url_ml + '/health')
        return estado == 200 and datos and datos.get('model_loaded')

    if not cargado():
        docker('--profile', 'analitica', 'run', '--rm', 'ml', 'python', '-m', 'mlsvc.train', '--source', 'simulate',
               mostrar=True)
        for _i in range(15):
            if cargado():
                break
            time.sleep(2)
    exigir(cargado(), 'El servicio ML no tiene un modelo cargado.')

    placa = ctx.datos_odoo['vehiculos'][0]['license_plate']
    estado, prediccion = http_json(ctx.url_ml + '/predict', {
        'vehicle_code': placa, 'reference_datetime': ahora_utc().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'origin_zone': 'centro'})
    exigir(estado == 200 and prediccion.get('predicted_zone'), '/predict respondió %s.' % estado)
    exigir(len(prediccion.get('alternatives', [])) >= 1, '/predict no trae alternativas.')
    exigir(abs(sum(prediccion['probabilities'].values()) - 1.0) < 1e-6, 'Las probabilidades no suman 1.')

    estado, metricas = http_json(ctx.url_ml + '/metrics')
    exigir(estado == 200 and all(k in metricas for k in ('accuracy', 'f1_macro', 'confusion_matrix', 'baseline_accuracy')),
           '/metrics no trae accuracy, F1, matriz de confusión y predictor base.')

    zonas = {z['code']: (z['latitude'], z['longitude']) for z in odoo.buscar('logistica.zona', [], ['code', 'latitude', 'longitude'])}
    origen, destino = zonas['centro'], zonas.get(prediccion['predicted_zone'], zonas['centro'])
    consulta = urllib.parse.urlencode({'origin_lat': origen[0], 'origin_lon': origen[1],
                                       'dest_lat': destino[0], 'dest_lon': destino[1]})
    estado, ruta = http_json(ctx.url_routing + '/route?' + consulta)
    exigir(estado == 200 and ruta.get('source') and ruta.get('distance_km') is not None,
           '/route respondió %s o no indica su fuente.' % estado)

    vehiculo = odoo.buscar('fleet.vehicle', [('license_plate', '=', placa)], ['id'])[0]['id']
    antes = odoo.contar('logistica.entrega', [('state', '=', 'entregado')])
    asistente = odoo.x('logistica.prediccion.wizard', 'create', [{
        'vehicle_id': vehiculo, 'fecha': ahora_utc().strftime('%Y-%m-%d'), 'hora': 8.0, 'origin_zone': 'centro'}])
    try:
        accion = odoo.x('logistica.prediccion.wizard', 'action_predecir', [[asistente]])
    except xmlrpc.client.Fault as error:
        raise Fallo('El asistente «Predecir destino» falló: %s' % mensaje_fault(error))
    consulta = odoo.buscar('logistica.prediccion.consulta', [('id', '=', accion['res_id'])],
                           ['predicted_zone', 'route_source', 'model_version'])[0]
    exigir(consulta['predicted_zone'] and consulta['model_version'], 'La consulta de Odoo quedó sin destino o versión.')
    exigir(odoo.contar('logistica.entrega', [('state', '=', 'entregado')]) == antes, 'La predicción cambió entregas.')


CRITERIOS = [
    (1, 'Cliente navega, compra sin cuenta y marca destino', criterio_1),
    (2, 'El pedido aparece en Odoo con productos, contacto y coordenadas', criterio_2),
    (3, 'Pasa a preparación sin aprobación manual', criterio_3),
    (4, 'Al menos 3 vehículos/conductores con dispositivo verificable', criterio_4),
    (5, 'El administrador genera y revisa una asignación desde la bodega común', criterio_5),
    (6, 'El conductor ve solo sus rutas, confirma carga e inicia', criterio_6),
    (7, 'Posiciones de Traccar asociadas al vehículo correcto con marca de tiempo', criterio_7),
    (8, 'La llegada GPS no marca entregado', criterio_8),
    (9, 'El conductor marca Entregado o No entregado con motivo y auditoría', criterio_9),
    (10, 'Una ruta iniciada no recibe pedidos nuevos', criterio_10),
    (11, 'El cliente consulta su pedido con enlace protegido', criterio_11),
    (12, 'El ETL extrae ambas APIs, valida y carga el modelo dimensional', criterio_12),
    (13, 'El BI usa el DWH', criterio_13),
    (14, 'El modelo de IA predice destinos, incluye métricas y presenta ruta vial', criterio_14),
]


def main():
    faltan = [v for v in OBLIGATORIAS if not os.environ.get(v)]
    if faltan:
        print('verify_flujo: faltan variables de entorno (revise .env): %s' % ', '.join(faltan), file=sys.stderr)
        return 2
    try:
        ctx = Contexto()
        preparar(ctx)
    except Fallo as error:
        print('verify_flujo: no se pudo preparar el entorno: %s' % error, file=sys.stderr)
        return 2
    except (OSError, xmlrpc.client.Error) as error:
        print('verify_flujo: no se pudo conectar con Odoo: %s' % error, file=sys.stderr)
        return 2

    cumplidos = 0
    for numero, descripcion, comprobar in CRITERIOS:
        try:
            comprobar(ctx)
        except Fallo as error:
            print('[FAIL] %2d. %s\n         -> %s' % (numero, descripcion, error))
        except xmlrpc.client.Fault as error:
            print('[FAIL] %2d. %s\n         -> Odoo rechazó la operación: %s' % (numero, descripcion, mensaje_fault(error)))
        except Exception as error:  # un criterio roto no debe tapar a los demás
            print('[FAIL] %2d. %s\n         -> error inesperado: %s: %s' % (
                numero, descripcion, type(error).__name__, error))
        else:
            cumplidos += 1
            print('[PASS] %2d. %s' % (numero, descripcion))
    print('\n%d/14 criterios cumplidos' % cumplidos)
    return 0 if cumplidos == 14 else 1


if __name__ == '__main__':
    sys.exit(main())
