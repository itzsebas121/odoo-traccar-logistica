"""Tablero: API con un DWH falso (forma, sesión, filtros, errores, caché) y consultas reales contra un DWH de prueba."""
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, tablero

from .conftest import OdooFalso

CSRF = {'X-Agente': '1'}


class DwhFalso:
    """Imita tablero.Dwh: devuelve filas fijas por nombre de consulta y anota las llamadas."""

    def __init__(self, respuestas=None, error=None):
        self.respuestas = respuestas or {}
        self.error = error
        self.llamadas = []

    def consultar(self, nombre, sql, params=None):
        self.llamadas.append((nombre, params))
        if self.error:
            raise self.error
        r = self.respuestas.get(nombre, [])
        return r(params) if callable(r) else [dict(x) for x in r]


RESPUESTAS = {
    'ultimo_dia': [{'ultimo': '2026-11-16'}],
    'hay_demo': [{'hay': True}],
    'opciones_zonas': [{'codigo': 'centro', 'nombre': 'Centro'}, {'codigo': 'atocha', 'nombre': 'Atocha'}],
    'opciones_categorias': [{'categoria': 'Granos'}, {'categoria': 'Aseo'}],
    'opciones_conductores': [{'conductor': 'Carlos'}, {'conductor': 'Luis'}],
    'resumen_variacion': [{'importe_7d': 300.0, 'importe_7d_previo': 200.0, 'pedidos_7d': 10, 'pedidos_7d_previo': 8}],
    'resumen_total': [{'importe': 600.0, 'pedidos': 20, 'unidades': 50.0}],
    'resumen_serie': [{'fecha': '2026-11-15', 'procedencia': 'SIMULADO', 'pedidos': 3, 'importe': 90.0,
                       'unidades': 7.0}],
    'resumen_simulado': [{'simulados': 12, 'total': 20}],
    'resumen_pronostico': [{'fecha': '2026-11-10', 'tipo': 'backtest', 'pronostico': 20.0, 'real': 25.0},
                           {'fecha': '2026-11-17', 'tipo': 'pronostico', 'pronostico': 22.0, 'real': None}],
    'demanda_categoria': [{'categoria': 'Granos', 'unidades': 10.0, 'importe': 50.0, 'pedidos': 4}],
    'demanda_zona': [{'zona': 'centro', 'unidades': 8.0, 'importe': 40.0, 'pedidos': 3}],
    'demanda_top_zona': [{'zona': 'centro', 'producto_sk': 1, 'producto': '[ALI-ARR-2KG] Arroz', 'unidades': 5.0,
                          'importe': 9.0, 'puesto': 1},
                         {'zona': 'centro', 'producto_sk': 2, 'producto': 'Azúcar', 'unidades': 3.0, 'importe': 4.0,
                          'puesto': 2}],
    'demanda_mapa': [{'latitud': -1.241, 'longitud': -78.62, 'pedidos': 2, 'unidades': 3.0, 'importe': 10.0}],
    'pronostico_celdas': [
        {'producto_sk': 1, 'producto': '[ALI-ARR-2KG] Arroz', 'categoria': 'Granos', 'zona': 'centro',
         'unidades': 9.0, 'unidades_con_margen': 12.0, 'vendido_semana': 8.0, 'pronostico_semana': 7.0},
        {'producto_sk': 1, 'producto': '[ALI-ARR-2KG] Arroz', 'categoria': 'Granos', 'zona': 'atocha',
         'unidades': 3.0, 'unidades_con_margen': 4.0, 'vendido_semana': 3.0, 'pronostico_semana': 3.0},
        {'producto_sk': 2, 'producto': 'Azúcar', 'categoria': 'Granos', 'zona': 'centro', 'unidades': 6.0,
         'unidades_con_margen': 2.0, 'vendido_semana': None, 'pronostico_semana': None}],
    'pronostico_zonas_geo': [{'codigo': 'centro', 'nombre': 'Centro', 'latitud': -1.2417, 'longitud': -78.6197},
                             {'codigo': 'atocha', 'nombre': 'Atocha', 'latitud': -1.23, 'longitud': -78.65}],
    'pronostico_actualizado': [{'actualizado': '2026-11-17T10:00:00+00:00'}],
    'pronostico_serie': [
        {'fecha': '2026-11-10', 'tipo_registro': 'backtest', 'pronostico': 2.0, 'real': 3.0, 'p10': None,
         'p90': None, 'generado_utc': '2026-11-17T10:00:00+00:00'},
        {'fecha': '2026-11-17', 'tipo_registro': 'pronostico', 'pronostico': 2.5, 'real': None, 'p10': 1.0,
         'p90': 4.0, 'generado_utc': '2026-11-17T10:00:00+00:00'}],
    'pronostico_historia': [{'fecha': '2026-11-01', 'real': 4.0}],
    'operacion_entregas': [{'total': 10, 'entregadas': 7, 'no_entregadas': 2, 'pendientes': 1, 'a_tiempo': 6,
                            'con_plan': 7, 'cerradas': 9, 'con_gps': 6}],
    'operacion_por_dia': [{'fecha': '2026-11-15', 'resultado': 'entregado', 'entregas': 7}],
    'operacion_rutas': [{'codigo': 'R1', 'fecha': '2026-11-15', 'conductor': 'Carlos', 'placa': 'ABC',
                         'km_planificado': 10.0, 'km_real': 11.0, 'desviacion_km_pct': 10.0, 'min_planificado': 30.0,
                         'min_real': 35.0, 'desviacion_min_pct': 16.7, 'paradas_total': 5, 'pct_entregado': 80.0}],
    'operacion_plan_total': [{'rutas': 3, 'km_plan': 30.0, 'km_real': 31.0, 'rutas_con_gps': 2}],
    'operacion_conductores': [{'conductor': 'Carlos', 'rutas': 3, 'km_plan': 30.0, 'km_real': 31.0}],
}


