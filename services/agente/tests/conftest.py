"""Dobles de prueba: Odoo y la API de OpenAI (Responses API) simulados, sin red."""
import json
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


class Item(NS):
    """Elemento de salida de la Responses API (con model_dump, como los objetos del SDK)."""

    def model_dump(self, **_kwargs):
        return {k: v for k, v in vars(self).items() if v is not None}


def bloque_texto(texto):
    return Item(type='message', role='assistant', id='msg_1',
                content=[Item(type='output_text', text=texto, annotations=[])])


def bloque_rechazo():
    return Item(type='message', role='assistant', id='msg_r', content=[Item(type='refusal', refusal='no')])


def bloque_herramienta(id_, nombre, entrada):
    return Item(type='function_call', id=f'fc_{id_}', call_id=id_, name=nombre, arguments=json.dumps(entrada))


def mensaje(salida, estado='completed', motivo=None):
    return NS(output=salida, status=estado,
              incomplete_details=NS(reason=motivo) if motivo else None,
              usage=NS(input_tokens=10, output_tokens=5, input_tokens_details=NS(cached_tokens=0),
                       output_tokens_details=NS(reasoning_tokens=2)))


class _Flujo:
    def __init__(self, eventos):
        self._eventos = eventos

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for evento in self._eventos:
            yield evento


class IAFalsa:
    """Devuelve, en orden, las respuestas finales indicadas como un flujo de eventos; guarda cada petición."""

    def __init__(self, finales):
        self.finales = list(finales)
        self.peticiones = []
        self.responses = NS(create=self._create)

    async def _create(self, **kwargs):
        self.peticiones.append({**kwargs, 'input': list(kwargs['input'])})
        final = self.finales.pop(0)
        eventos = [NS(type='response.reasoning_summary_text.delta', delta='pensando')]
        for item in final.output:
            eventos.append(NS(type='response.output_item.added', item=item))
            if item.type == 'message':
                eventos += [NS(type='response.output_text.delta', delta=c.text)
                            for c in item.content if c.type == 'output_text']
        tipo_fin = 'response.completed' if final.status == 'completed' else 'response.incomplete'
        eventos.append(NS(type=tipo_fin, response=final))
        return _Flujo(eventos)


@pytest.fixture
def odoo():
    return OdooFalso()
