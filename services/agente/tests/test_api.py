import pytest
from fastapi.testclient import TestClient

from app import main

from .conftest import ClaudeFalso, OdooFalso, bloque_texto, mensaje

CSRF = {'X-Agente': '1'}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(main, 'odoo', OdooFalso())
    monkeypatch.setattr(main, 'almacen', main.Almacen())
    monkeypatch.setattr(main, 'limite_login', main.Limitador(100, 60))
    return TestClient(main.app)


def _entrar(cliente):
    r = cliente.post('/api/login', json={'login': 'admin@x', 'clave': 'buena'}, headers=CSRF)
    assert r.status_code == 200, r.text


def test_login_exige_cabecera_csrf(cliente):
    assert cliente.post('/api/login', json={'login': 'admin@x', 'clave': 'buena'}).status_code == 403


def test_login_solo_administradores(cliente):
    assert cliente.post('/api/login', json={'login': 'admin@x', 'clave': 'mala'}, headers=CSRF).status_code == 401
    r = cliente.post('/api/login', json={'login': 'vendedor@x', 'clave': 'buena'}, headers=CSRF)
    assert r.status_code == 403
    _entrar(cliente)
    assert cliente.get('/api/yo').json()['nombre'] == 'Administrador'


def test_api_sin_sesion_401(cliente):
    assert cliente.get('/api/conversaciones').status_code == 401
    assert cliente.post('/api/chat', json={'mensaje': 'hola'}, headers=CSRF).status_code == 401


def test_chat_transmite_eventos_y_guarda_conversacion(cliente, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'prueba')
    claude = ClaudeFalso([mensaje([bloque_texto('Hola, soy el asistente.')])])
    monkeypatch.setattr(main, 'cliente_claude', lambda: claude)
    _entrar(cliente)
    r = cliente.post('/api/chat', json={'mensaje': 'hola'}, headers=CSRF)
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/event-stream')
    assert 'event: conversacion' in r.text and 'event: texto' in r.text and 'event: fin' in r.text
    lista = cliente.get('/api/conversaciones').json()
    assert len(lista) == 1
    detalle = cliente.get(f"/api/conversaciones/{lista[0]['id']}").json()
    assert [m['rol'] for m in detalle['mensajes']] == ['usuario', 'asistente']


def test_chat_sin_clave_api_avisa(cliente, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    _entrar(cliente)
    r = cliente.post('/api/chat', json={'mensaje': 'hola'}, headers=CSRF)
    assert 'ANTHROPIC_API_KEY' in r.text


def test_conversacion_inexistente_404(cliente):
    _entrar(cliente)
    assert cliente.get('/api/conversaciones/no-existe').status_code == 404
