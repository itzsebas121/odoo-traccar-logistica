"""Tablero de indicadores dentro de Odoo: lee el DWH (base logistica_dwh) con el rol de solo lectura dwh_ro.

Mismas secciones, filtros y consultas que el tablero del asistente (services/agente/app/tablero.py). Todo lo que
va desde «utilidades SQL» hasta el final es una COPIA TEXTUAL de ese archivo: si cambia una consulta alli, se copia
aqui (lo vigila tests/test_tablero.py::test_consultas_iguales_al_asistente). Este encabezado es lo propio de Odoo:
la conexion usa psycopg2 (el de Odoo) y el codigo corre en Python 3.9.

Solo consulta las vistas planas `v_bi_*` (services/etl/sql/dwh_bi_views.sql), nunca las tablas. Cada resultado se
guarda 60 s en memoria por (seccion, filtros) en cada proceso de Odoo.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

PROCEDENCIAS = ('REAL', 'SIMULADO')
DIAS_POR_DEFECTO = 30
TTL_S = 60
MAX_PUNTOS_MAPA = 1500
MAX_TEXTO = 80

AYUDA = ('Revise que DWH_DB_PASSWORD este definida para el servicio odoo y los registros de etl-scheduler '
         '(crea el DWH y lo carga al arrancar).')
MENSAJE_USUARIO = ('Los datos del tablero no están disponibles por ahora. Inténtalo de nuevo en unos minutos; '
                   'si sigue igual, avisa a quien administra el sistema.')


class SinDwh(RuntimeError):
    """El DWH no está configurado, no responde o le faltan las vistas: el mensaje dice qué hacer."""


@dataclass(frozen=True)
class Filtros:
    desde: date | None = None
    hasta: date | None = None
    procedencia: str | None = None
    zona: str | None = None
    categoria: str | None = None
    conductor: str | None = None

    def clave(self):
        return (self.desde, self.hasta, self.procedencia, self.zona, self.categoria, self.conductor)


class Dwh:
    """Conexión de solo lectura al DWH con psycopg2, por partes (la clave puede tener cualquier carácter)."""

    def __init__(self, host, port, dbname, user, password):
        self.params = dict(host=host, port=port, dbname=dbname, user=user, password=password)

    @classmethod
    def desde_entorno(cls):
        e = os.environ.get
        return cls(e('DWH_HOST') or 'db', e('DWH_PORT') or '5432', e('DWH_NAME') or 'logistica_dwh',
                   e('DWH_USER') or 'dwh_ro', e('DWH_DB_PASSWORD') or '')

    def consultar(self, nombre, sql, params=None):
        """Filas como dicts. `nombre` identifica la consulta (lo usan las pruebas con un DWH falso)."""
        if not self.params['password']:
            raise SinDwh('El tablero necesita el DWH: defina DWH_DB_PASSWORD (rol dwh_ro). ' + AYUDA)
        import psycopg2
        import psycopg2.errors
        from psycopg2.extras import RealDictCursor
        try:
            con = psycopg2.connect(connect_timeout=5, **self.params)
        except psycopg2.OperationalError as exc:
            raise SinDwh('No se pudo conectar al DWH (%s). %s' % (str(exc).splitlines()[0][:160], AYUDA)) from exc
        try:
            con.set_session(readonly=True)
            with con.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params or {})
                return [_limpiar(dict(f)) for f in cur.fetchall()]
        except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn) as exc:
            raise SinDwh('Faltan las vistas del DWH (%s). %s' % (str(exc).splitlines()[0], AYUDA)) from exc
        except psycopg2.OperationalError as exc:
            raise SinDwh('No se pudo consultar el DWH (%s). %s' % (str(exc).splitlines()[0][:160], AYUDA)) from exc
        finally:
            con.close()


def _limpiar(fila):
    out = {}
    for k, v in fila.items():
        if isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, (date, datetime)):
            v = v.isoformat()
        out[k] = v
    return out


class Cache:
    def __init__(self, ttl=TTL_S, reloj=time.monotonic):
        self.ttl, self.reloj, self._datos, self._lock = ttl, reloj, {}, threading.Lock()

    def obtener(self, clave, calcular):
        ahora = self.reloj()
        with self._lock:
            hit = self._datos.get(clave)
            if hit and hit[0] > ahora:
                return hit[1]
        valor = calcular()
        with self._lock:
            self._datos[clave] = (ahora + self.ttl, valor)
        return valor

    def limpiar(self):
        with self._lock:
            self._datos.clear()


# ------------------------------------------------------------------ utilidades SQL
# Cada condición se activa solo si el filtro viene (si no, `%(x)s::text IS NULL` la deja pasar).
PROC = '(%(proc)s::text IS NULL OR procedencia = %(proc)s)'
FILTRO = 'fecha BETWEEN %(desde)s AND %(hasta)s AND ' + PROC
ZONA = '(%(zona)s::text IS NULL OR zona = %(zona)s)'
ZONA_APROX = '(%(zona)s::text IS NULL OR zona_aprox = %(zona)s)'      # pronóstico: zona más cercana a cada unidad
CATEGORIA = '(%(categoria)s::text IS NULL OR categoria = %(categoria)s)'
CONDUCTOR = '(%(conductor)s::text IS NULL OR conductor = %(conductor)s)'
# una ruta pasa por una zona si alguna de sus paradas está en ella
RUTA_EN_ZONA = ('(%(zona)s::text IS NULL OR ruta_id_odoo IN '
                '(SELECT ruta_id_odoo FROM v_bi_paradas WHERE zona = %(zona)s))')


def _params(f):
    return {'desde': f.desde, 'hasta': f.hasta, 'proc': f.procedencia, 'zona': f.zona, 'categoria': f.categoria,
            'conductor': f.conductor}


def resolver(dwh, f):
    """Completa las fechas que falten: ventana de DIAS_POR_DEFECTO que termina en el último día con ventas."""
    if f.desde and f.hasta:
        return f
    hasta = f.hasta
    if hasta is None:
        ultimo = ultimo_dia(dwh)
        hasta = date.fromisoformat(ultimo) if ultimo else date.today()
    desde = f.desde or hasta - timedelta(days=DIAS_POR_DEFECTO - 1)
    return replace(f, desde=desde, hasta=hasta)


def _rango(f):
    return {'desde': f.desde.isoformat(), 'hasta': f.hasta.isoformat(), 'procedencia': f.procedencia,
            'zona': f.zona, 'categoria': f.categoria, 'conductor': f.conductor}


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def _num(v):
    return 0.0 if v is None else float(v)


def sin_codigo(nombre):
    """'[ALI-ARR-2KG] Arroz blanco 2 kg' -> 'Arroz blanco 2 kg': el código interno no es para el usuario."""
    return re.sub(r'^\s*\[[^\]]*\]\s*', '', nombre or '')


def _limpiar_productos(filas):
    for f in filas:
        if 'producto' in f:
            f['producto'] = sin_codigo(f['producto'])
    return filas


def ultimo_dia(dwh):
    """Último día con pedidos (None si no hay)."""
    fila = dwh.consultar('ultimo_dia', 'SELECT max(fecha) AS ultimo FROM v_bi_pedidos')
    return fila[0]['ultimo'] if fila and fila[0]['ultimo'] else None


def nombres_zona(dwh):
    """{código: nombre} de las zonas activas (para mostrar «Centro» y no «centro»)."""
    filas = dwh.consultar('opciones_zonas', 'SELECT zona AS codigo, nombre FROM v_bi_dim_zona WHERE activa ORDER BY nombre')
    return {z['codigo']: z['nombre'] for z in filas}


# ------------------------------------------------------------------ secciones
def resumen(dwh, f):
    f = resolver(dwh, f)
    p = _params(f)
    ventana = dwh.consultar('resumen_variacion', f"""
        SELECT COALESCE(SUM(importe) FILTER (WHERE fecha > %(hasta)s::date - 7), 0) AS importe_7d,
               COALESCE(SUM(importe) FILTER (WHERE fecha <= %(hasta)s::date - 7), 0) AS importe_7d_previo,
               COUNT(DISTINCT pedido_id_odoo) FILTER (WHERE fecha > %(hasta)s::date - 7) AS pedidos_7d,
               COUNT(DISTINCT pedido_id_odoo) FILTER (WHERE fecha <= %(hasta)s::date - 7) AS pedidos_7d_previo
        FROM v_bi_lineas_venta
        WHERE fecha BETWEEN %(hasta)s::date - 13 AND %(hasta)s AND {PROC} AND {ZONA} AND {CATEGORIA}""", p)[0]
    tot = dwh.consultar('resumen_total', f"""
        SELECT COALESCE(SUM(importe), 0) AS importe, COUNT(DISTINCT pedido_id_odoo) AS pedidos,
               COALESCE(SUM(unidades), 0) AS unidades
        FROM v_bi_lineas_venta WHERE {FILTRO} AND {ZONA} AND {CATEGORIA}""", p)[0]
    serie = dwh.consultar('resumen_serie', f"""
        SELECT fecha, procedencia, COUNT(DISTINCT pedido_id_odoo) AS pedidos, SUM(importe) AS importe,
               SUM(unidades) AS unidades
        FROM v_bi_lineas_venta WHERE {FILTRO} AND {ZONA} AND {CATEGORIA}
        GROUP BY fecha, procedencia ORDER BY fecha""", p)
    sim = dwh.consultar('resumen_simulado', f"""
        SELECT COUNT(DISTINCT pedido_id_odoo) FILTER (WHERE procedencia = 'SIMULADO') AS simulados,
               COUNT(DISTINCT pedido_id_odoo) AS total
        FROM v_bi_lineas_venta
        WHERE fecha BETWEEN %(desde)s AND %(hasta)s AND {ZONA} AND {CATEGORIA}""", p)[0]
    demo = dwh.consultar('hay_demo', "SELECT EXISTS (SELECT 1 FROM v_bi_pedidos WHERE procedencia = 'SIMULADO') AS hay")
    # Pronóstico de todo el negocio (suma de productos) con los mismos filtros de zona y categoría
    total = dwh.consultar('resumen_pronostico', f"""
        SELECT fecha, tipo_registro AS tipo, SUM(unidades_pred) AS pronostico, SUM(unidades_real) AS real
        FROM v_bi_demanda_real_vs_pronostico WHERE {ZONA_APROX} AND {CATEGORIA}
        GROUP BY fecha, tipo_registro ORDER BY fecha""", p)

    def var(a, b):
        return round(100.0 * (_num(a) - _num(b)) / _num(b), 1) if _num(b) else None

    pedidos = int(tot['pedidos'] or 0)
    return {
        'rango': _rango(f),
        'ultimo_dia': ultimo_dia(dwh),
        'hay_demo': bool(demo and demo[0]['hay']),
        'kpi': {'importe': _num(tot['importe']), 'pedidos': pedidos, 'unidades': _num(tot['unidades']),
                'ticket': round(_num(tot['importe']) / pedidos, 2) if pedidos else None,
                'variacion_importe_7d': var(ventana['importe_7d'], ventana['importe_7d_previo']),
                'variacion_pedidos_7d': var(ventana['pedidos_7d'], ventana['pedidos_7d_previo'])},
        'serie': serie,
        'simulado': {'pedidos': int(sim['simulados'] or 0), 'total': int(sim['total'] or 0)},
        'pronostico_total': [{'fecha': r['fecha'], 'tipo': r['tipo'], 'pronostico': _num(r['pronostico']),
                              'real': None if r['real'] is None else _num(r['real'])} for r in total],
    }


def demanda(dwh, f):
    f = resolver(dwh, f)
    p = dict(_params(f), max_puntos=MAX_PUNTOS_MAPA)
    categorias = dwh.consultar('demanda_categoria', f"""
        SELECT categoria, SUM(unidades) AS unidades, SUM(importe) AS importe,
               COUNT(DISTINCT pedido_id_odoo) AS pedidos
        FROM v_bi_lineas_venta WHERE {FILTRO} AND {ZONA} AND {CATEGORIA}
        GROUP BY categoria ORDER BY importe DESC""", p)
    zonas = dwh.consultar('demanda_zona', f"""
        SELECT zona, SUM(unidades) AS unidades, SUM(importe) AS importe, COUNT(DISTINCT pedido_id_odoo) AS pedidos
        FROM v_bi_lineas_venta WHERE {FILTRO} AND {ZONA} AND {CATEGORIA}
        GROUP BY zona ORDER BY importe DESC""", p)
    top = dwh.consultar('demanda_top_zona', f"""
        SELECT zona, producto_sk, producto, unidades, importe, puesto FROM (
            SELECT zona, producto_sk, producto, SUM(unidades) AS unidades, SUM(importe) AS importe,
                   ROW_NUMBER() OVER (PARTITION BY zona ORDER BY SUM(unidades) DESC, producto) AS puesto
            FROM v_bi_lineas_venta WHERE {FILTRO} AND {ZONA} AND {CATEGORIA}
            GROUP BY zona, producto_sk, producto) x
        WHERE puesto <= 5 ORDER BY zona, puesto""", p)
    puntos = dwh.consultar('demanda_mapa', f"""
        SELECT latitud, longitud, SUM(pedidos) AS pedidos, SUM(unidades) AS unidades, SUM(importe) AS importe
        FROM v_bi_ventas_mapa WHERE {FILTRO} AND {ZONA} AND {CATEGORIA}
        GROUP BY latitud, longitud ORDER BY importe DESC LIMIT %(max_puntos)s""", p)
    nombres = nombres_zona(dwh)
    por_zona = {}
    for r in _limpiar_productos(top):
        por_zona.setdefault(r['zona'], []).append(r)
    return {'rango': _rango(f), 'categorias': categorias,
            'zonas': [dict(z, nombre=nombres.get(z['zona'], z['zona'])) for z in zonas],
            'top_por_zona': [{'zona': z, 'nombre': nombres.get(z, z), 'productos': v} for z, v in por_zona.items()],
            'puntos': puntos}


def pronostico(dwh, f):
    """Pronóstico de los próximos 7 días por producto y zona, con los filtros de zona y categoría. Devuelve las celdas
    producto x zona (lo esperado y lo vendido la última semana) y las zonas con su ubicación para el mapa. La zona de
    un pronóstico es la zona más cercana al centro de su unidad de ubicación (aproximada)."""
    f = resolver(dwh, f)
    p = _params(f)
    celdas = _limpiar_productos(dwh.consultar('pronostico_celdas', f"""
        SELECT producto_sk, producto, categoria, COALESCE(zona_aprox, '(sin zona)') AS zona,
               SUM(unidades_pred) FILTER (WHERE tipo_registro = 'pronostico') AS unidades,
               SUM(p90) FILTER (WHERE tipo_registro = 'pronostico') AS unidades_con_margen,
               SUM(unidades_real) FILTER (WHERE tipo_registro = 'backtest') AS vendido_semana,
               SUM(unidades_pred) FILTER (WHERE tipo_registro = 'backtest') AS pronostico_semana
        FROM v_bi_demanda_real_vs_pronostico WHERE {ZONA_APROX} AND {CATEGORIA}
        GROUP BY producto_sk, producto, categoria, COALESCE(zona_aprox, '(sin zona)')
        HAVING SUM(unidades_pred) FILTER (WHERE tipo_registro = 'pronostico') IS NOT NULL
        ORDER BY producto, zona""", p))
    if not celdas:
        aviso = ('No hay pronóstico para esa zona y categoría.' if f.zona or f.categoria else
                 'Todavía no hay pronóstico disponible. Se publica automáticamente cuando el sistema lo calcula.')
        return {'rango': _rango(f), 'zonas': [], 'unidades': [], 'celdas': [], 'actualizado_utc': None,
                'aviso': aviso}
    for c in celdas:
        for k in ('unidades', 'unidades_con_margen', 'vendido_semana', 'pronostico_semana'):
            c[k] = _num(c.get(k))
        # con margen nunca es menos que lo esperado (los rangos vienen de errores pasados, no del pronóstico)
        c['unidades_con_margen'] = max(c['unidades_con_margen'], c['unidades'])
    zonas = dwh.consultar('pronostico_zonas_geo', """
        SELECT zona AS codigo, nombre, latitud, longitud FROM v_bi_dim_zona
        WHERE activa AND latitud IS NOT NULL AND longitud IS NOT NULL ORDER BY nombre""")
    # Unidades de ubicación del modelo con su centro real (el de los pedidos) y lo esperado en 7 días.
    unidades = dwh.consultar('pronostico_unidades_geo', f"""
        SELECT unidad_id, COALESCE(zona_aprox, '(sin zona)') AS zona, latitud, longitud,
               SUM(unidades_pred) AS unidades
        FROM v_bi_demanda_real_vs_pronostico
        WHERE tipo_registro = 'pronostico' AND latitud IS NOT NULL AND longitud IS NOT NULL
          AND {ZONA_APROX} AND {CATEGORIA}
        GROUP BY unidad_id, COALESCE(zona_aprox, '(sin zona)'), latitud, longitud
        ORDER BY unidades DESC""", p)
    for u in unidades:
        u['unidades'] = _num(u.get('unidades'))
    # Cada zona se dibuja donde de verdad se vende: el centro de sus unidades, pesado por lo esperado (la zona
    # residual «otra», por ejemplo, no tiene un lugar fijo). Sin unidades, su centroide de Odoo.
    peso = {}
    for u in unidades:
        w = max(u['unidades'], 1e-6)
        acc = peso.setdefault(u['zona'], [0.0, 0.0, 0.0])
        acc[0] += w * u['latitud']
        acc[1] += w * u['longitud']
        acc[2] += w
    for z in zonas:
        if z['codigo'] in peso:
            lat, lon, w = peso[z['codigo']]
            z['latitud'], z['longitud'] = round(lat / w, 7), round(lon / w, 7)
    fecha = dwh.consultar('pronostico_actualizado', 'SELECT max(generado_utc) AS actualizado FROM v_bi_demanda_real_vs_pronostico')
    return {'rango': _rango(f), 'zonas': zonas, 'unidades': unidades, 'celdas': celdas,
            'actualizado_utc': fecha[0]['actualizado'] if fecha else None}


def pronostico_detalle(dwh, f, producto_sk=None):
    """Lo vendido, la prueba de la última semana y los próximos días de un producto (o de todos si no se indica), en la
    zona y categoría filtradas. Sin producto no hay rango probable: sumar los rangos de muchas series no tiene sentido."""
    f = resolver(dwh, f)
    p = dict(_params(f), sk=producto_sk)
    SK = '(%(sk)s::int IS NULL OR producto_sk = %(sk)s)'
    modelada = dwh.consultar('pronostico_serie', f"""
        SELECT fecha, tipo_registro, SUM(unidades_pred) AS pronostico, SUM(unidades_real) AS real,
               SUM(p10) AS p10, SUM(p90) AS p90
        FROM v_bi_demanda_real_vs_pronostico WHERE {SK} AND {ZONA_APROX} AND {CATEGORIA}
        GROUP BY fecha, tipo_registro ORDER BY fecha""", p)
    inicio = min((r['fecha'] for r in modelada), default=None)
    # lo vendido antes del tramo del modelo: desde el inicio del periodo elegido (y al menos 2 semanas)
    historia = dwh.consultar('pronostico_historia', f"""
        SELECT fecha, SUM(unidades) AS real FROM v_bi_ventas_diarias
        WHERE {SK} AND fecha >= LEAST(%(desde)s::date, %(inicio)s::date - 14) AND fecha < %(inicio)s::date
          AND {PROC} AND {ZONA} AND {CATEGORIA}
        GROUP BY fecha ORDER BY fecha""", dict(p, inicio=inicio)) if inicio else []
    serie = [{'fecha': r['fecha'], 'real': _num(r['real']), 'pronostico': None, 'p10': None, 'p90': None,
              'tipo': 'historia'} for r in historia]
    for r in modelada:
        es_pron = r['tipo_registro'] == 'pronostico'
        con_rango = es_pron and producto_sk is not None
        serie.append({'fecha': r['fecha'], 'real': None if es_pron else _num(r['real']),
                      'pronostico': _num(r['pronostico']), 'p10': _num(r['p10']) if con_rango else None,
                      'p90': _num(r['p90']) if con_rango else None, 'tipo': r['tipo_registro']})
    return {'rango': _rango(f), 'serie': serie}


def operacion(dwh, f):
    f = resolver(dwh, f)
    p = _params(f)
    ent = dwh.consultar('operacion_entregas', f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE resultado = 'entregado') AS entregadas,
               COUNT(*) FILTER (WHERE resultado = 'no_entregado') AS no_entregadas,
               COUNT(*) FILTER (WHERE resultado = 'pendiente') AS pendientes,
               COUNT(*) FILTER (WHERE a_tiempo) AS a_tiempo, COUNT(a_tiempo) AS con_plan,
               COUNT(*) FILTER (WHERE completado_utc IS NOT NULL) AS cerradas,
               COUNT(*) FILTER (WHERE completado_utc IS NOT NULL AND vinculada_gps) AS con_gps
        FROM v_bi_entregas WHERE {FILTRO} AND {ZONA} AND {CONDUCTOR}""", p)[0]
    por_dia = dwh.consultar('operacion_por_dia', f"""
        SELECT fecha, resultado, COUNT(*) AS entregas FROM v_bi_entregas WHERE {FILTRO} AND {ZONA} AND {CONDUCTOR}
        GROUP BY fecha, resultado ORDER BY fecha""", p)
    rutas = dwh.consultar('operacion_rutas', f"""
        SELECT codigo, fecha, conductor, placa, km_planificado, km_real, desviacion_km_pct, min_planificado,
               min_real, desviacion_min_pct, paradas_total, pct_entregado
        FROM v_bi_ruta_plan_vs_real
        WHERE {FILTRO} AND km_planificado IS NOT NULL AND {CONDUCTOR} AND {RUTA_EN_ZONA}
        ORDER BY fecha DESC, codigo LIMIT 50""", p)
    plan = dwh.consultar('operacion_plan_total', f"""
        SELECT COUNT(*) AS rutas, SUM(km_planificado) AS km_plan, SUM(km_real) AS km_real,
               COUNT(km_real) AS rutas_con_gps
        FROM v_bi_ruta_plan_vs_real WHERE {FILTRO} AND {CONDUCTOR} AND {RUTA_EN_ZONA}""", p)[0]
    # km planificados y reales por conductor, solo de las rutas medidas (para que sean comparables)
    conductores = dwh.consultar('operacion_conductores', f"""
        SELECT conductor, COUNT(*) AS rutas, SUM(km_planificado) AS km_plan, SUM(km_real) AS km_real
        FROM v_bi_ruta_plan_vs_real
        WHERE {FILTRO} AND conductor IS NOT NULL AND km_real IS NOT NULL AND {CONDUCTOR} AND {RUTA_EN_ZONA}
        GROUP BY conductor ORDER BY km_real DESC LIMIT 15""", p)
    return {
        'rango': _rango(f),
        'kpi': {'entregas': int(ent['total'] or 0), 'entregadas': int(ent['entregadas'] or 0),
                'no_entregadas': int(ent['no_entregadas'] or 0), 'pendientes': int(ent['pendientes'] or 0),
                'pct_a_tiempo': _pct(ent['a_tiempo'] or 0, ent['con_plan'] or 0),
                'pct_vinculadas_gps': _pct(ent['con_gps'] or 0, ent['cerradas'] or 0),
                'rutas': int(plan['rutas'] or 0), 'rutas_con_gps': int(plan['rutas_con_gps'] or 0),
                'km_planificado': _num(plan['km_plan']), 'km_real': _num(plan['km_real'])},
        'por_dia': por_dia, 'rutas': rutas, 'conductores': conductores,
    }