@pytest.fixture
def dwh_falso():
    return DwhFalso(RESPUESTAS)


@pytest.fixture
def cliente(monkeypatch, dwh_falso):
    monkeypatch.setattr(main, 'odoo', OdooFalso())
    monkeypatch.setattr(main, 'limite_login', main.Limitador(100, 60))
    monkeypatch.setattr(main, 'dwh', dwh_falso)
    monkeypatch.setattr(main, 'cache_tablero', tablero.Cache())
    c = TestClient(main.app)
    r = c.post('/api/login', json={'login': 'admin@x', 'clave': 'buena'}, headers=CSRF)
    assert r.status_code == 200, r.text
    return c


SECCIONES = ['resumen', 'demanda', 'pronostico', 'pronostico_detalle', 'operacion', 'opciones']


@pytest.mark.parametrize('seccion', SECCIONES)
def test_tablero_sin_sesion_401(monkeypatch, seccion):
    monkeypatch.setattr(main, 'dwh', DwhFalso(RESPUESTAS))
    assert TestClient(main.app).get('/api/tablero/' + seccion).status_code == 401


def test_resumen(cliente):
    j = cliente.get('/api/tablero/resumen').json()
    # sin fechas: 30 días que terminan en el último día con ventas
    assert j['rango'] == {'desde': '2026-10-18', 'hasta': '2026-11-16', 'procedencia': None, 'zona': None,
                          'categoria': None, 'conductor': None}
    assert j['kpi']['importe'] == 600.0 and j['kpi']['pedidos'] == 20 and j['kpi']['ticket'] == 30.0
    assert j['kpi']['variacion_importe_7d'] == 50.0 and j['kpi']['variacion_pedidos_7d'] == 25.0
    assert j['simulado'] == {'pedidos': 12, 'total': 20}
    assert j['ultimo_dia'] == '2026-11-16' and j['hay_demo'] is True
    assert j['serie'][0]['procedencia'] == 'SIMULADO'
    # el pronóstico de todo el negocio se ve desde el resumen
    assert [p['tipo'] for p in j['pronostico_total']] == ['backtest', 'pronostico']
    assert j['pronostico_total'][1]['real'] is None


def test_opciones_de_los_filtros(cliente):
    j = cliente.get('/api/tablero/opciones').json()
    assert j['zonas'] == [{'codigo': 'centro', 'nombre': 'Centro'}, {'codigo': 'atocha', 'nombre': 'Atocha'}]
    assert j['categorias'] == ['Granos', 'Aseo'] and j['conductores'] == ['Carlos', 'Luis']


