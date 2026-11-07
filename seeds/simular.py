# -*- coding: utf-8 -*-
"""Envia a Traccar, por el protocolo OsmAnd, las rutas de seeds/data/simulacion.json.

Solo biblioteca estandar. Las coordenadas viven en el JSON, no en este archivo.
TRACCAR_OSMAND_URL es obligatoria y no tiene valor por defecto. SIM_INTERVALO_S,
si falta o esta vacia, espera 0 segundos entre posiciones.
"""
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from seeds import schema


class ErrorSimulacion(RuntimeError):
    """El simulador no pudo enviar una posicion. El mensaje no incluye cuerpos de respuesta."""


def construir_url(base, unique_id, punto):
    """GET OsmAnd: id, lat, lon, speed (nudos) y timestamp (segundos unix)."""
    consulta = urllib.parse.urlencode({
        'id': unique_id,
        'lat': punto['lat'],
        'lon': punto['lon'],
        'speed': punto['speed'],
        'timestamp': int(punto['timestamp']),
    })
    return base.rstrip('/') + '/?' + consulta


def url_osmand():
    valor = os.environ.get('TRACCAR_OSMAND_URL', '').strip()
    if not valor:
        raise ErrorSimulacion(
            'falta TRACCAR_OSMAND_URL (revise .env); no tiene valor por defecto')
    return valor


def intervalo_s():
    crudo = os.environ.get('SIM_INTERVALO_S', '').strip()
    if not crudo:
        return 0.0
    try:
        valor = float(crudo)
    except ValueError:
        raise ErrorSimulacion('SIM_INTERVALO_S debe ser un numero de segundos') from None
    if valor < 0:
        raise ErrorSimulacion('SIM_INTERVALO_S no puede ser negativo')
    return valor


def _enviar(base, unique_id, punto):
    destino = construir_url(base, unique_id, punto)
    peticion = urllib.request.Request(destino, method='GET')
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            codigo = respuesta.status
    except urllib.error.HTTPError as error:
        raise ErrorSimulacion(f'OsmAnd respondio HTTP {error.code}') from None
    except urllib.error.URLError as error:
        raise ErrorSimulacion(f'no hay respuesta de OsmAnd ({error.reason})') from None
    if codigo != 200:
        raise ErrorSimulacion(f'OsmAnd respondio HTTP {codigo}')


def ejecutar(base, espera_s=0.0):
    """Envia cada punto de cada ruta. Devuelve cuantas posiciones se enviaron."""
    _odoo, _traccar, simulacion = schema.cargar()
    enviadas = 0
    for ruta in simulacion['rutas']:
        for punto in ruta['puntos']:
            if enviadas and espera_s:
                time.sleep(espera_s)
            _enviar(base, ruta['uniqueId'], punto)
            enviadas += 1
    return enviadas


def main():
    try:
        enviadas = ejecutar(url_osmand(), intervalo_s())
    except (ErrorSimulacion, schema.ErrorEsquema) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    print(enviadas)
    return 0


if __name__ == '__main__':
    sys.exit(main())
