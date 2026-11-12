# -*- coding: utf-8 -*-
"""Sembrado idempotente de Odoo y Traccar (Fase 1).

Se ejecuta en el host con Python 3 y solo biblioteca estandar. Los datos de negocio salen de seeds/data/*.json
(validados por schema.py). Las direcciones y credenciales salen de variables de entorno y nunca se imprimen.
Imprime {"creados": [...], "actualizados": [...], "omitidos": [...]}: una segunda ejecucion no crea nada.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
import xmlrpc.client

import schema

VARIABLES_ENTORNO = ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD',
                     'TRACCAR_URL', 'TRACCAR_INTERNAL_URL', 'TRACCAR_ADMIN_EMAIL', 'TRACCAR_ADMIN_PASSWORD',
                     'INTEGRATION_TRACCAR_EMAIL', 'INTEGRATION_TRACCAR_PASSWORD',
                     'DEMO_CONDUCTOR_PASSWORD')
# Tipo de autenticacion del traccar.server de Odoo (valor tecnico, no de negocio).
AUTH_TRACCAR_ODOO = 'basic'


class ErrorSembrado(RuntimeError):
    """Fallo del sembrado con un mensaje listo para mostrar (sin credenciales)."""


class ErrorHttp(ErrorSembrado):
    """Traccar respondio con un codigo HTTP de error. El codigo permite distinguir, por ejemplo, un 401."""

    def __init__(self, mensaje, codigo):
        super().__init__(mensaje)
        self.codigo = codigo


class Informe:
    def __init__(self):
        self.creados = []
        self.actualizados = []
        self.omitidos = []


def _leer_entorno():
    faltan = [nombre for nombre in VARIABLES_ENTORNO if not os.environ.get(nombre)]
    if faltan:
        raise ErrorSembrado('faltan variables de entorno (revise .env): ' + ', '.join(faltan))
    return {nombre: os.environ[nombre] for nombre in VARIABLES_ENTORNO}


def _sin_claves_documentales(registro):
    """Quita las claves que empiezan por _ (documentacion) antes de enviar un registro."""
    return {clave: valor for clave, valor in registro.items() if not clave.startswith('_')}


class ClienteTraccar:
    """API REST de Traccar con autenticacion basica (administrador, o usuario de integracion para la prueba de clave)."""

    def __init__(self, url, correo, clave):
        self._base = url.rstrip('/')
        self._cabeceras = {'Accept': 'application/json'}
        if correo is not None:
            credenciales = base64.b64encode(f'{correo}:{clave}'.encode('utf-8')).decode('ascii')
            self._cabeceras['Authorization'] = 'Basic ' + credenciales

    def llamar(self, metodo, ruta, cuerpo=None):
        cabeceras = dict(self._cabeceras)
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode('utf-8')
            cabeceras['Content-Type'] = 'application/json'
        peticion = urllib.request.Request(self._base + ruta, data=datos, method=metodo, headers=cabeceras)
        try:
            with urllib.request.urlopen(peticion, timeout=15) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            raise ErrorHttp(f'Traccar {metodo} {ruta} respondio HTTP {error.code}', error.code) from None
        except urllib.error.URLError as error:
            raise ErrorSembrado(f'no hay respuesta de Traccar en {self._base} ({error.reason})') from None
        if not contenido:
            return None
        try:
            return json.loads(contenido)
        except ValueError:
            raise ErrorSembrado(f'Traccar {metodo} {ruta} devolvio una respuesta que no es JSON') from None


class ClienteOdoo:
    """XML-RPC de Odoo; autentica al crear el cliente."""

    def __init__(self, url, base, usuario, clave):
        self._base = base
        self._clave = clave
        comun = xmlrpc.client.ServerProxy(url.rstrip('/') + '/xmlrpc/2/common', allow_none=True)
        self._uid = comun.authenticate(base, usuario, clave, {})
        if not self._uid:
            raise ErrorSembrado('autenticacion de Odoo fallida (revise ODOO_DB, ODOO_USER y ODOO_PASSWORD)')
        self._objetos = xmlrpc.client.ServerProxy(url.rstrip('/') + '/xmlrpc/2/object', allow_none=True)

    def ejecutar(self, modelo, metodo, args, kwargs=None):
        return self._objetos.execute_kw(self._base, self._uid, self._clave, modelo, metodo, args, kwargs or {})


def _normalizar(valor):
    """Un many2one llega por XML-RPC como [id, nombre] o False; se compara solo el id."""
    if isinstance(valor, (list, tuple)):
        return valor[0] if valor else False
    return valor


def _asegurar(odoo, informe, modelo, dominio, valores, etiqueta, crear=True):
    """Clave natural = dominio. Crea si falta, escribe solo lo que difiere y reporta cada caso."""
    ids = odoo.ejecutar(modelo, 'search', [dominio], {'limit': 1, 'context': {'active_test': False}})
    if not ids:
        if not crear:
            raise ErrorSembrado(f'no existe {etiqueta} y no puede crearse aqui')
        registro = odoo.ejecutar(modelo, 'create', [valores])
        informe.creados.append(etiqueta)
        return registro
    registro = ids[0]
    actual = odoo.ejecutar(modelo, 'read', [[registro], list(valores)])[0]
    cambios = {campo: valor for campo, valor in valores.items() if _normalizar(actual[campo]) != valor}
    if cambios:
        odoo.ejecutar(modelo, 'write', [[registro], cambios])
        informe.actualizados.append(etiqueta)
    else:
        informe.omitidos.append(etiqueta)
    return registro


def _sembrar_traccar(traccar, datos, informe):
    existentes = {d['uniqueId']: d for d in traccar.llamar('GET', '/api/devices')}
    ids_dispositivo = {}
    for entrada in datos['dispositivos']:
        uid = entrada['uniqueId']
        etiqueta = f'traccar.device {uid}'
        actual = existentes.get(uid)
        if actual is None:
            creado = traccar.llamar('POST', '/api/devices',
                                    {'name': entrada['name'], 'uniqueId': uid, 'attributes': entrada['attributes']})
            ids_dispositivo[uid] = creado['id']
            informe.creados.append(etiqueta)
            continue
        ids_dispositivo[uid] = actual['id']
        atributos_actuales = actual.get('attributes') or {}
        al_dia = actual.get('name') == entrada['name'] and all(
            atributos_actuales.get(clave) == valor for clave, valor in entrada['attributes'].items())
        if al_dia:
            informe.omitidos.append(etiqueta)
        else:
            cuerpo = {**actual, 'name': entrada['name'],
                      'attributes': {**atributos_actuales, **entrada['attributes']}}
            traccar.llamar('PUT', f"/api/devices/{actual['id']}", cuerpo)
            informe.actualizados.append(etiqueta)

    existentes_geo = {g['name']: g for g in traccar.llamar('GET', '/api/geofences')}
    ids_geocerca = {}
    for entrada in datos['geocercas']:
        nombre = entrada['name']
        etiqueta = f'traccar.geofence {nombre}'
        actual = existentes_geo.get(nombre)
        if actual is None:
            creada = traccar.llamar('POST', '/api/geofences', {'name': nombre, 'area': entrada['area']})
            ids_geocerca[nombre] = creada['id']
            informe.creados.append(etiqueta)
        elif actual.get('area') == entrada['area']:
            ids_geocerca[nombre] = actual['id']
            informe.omitidos.append(etiqueta)
        else:
            traccar.llamar('PUT', f"/api/geofences/{actual['id']}", {**actual, 'area': entrada['area']})
            ids_geocerca[nombre] = actual['id']
            informe.actualizados.append(etiqueta)

    for entrada in datos['dispositivos']:
        uid = entrada['uniqueId']
        id_dispositivo = ids_dispositivo[uid]
        vinculadas = {g['id'] for g in traccar.llamar('GET', f'/api/geofences?deviceId={id_dispositivo}')}
        for nombre in entrada['geocercas']:
            etiqueta = f'traccar.permission {uid} / {nombre}'
            id_geo = ids_geocerca[nombre]
            if id_geo in vinculadas:
                informe.omitidos.append(etiqueta)
            else:
                traccar.llamar('POST', '/api/permissions', {'deviceId': id_dispositivo, 'geofenceId': id_geo})
                informe.creados.append(etiqueta)
    return ids_dispositivo


def _clave_aceptada(url, correo, clave):
    """True si Traccar acepta la contrasena del usuario de integracion (la prueba con una lectura)."""
    try:
        ClienteTraccar(url, correo, clave).llamar('GET', '/api/devices')
    except ErrorHttp as error:
        if error.codigo == 401:
            return False
        raise
    return True


def _sembrar_usuario_integracion(traccar, entorno, datos, ids_dispositivo, informe):
    """Usuario de integracion (F1-D7): clave natural = email. Solo lectura, sin administrador.

    Recibe permiso sobre cada dispositivo y cada geocerca para que el cron de Odoo pueda leer sus posiciones y eventos.
    """
    entrada = datos['usuarios'][0]
    correo = entorno['INTEGRATION_TRACCAR_EMAIL']
    clave = entorno['INTEGRATION_TRACCAR_PASSWORD']
    etiqueta = f'traccar.user {correo}'
    perfil = {'name': entrada['name'], 'readonly': entrada['readonly'], 'administrator': entrada['administrator']}

    actual = {u['email']: u for u in traccar.llamar('GET', '/api/users')}.get(correo)
    if actual is None:
        creado = traccar.llamar('POST', '/api/users', {**perfil, 'email': correo, 'password': clave})
        id_usuario = creado['id']
        informe.creados.append(etiqueta)
    else:
        id_usuario = actual['id']
        perfil_al_dia = all(actual.get(campo) == valor for campo, valor in perfil.items())
        clave_al_dia = _clave_aceptada(entorno['TRACCAR_URL'], correo, clave)
        if perfil_al_dia and clave_al_dia:
            informe.omitidos.append(etiqueta)
        else:
            cuerpo = {**actual, **perfil}
            if not clave_al_dia:
                cuerpo['password'] = clave
            traccar.llamar('PUT', f'/api/users/{id_usuario}', cuerpo)
            informe.actualizados.append(etiqueta)

    vinculados = {d['id'] for d in traccar.llamar('GET', f'/api/devices?userId={id_usuario}')}
    for dispositivo in datos['dispositivos']:
        uid = dispositivo['uniqueId']
        id_dispositivo = ids_dispositivo[uid]
        etiqueta_permiso = f'traccar.permission {correo} / {uid}'
        if id_dispositivo in vinculados:
            informe.omitidos.append(etiqueta_permiso)
        else:
            traccar.llamar('POST', '/api/permissions', {'userId': id_usuario, 'deviceId': id_dispositivo})
            informe.creados.append(etiqueta_permiso)

    # Traccar oculta los eventos geofenceEnter/geofenceExit a quien no tiene permiso sobre la geocerca.
    geocercas = {g['name']: g['id'] for g in traccar.llamar('GET', '/api/geofences')}
    geocercas_vinculadas = {g['id'] for g in traccar.llamar('GET', f'/api/geofences?userId={id_usuario}')}
    for geocerca in datos['geocercas']:
        nombre = geocerca['name']
        etiqueta_permiso = f'traccar.permission {correo} / {nombre}'
        if geocercas[nombre] in geocercas_vinculadas:
            informe.omitidos.append(etiqueta_permiso)
        else:
            traccar.llamar('POST', '/api/permissions', {'userId': id_usuario, 'geofenceId': geocercas[nombre]})
            informe.creados.append(etiqueta_permiso)


def _sembrar_odoo(odoo, entorno, datos, informe, simulacion):
    url_traccar = entorno['TRACCAR_INTERNAL_URL']
    servidor = _asegurar(odoo, informe, 'traccar.server', [('base_url', '=', url_traccar)], {
        'name': datos['traccar_server']['name'],
        'base_url': url_traccar,
        'auth_type': AUTH_TRACCAR_ODOO,
        'username': entorno['INTEGRATION_TRACCAR_EMAIL'],
        'password': entorno['INTEGRATION_TRACCAR_PASSWORD'],
    }, f'traccar.server {url_traccar}')

    bodega = datos['bodega']
    _asegurar(odoo, informe, 'res.partner', [('name', '=', bodega['name'])],
              _sin_claves_documentales(bodega), f"res.partner {bodega['name']}")

    ids_conductor = {}
    for conductor in datos['conductores']:
        ids_conductor[conductor['name']] = _asegurar(
            odoo, informe, 'res.partner', [('name', '=', conductor['name'])],
            _sin_claves_documentales(conductor), f"res.partner {conductor['name']}")

    id_marca = _asegurar(odoo, informe, 'fleet.vehicle.model.brand', [('name', '=', datos['marca'])],
                         {'name': datos['marca']}, f"fleet.vehicle.model.brand {datos['marca']}")
    id_modelo = _asegurar(odoo, informe, 'fleet.vehicle.model',
                          [('name', '=', datos['modelo']), ('brand_id', '=', id_marca)],
                          {'name': datos['modelo'], 'brand_id': id_marca},
                          f"fleet.vehicle.model {datos['modelo']}")

    for vehiculo in datos['vehiculos']:
        placa = vehiculo['license_plate']
        _asegurar(odoo, informe, 'fleet.vehicle', [('license_plate', '=', placa)],
                  {'license_plate': placa, 'model_id': id_modelo, 'driver_id': ids_conductor[vehiculo['conductor']]},
                  f'fleet.vehicle {placa}')

    previos = {d['unique_id'] for d in odoo.ejecutar('traccar.device', 'search_read',
                                                       [[('server_id', '=', servidor)]],
                                                       {'fields': ['unique_id']})}
    odoo.ejecutar('traccar.server', 'action_sync_devices', [[servidor]])
    tras = odoo.ejecutar('traccar.device', 'search_read', [[('server_id', '=', servidor)]],
                         {'fields': ['unique_id', 'id']})
    ids_traccar_device = {d['unique_id']: d['id'] for d in tras}
    for uid in sorted(set(ids_traccar_device) - previos):
        informe.creados.append(f'traccar.device {uid} (importado con action_sync_devices)')

    for vehiculo in datos['vehiculos']:
        placa = vehiculo['license_plate']
        uid = vehiculo['uniqueId']
        if uid not in ids_traccar_device:
            raise ErrorSembrado(f'tras sincronizar, Odoo no tiene traccar.device con uniqueId {uid}')
        _asegurar(odoo, informe, 'fleet.vehicle', [('license_plate', '=', placa)],
                  {'traccar_device_id': ids_traccar_device[uid]},
                  f'fleet.vehicle {placa} vinculado a {uid}', crear=False)

    _sembrar_bodega_logistica(odoo, informe, datos['bodega_logistica'])
    ids_productos = _sembrar_productos(odoo, informe, datos['productos'])
    _sembrar_usuarios_conductor(odoo, entorno, informe, datos['usuarios_conductor'], ids_conductor)
    _sembrar_pedidos(odoo, informe, simulacion['pedidos'], ids_productos)


def _sembrar_bodega_logistica(odoo, informe, bodega):
    """La bodega activa de Odoo se alinea con la geocerca de Traccar (una sola bodega activa)."""
    valores = {'name': bodega['name'], 'latitude': bodega['latitude'], 'longitude': bodega['longitude']}
    if bodega.get('address'):
        valores['address'] = bodega['address']
    _asegurar(odoo, informe, 'logistica.bodega', [('active', '=', True)], valores,
              f"logistica.bodega {bodega['name']}")


def _sembrar_productos(odoo, informe, productos):
    """Articulos publicados en la tienda. Devuelve los ids de product.product."""
    ids = []
    for producto in productos:
        plantilla = _asegurar(odoo, informe, 'product.template', [('name', '=', producto['name'])],
                              _sin_claves_documentales(producto), f"product.template {producto['name']}")
        variantes = odoo.ejecutar('product.product', 'search', [[('product_tmpl_id', '=', plantilla)]], {'limit': 1})
        ids.append(variantes[0])
    return ids


def _sembrar_usuarios_conductor(odoo, entorno, informe, usuarios, ids_conductor):
    """Un usuario por conductor con el grupo del portal movil. La clave inicial sale de .env y nunca se reescribe."""
    id_grupo = odoo.ejecutar('ir.model.data', 'check_object_reference',
                             ['logistica_conductor', 'group_conductor'])[1]
    for usuario in usuarios:
        nombre = usuario['conductor']
        partner = ids_conductor[nombre]
        _asegurar(odoo, informe, 'res.partner', [('id', '=', partner)], {'is_driver': True},
                  f'res.partner {nombre} (marcado como conductor)', crear=False)
        etiqueta = f"res.users {usuario['login']}"
        existentes = odoo.ejecutar('res.users', 'search', [[('login', '=', usuario['login'])]],
                                   {'limit': 1, 'context': {'active_test': False}})
        if not existentes:
            clave_usuario = entorno.get(usuario.get('password_env', ''), entorno['DEMO_CONDUCTOR_PASSWORD'])
            odoo.ejecutar('res.users', 'create', [{
                'login': usuario['login'], 'partner_id': partner,
                'password': clave_usuario, 'groups_id': [(4, id_grupo)]}])
            informe.creados.append(etiqueta)
            continue
        grupos = odoo.ejecutar('res.users', 'read', [[existentes[0]], ['groups_id']])[0]['groups_id']
        if id_grupo in grupos:
            informe.omitidos.append(etiqueta)
        else:
            odoo.ejecutar('res.users', 'write', [[existentes[0]], {'groups_id': [(4, id_grupo)]}])
            informe.actualizados.append(etiqueta)


def _sembrar_pedidos(odoo, informe, pedidos, ids_productos):
    """Pedidos confirmados, con destino. La confirmacion crea la entrega en estado «en preparacion»."""
    for i, pedido in enumerate(pedidos):
        ref = pedido['ref']
        etiqueta = f'sale.order {ref}'
        existentes = odoo.ejecutar('sale.order', 'search_read', [[('client_order_ref', '=', ref)]],
                                   {'fields': ['state'], 'limit': 1})
        if existentes:
            if existentes[0]['state'] == 'draft':
                odoo.ejecutar('sale.order', 'action_confirm', [[existentes[0]['id']]])
                informe.actualizados.append(f'{etiqueta} (confirmado)')
            else:
                informe.omitidos.append(etiqueta)
            continue
        cliente = _asegurar(odoo, informe, 'res.partner', [('name', '=', pedido['cliente'])],
                            {'name': pedido['cliente']}, f"res.partner {pedido['cliente']}")
        orden = odoo.ejecutar('sale.order', 'create', [{
            'partner_id': cliente, 'client_order_ref': ref,
            'delivery_latitude': pedido['latitud'], 'delivery_longitude': pedido['longitud'],
            'order_line': [(0, 0, {'product_id': ids_productos[i % len(ids_productos)], 'product_uom_qty': 1})],
        }])
        odoo.ejecutar('sale.order', 'action_confirm', [[orden]])
        informe.creados.append(etiqueta)


def _registrar_administrador_inicial(entorno, informe):
    """Un Traccar recien instalado no tiene usuarios (/api/server: newServer=true). El primer usuario
    registrado queda como administrador; se registra el de TRACCAR_ADMIN_EMAIL para que el resto del sembrado entre."""
    anonimo = ClienteTraccar(entorno['TRACCAR_URL'], None, None)
    if not (anonimo.llamar('GET', '/api/server') or {}).get('newServer'):
        return
    correo = entorno['TRACCAR_ADMIN_EMAIL']
    anonimo.llamar('POST', '/api/users', {
        'name': 'Administrador', 'email': correo, 'password': entorno['TRACCAR_ADMIN_PASSWORD']})
    informe.creados.append(f'traccar.user {correo} (administrador inicial)')


def main():
    informe = Informe()
    try:
        datos_odoo, datos_traccar, datos_simulacion = schema.cargar()
        entorno = _leer_entorno()
        _registrar_administrador_inicial(entorno, informe)
        traccar = ClienteTraccar(entorno['TRACCAR_URL'], entorno['TRACCAR_ADMIN_EMAIL'],
                                 entorno['TRACCAR_ADMIN_PASSWORD'])
        ids_dispositivo = _sembrar_traccar(traccar, datos_traccar, informe)
        _sembrar_usuario_integracion(traccar, entorno, datos_traccar, ids_dispositivo, informe)
        odoo = ClienteOdoo(entorno['ODOO_URL'], entorno['ODOO_DB'], entorno['ODOO_USER'], entorno['ODOO_PASSWORD'])
        _sembrar_odoo(odoo, entorno, datos_odoo, informe, datos_simulacion)
    except schema.ErrorEsquema as error:
        print(f'seed: datos invalidos: {error}', file=sys.stderr)
        return 1
    except ErrorSembrado as error:
        print(f'seed: {error}', file=sys.stderr)
        return 1
    except xmlrpc.client.Fault as error:
        lineas = [linea for linea in str(error.faultString).splitlines() if linea.strip()]
        print(f'seed: Odoo rechazo la operacion: {lineas[-1] if lineas else "error sin detalle"}', file=sys.stderr)
        return 1
    except (OSError, xmlrpc.client.ProtocolError) as error:
        print(f'seed: no se pudo conectar con Odoo o Traccar: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'creados': informe.creados, 'actualizados': informe.actualizados,
                      'omitidos': informe.omitidos}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