def test_filtros_llegan_a_la_consulta(cliente, dwh_falso):
    r = cliente.get('/api/tablero/demanda', params={'desde': '2026-11-01', 'hasta': '2026-11-10',
                                                    'procedencia': 'real'})
    assert r.status_code == 200
    nombre, params = dwh_falso.llamadas[0]
    assert nombre == 'demanda_categoria' and params['proc'] == 'REAL'
    assert str(params['desde']) == '2026-11-01' and str(params['hasta']) == '2026-11-10'
    j = r.json()
    assert j['top_por_zona'][0]['zona'] == 'centro' and len(j['top_por_zona'][0]['productos']) == 2
    assert j['top_por_zona'][0]['nombre'] == 'Centro' and j['zonas'][0]['nombre'] == 'Centro'
    assert j['top_por_zona'][0]['productos'][0]['producto'] == 'Arroz'      # sin el código interno
    assert j['puntos'][0]['latitud'] == -1.241


@pytest.mark.parametrize('seccion, extra', [
    ('resumen', {'zona': 'centro', 'categoria': 'Granos'}),
    ('demanda', {'zona': 'centro', 'categoria': 'Granos'}),
    ('pronostico', {'zona': 'centro', 'categoria': 'Granos'}),
    ('pronostico_detalle', {'zona': 'centro', 'categoria': 'Granos'}),
    ('operacion', {'zona': 'centro', 'conductor': 'Carlos'}),
])
def test_zona_categoria_y_conductor_llegan_a_todas_las_consultas(cliente, dwh_falso, seccion, extra):
    assert cliente.get('/api/tablero/' + seccion, params=extra).status_code == 200
    consultas = [p for n, p in dwh_falso.llamadas if p and 'zona' in p]
    assert consultas, 'ninguna consulta recibió filtros'
    for p in consultas:
        assert p['zona'] == 'centro'
        assert p['categoria'] == extra.get('categoria') and p['conductor'] == extra.get('conductor')


def test_cada_filtro_cambia_la_respuesta_cacheada(cliente, dwh_falso):
    cliente.get('/api/tablero/resumen')
    n = len(dwh_falso.llamadas)
    cliente.get('/api/tablero/resumen')
    assert len(dwh_falso.llamadas) == n                                      # igual: sale de la caché
    for extra in ({'zona': 'centro'}, {'categoria': 'Granos'}):
        antes = len(dwh_falso.llamadas)
        cliente.get('/api/tablero/resumen', params=extra)
        assert len(dwh_falso.llamadas) > antes, extra                        # otro filtro: se consulta de nuevo


@pytest.mark.parametrize('params', [{'procedencia': 'otra'}, {'desde': '2026-11-10', 'hasta': '2026-11-01'},
                                    {'desde': 'ayer'}, {'zona': 'x' * 200}, {'categoria': 'y' * 200}])
def test_filtros_invalidos_422(cliente, params):
    r = cliente.get('/api/tablero/resumen', params=params)
    assert r.status_code == 422 and r.json()['detalle']


def test_filtros_vacios_equivalen_a_ninguno(cliente, dwh_falso):
    cliente.get('/api/tablero/resumen', params={'zona': '  ', 'categoria': ''})
    assert all(p['zona'] is None and p['categoria'] is None for n, p in dwh_falso.llamadas if p and 'zona' in p)


def test_pronostico_general_por_producto_y_zona(cliente):
    j = cliente.get('/api/tablero/pronostico').json()
    assert len(j['celdas']) == 3
    arroz = [c for c in j['celdas'] if c['producto_sk'] == 1]
    assert {c['zona'] for c in arroz} == {'centro', 'atocha'} and arroz[0]['producto'] == 'Arroz'   # sin código interno
    assert j['celdas'][2]['vendido_semana'] == 0.0                         # sin ventas la semana pasada: 0, no null
    assert j['celdas'][0]['unidades_con_margen'] == 12.0 and j['celdas'][0]['pronostico_semana'] == 7.0
    assert j['celdas'][2]['unidades_con_margen'] == 6.0                    # con margen nunca baja de lo esperado
    assert [z['codigo'] for z in j['zonas']] == ['centro', 'atocha'] and j['zonas'][0]['latitud'] == -1.2417
    assert j['actualizado_utc'] == '2026-11-17T10:00:00+00:00'
    assert 'modelo' not in j and 'model_version' not in str(j)             # nada del modelo llega al navegador