def opciones(dwh, _f=None):
    """Valores para los filtros: zonas (código y nombre), categorías de producto y conductores."""
    zonas = dwh.consultar('opciones_zonas', 'SELECT zona AS codigo, nombre FROM v_bi_dim_zona WHERE activa ORDER BY nombre')
    categorias = dwh.consultar('opciones_categorias', """
        SELECT DISTINCT categoria FROM v_bi_dim_producto WHERE categoria IS NOT NULL ORDER BY 1""")
    conductores = dwh.consultar('opciones_conductores', """
        SELECT DISTINCT conductor FROM v_bi_ruta_plan_vs_real WHERE conductor IS NOT NULL ORDER BY 1""")
    return {'zonas': zonas, 'categorias': [c['categoria'] for c in categorias],
            'conductores': [c['conductor'] for c in conductores]}


SECCIONES = {'resumen': resumen, 'demanda': demanda, 'pronostico': pronostico,
             'pronostico_detalle': pronostico_detalle, 'operacion': operacion, 'opciones': opciones}


def _texto(valor, nombre):
    valor = (valor or '').strip()
    if not valor:
        return None
    if len(valor) > MAX_TEXTO:
        raise ValueError('%s es demasiado largo' % nombre)
    return valor


def filtros(desde=None, hasta=None, procedencia=None, zona=None, categoria=None, conductor=None):
    """Valida los parámetros de la URL. ValueError con un mensaje legible si algo no cuadra."""
    proc = (procedencia or '').strip().upper() or None
    if proc in ('TODAS', 'TODOS'):
        proc = None
    if proc is not None and proc not in PROCEDENCIAS:
        raise ValueError('procedencia debe ser REAL, SIMULADO o vacía')
    d = date.fromisoformat(desde) if desde else None
    h = date.fromisoformat(hasta) if hasta else None
    if d and h and d > h:
        raise ValueError('desde no puede ser posterior a hasta')
    if d and h and (h - d).days > 366:
        raise ValueError('el rango no puede superar un año')
    return Filtros(d, h, proc, _texto(zona, 'zona'), _texto(categoria, 'categoria'), _texto(conductor, 'conductor'))
