"""Dobles de prueba: Odoo y la API de Claude simulados (sin red)."""
import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault('AGENTE_SESSION_SECRET', 'x' * 40)
os.environ.setdefault('AGENTE_COOKIE_SEGURA', 'false')
os.environ.setdefault('AGENTE_STATIC_DIR', os.path.join(os.path.dirname(__file__), 'no-existe'))


class OdooFalso:
    def __init__(self):
        self.llamadas = []
        self.read_group_respuestas = {}
        self.search_read_respuestas = {}

    async def read_group(self, modelo, dominio, campos, agrupar, orden=None, limit=None):
        self.llamadas.append(('read_group', modelo, dominio, campos, agrupar, orden, limit))
        respuesta = self.read_group_respuestas.get((modelo, tuple(agrupar)))
        return respuesta(dominio) if callable(respuesta) else (respuesta or [])

    async def search_read(self, modelo, dominio, campos, limit=None, order=None):
        self.llamadas.append(('search_read', modelo, dominio, campos, limit, order))
        respuesta = self.search_read_respuestas.get(modelo)
        return respuesta(dominio) if callable(respuesta) else (respuesta or [])

    async def search_count(self, modelo, dominio):
        return 0

    async def autenticar_persona(self, login, clave):
        return {'admin@x': 2, 'vendedor@x': 7}.get(login) if clave == 'buena' else None

    async def datos_admin(self, uid, grupo):
        return {'name': 'Administrador', 'login': 'admin@x'} if uid == 2 else None


def bloque_texto(texto):
    return NS(type='text', text=texto)


def bloque_herramienta(id_, nombre, entrada):
    return NS(type='tool_use', id=id_, name=nombre, input=entrada)


def mensaje(contenido, stop='end_turn'):
    return NS(content=contenido, stop_reason=stop,
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class _Stream:
    def __init__(self, final, eventos):
        self._final, self._eventos = final, eventos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for evento in self._eventos:
            yield evento

    async def get_final_message(self):
        return self._final


class ClaudeFalso:
    """Devuelve, en orden, los mensajes finales indicados; guarda los parámetros de cada llamada."""

    def __init__(self, finales):
        self.finales = list(finales)
        self.peticiones = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        # Copia del historial en el momento de la llamada (luego se sigue modificando).
        self.peticiones.append({**kwargs, 'messages': list(kwargs['messages'])})
        final = self.finales.pop(0)
        eventos = [NS(type='text', text=b.text) for b in final.content if b.type == 'text']
        return _Stream(final, eventos)


@pytest.fixture
def odoo():
    return OdooFalso()