def test_pronostico_zonas_en_el_centro_real_de_sus_unidades(monkeypatch, cliente):
    """Una zona se dibuja donde se vende (centro de sus unidades, pesado por lo esperado), no en su centroide fijo;
    la que no tiene unidades conserva el suyo. Las unidades viajan con sus coordenadas exactas."""
    import copy
    unidades = [{'unidad_id': 'd01', 'zona': 'atocha', 'latitud': -1.30, 'longitud': -78.70, 'unidades': 3.0},
                {'unidad_id': 's-1.340_-78.650', 'zona': 'atocha', 'latitud': -1.34, 'longitud': -78.65,
                 'unidades': 1.0}]
    monkeypatch.setattr(main, 'dwh', DwhFalso(dict(copy.deepcopy(RESPUESTAS), pronostico_unidades_geo=unidades)))
    main.cache_tablero.limpiar()
    j = cliente.get('/api/tablero/pronostico').json()
    zonas = {z['codigo']: z for z in j['zonas']}
    assert zonas['centro']['latitud'] == -1.2417                            # sin unidades: su centroide
    assert zonas['atocha']['latitud'] == -1.31 and zonas['atocha']['longitud'] == -78.6875
    assert [u['unidad_id'] for u in j['unidades']] == ['d01', 's-1.340_-78.650']


def test_pronostico_detalle_de_un_producto(cliente, dwh_falso):
    j = cliente.get('/api/tablero/pronostico_detalle', params={'producto_sk': 1, 'zona': 'centro'}).json()
    assert [p['tipo'] for p in j['serie']] == ['historia', 'backtest', 'pronostico']
    futuro = j['serie'][-1]
    assert futuro['p10'] <= futuro['pronostico'] <= futuro['p90'] and futuro['real'] is None
    consulta = next(p for n, p in dwh_falso.llamadas if n == 'pronostico_serie')
    assert consulta['sk'] == 1 and consulta['zona'] == 'centro'


def test_pronostico_detalle_de_todo_el_negocio_no_trae_rango(cliente, dwh_falso):
    j = cliente.get('/api/tablero/pronostico_detalle').json()          # sin producto: suma de todos
    assert next(p for n, p in dwh_falso.llamadas if n == 'pronostico_serie')['sk'] is None
    futuro = j['serie'][-1]
    assert futuro['tipo'] == 'pronostico' and futuro['p10'] is None and futuro['p90'] is None


def test_pronostico_sin_datos_avisa(monkeypatch, cliente):
    monkeypatch.setattr(main, 'dwh', DwhFalso(dict(RESPUESTAS, pronostico_celdas=[])))
    j = cliente.get('/api/tablero/pronostico').json()
    assert j['celdas'] == [] and 'Todavía no hay pronóstico' in j['aviso'] and 'ml-predecir' not in j['aviso']
    j = cliente.get('/api/tablero/pronostico', params={'zona': 'atocha'}).json()
    assert 'esa zona y categoría' in j['aviso']                             # con filtros, otro mensaje


def test_operacion(cliente):
    j = cliente.get('/api/tablero/operacion').json()
    assert j['kpi']['pct_a_tiempo'] == pytest.approx(85.7) and j['kpi']['pct_vinculadas_gps'] == pytest.approx(66.7)
    assert j['rutas'][0]['codigo'] == 'R1'
    assert j['conductores'] == [{'conductor': 'Carlos', 'rutas': 3, 'km_plan': 30.0, 'km_real': 31.0}]
    assert cliente.get('/api/tablero/etl').status_code == 404              # la calidad del ETL ya no está en el tablero


def test_sin_dwh_503_mensaje_simple_y_detalle_en_el_log(monkeypatch, cliente, caplog):
    monkeypatch.setattr(main, 'dwh', tablero.Dwh('db', '5432', 'logistica_dwh', 'dwh_ro', ''))
    with caplog.at_level('WARNING', logger='agente'):
        r = cliente.get('/api/tablero/resumen')
    assert r.status_code == 503 and r.json()['detalle'] == tablero.MENSAJE_USUARIO
    for tecnico in ('DWH_DB_PASSWORD', 'docker', 'etl bootstrap', 'DWH'):
        assert tecnico not in r.json()['detalle']
    assert 'DWH_DB_PASSWORD' in caplog.text                                # el administrador lo ve en el log
    monkeypatch.setattr(main, 'dwh', DwhFalso(error=tablero.SinDwh('Faltan las vistas del DWH. Corra etl bootstrap')))
    r = cliente.get('/api/tablero/operacion')
    assert r.status_code == 503 and r.json()['detalle'] == tablero.MENSAJE_USUARIO


def test_cache_evita_repetir_consultas(cliente, dwh_falso):
    cliente.get('/api/tablero/operacion')
    n = len(dwh_falso.llamadas)
    cliente.get('/api/tablero/operacion')
    assert len(dwh_falso.llamadas) == n
    cliente.get('/api/tablero/operacion', params={'procedencia': 'SIMULADO'})
    assert len(dwh_falso.llamadas) > n


def test_cache_vence():
    t = [0.0]
    c = tablero.Cache(ttl=60, reloj=lambda: t[0])
    calls = []
    assert c.obtener('k', lambda: calls.append(1) or 'a') == 'a'
    assert c.obtener('k', lambda: calls.append(1) or 'b') == 'a'
    t[0] = 61
    assert c.obtener('k', lambda: calls.append(1) or 'c') == 'c' and len(calls) == 2


def test_csp_permite_las_teselas_del_mapa(cliente):
    csp = cliente.get('/api/tablero/resumen').headers['content-security-policy']
    assert 'https://server.arcgisonline.com' in csp and 'cartocdn' not in csp and 'openstreetmap' not in csp


def test_sin_codigo_de_producto():
    assert tablero.sin_codigo('[ALI-ARR-2KG] Arroz blanco 2 kg') == 'Arroz blanco 2 kg'
    assert tablero.sin_codigo('Arroz [integral] 1 kg') == 'Arroz [integral] 1 kg'
    assert tablero.sin_codigo(None) == ''


# ------------------------------------------------------------------ consultas reales (DWH de prueba)
BI_TESTS = Path(__file__).resolve().parents[2] / 'bi' / 'tests'


@pytest.fixture
def dwh_real():
    """Base desechable con el esquema y las vistas del DWH y los datos de prueba del BI. Necesita DWH_ADMIN_DSN."""
    dsn = os.environ.get('DWH_ADMIN_DSN')
    if not dsn:
        pytest.skip('DWH_ADMIN_DSN no definido: pruebas de base de datos omitidas')
    if not BI_TESTS.is_dir():
        pytest.skip('services/bi/tests no está disponible')
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    spec = importlib.util.spec_from_file_location('bi_conftest', BI_TESTS / 'conftest.py')
    bi = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(bi)
    except ImportError as exc:          # el conftest del BI usa psycopg2
        pytest.skip('falta %s para poblar el DWH de prueba' % exc.name)
    nombre = 'agente_t_' + uuid.uuid4().hex[:8]
    with psycopg.connect(dsn, autocommit=True) as adm:
        adm.execute('CREATE DATABASE %s' % nombre)
    try:
        partes = conninfo_to_dict(dsn)
        with psycopg.connect(**dict(partes, dbname=nombre)) as con:
            with con.cursor() as cur:
                for f in ('dwh_schema.sql', 'dwh_views.sql', 'dwh_bi_views.sql'):
                    cur.execute((BI_TESTS / f).read_text(encoding='utf-8'))
                bi._poblar(cur)
        yield tablero.Dwh(partes.get('host'), partes.get('port') or '5432', nombre, partes.get('user'),
                          partes.get('password'))
    finally:
        with psycopg.connect(dsn, autocommit=True) as adm:
            adm.execute('DROP DATABASE IF EXISTS %s WITH (FORCE)' % nombre)


def test_consultas_reales_de_todas_las_secciones(dwh_real):
    f = tablero.Filtros()
    r = tablero.resumen(dwh_real, f)
    assert r['kpi']['pedidos'] > 0 and r['serie']
    d = tablero.demanda(dwh_real, f)
    assert d['categorias'] and d['top_por_zona'] and d['zonas']
    p = tablero.pronostico(dwh_real, f)
    assert p['celdas'] and p['zonas'] and p['actualizado_utc'] and 'modelo' not in p
    det = tablero.pronostico_detalle(dwh_real, f)
    assert {x['tipo'] for x in det['serie']} >= {'backtest', 'pronostico'}
    o = tablero.operacion(dwh_real, f)
    assert o['kpi']['entregas'] >= 0
    simulado = tablero.operacion(dwh_real, tablero.Filtros(procedencia='SIMULADO'))
    real = tablero.operacion(dwh_real, tablero.Filtros(procedencia='REAL'))
    assert simulado['kpi']['entregas'] + real['kpi']['entregas'] == o['kpi']['entregas']


def test_filtros_reales_reparten_el_total(dwh_real):
    """Cada filtro divide el total sin perder ni duplicar nada: la suma por zona (o categoría) es el total."""
    op = tablero.opciones(dwh_real)
    assert op['zonas'] and op['categorias']
    total = tablero.resumen(dwh_real, tablero.Filtros())['kpi']
    zonas = [z['codigo'] for z in op['zonas']] + ['(sin zona)']
    por_zona = [tablero.resumen(dwh_real, tablero.Filtros(zona=z))['kpi'] for z in zonas]
    assert sum(k['importe'] for k in por_zona) == pytest.approx(total['importe'])
    assert sum(k['pedidos'] for k in por_zona) == total['pedidos']           # un pedido pertenece a una sola zona
    por_cat = [tablero.resumen(dwh_real, tablero.Filtros(categoria=c))['kpi'] for c in op['categorias']]
    assert sum(k['importe'] for k in por_cat) == pytest.approx(total['importe'])
    assert sum(k['unidades'] for k in por_cat) == pytest.approx(total['unidades'])
    dem = tablero.demanda(dwh_real, tablero.Filtros())
    assert sum(z['importe'] for z in dem['zonas']) == pytest.approx(total['importe'])


def test_pronostico_real_cuadra_entre_celdas_y_detalle(dwh_real):
    """La suma de las celdas producto x zona es el total del detalle sin foco, y filtrar por zona o producto es un
    subconjunto exacto."""
    todo = tablero.pronostico(dwh_real, tablero.Filtros())
    total = sum(c['unidades'] for c in todo['celdas'])
    serie = tablero.pronostico_detalle(dwh_real, tablero.Filtros())['serie']
    assert sum(x['pronostico'] for x in serie if x['tipo'] == 'pronostico') == pytest.approx(total)
    zona = todo['celdas'][0]['zona']
    de_zona = tablero.pronostico(dwh_real, tablero.Filtros(zona=zona))
    assert sum(c['unidades'] for c in de_zona['celdas']) == pytest.approx(
        sum(c['unidades'] for c in todo['celdas'] if c['zona'] == zona))
    assert all(c['unidades_con_margen'] >= c['unidades'] for c in todo['celdas'])
    sk = todo['celdas'][0]['producto_sk']
    uno = tablero.pronostico_detalle(dwh_real, tablero.Filtros(), producto_sk=sk)['serie']
    assert sum(x['pronostico'] for x in uno if x['tipo'] == 'pronostico') == pytest.approx(
        sum(c['unidades'] for c in todo['celdas'] if c['producto_sk'] == sk))
    assert any(x['p10'] is not None for x in uno)                            # con producto sí hay rango probable
    cat = todo['celdas'][0]['categoria']
    assert {c['categoria'] for c in tablero.pronostico(dwh_real, tablero.Filtros(categoria=cat))['celdas']} == {cat}
    vacio = tablero.pronostico(dwh_real, tablero.Filtros(zona='no-existe'))
    assert vacio['celdas'] == [] and 'esa zona y categoría' in vacio['aviso']


def test_filtros_reales_de_operacion(dwh_real):
    op = tablero.opciones(dwh_real)
    total = tablero.operacion(dwh_real, tablero.Filtros())['kpi']['entregas']
    zonas = [z['codigo'] for z in op['zonas']] + ['(sin zona)']
    assert sum(tablero.operacion(dwh_real, tablero.Filtros(zona=z))['kpi']['entregas'] for z in zonas) == total
    cond = tablero.operacion(dwh_real, tablero.Filtros(conductor='Carlos'))
    assert cond['kpi']['entregas'] <= total
    assert all(c['conductor'] == 'Carlos' for c in cond['conductores'])


def test_consultas_iguales_al_tablero_de_odoo():
    """El modulo de Odoo logistica_tablero copia textualmente las consultas de este archivo (desde «utilidades
    SQL»): si se cambia una aqui, hay que copiarla alli. Se omite donde el repo no esta completo (imagen Docker)."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[3]
    odoo = raiz / 'odoo' / 'addons' / 'logistica_tablero' / 'tablero.py'
    if not odoo.exists():
        pytest.skip('sin el modulo de Odoo en esta copia del repo')
    marca = '# ------------------------------------------------------------------ utilidades SQL'
    propio = (Path(tablero.__file__)).read_text(encoding='utf-8')
    copia = odoo.read_text(encoding='utf-8')
    assert propio[propio.index(marca):] == copia[copia.index(marca):], \
        'Las consultas del tablero de Odoo difieren de las del asistente: copie el tramo desde «utilidades SQL».'
