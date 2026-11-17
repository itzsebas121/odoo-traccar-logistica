from types import SimpleNamespace as NS

import httpx

from app import agente
from app.config import cargar
from app.conversaciones import Almacen

from .conftest import ClaudeFalso, bloque_herramienta, bloque_texto, mensaje


async def _correr(claude, odoo, texto='¿Quién es el mejor cliente?'):
    conversacion = Almacen().crear(2, texto)
    eventos = [e async for e in agente.ejecutar_turno(claude, odoo, cargar(), conversacion, texto)]
    return conversacion, eventos


async def test_turno_con_herramienta_y_respuesta(odoo):
    odoo.read_group_respuestas[('sale.order', ('partner_id',))] = [
        {'partner_id': [5, 'Cliente A'], '__count': 2, 'amount_total': 80.0}]
    claude = ClaudeFalso([
        mensaje([bloque_herramienta('t1', 'ventas_por_cliente', {'top': 3})], stop='tool_use'),
        mensaje([bloque_texto('El mejor cliente es **Cliente A**.')]),
    ])
    conversacion, eventos = await _correr(claude, odoo)
    assert [e['evento'] for e in eventos] == ['herramienta', 'herramienta_resultado', 'texto', 'fin']
    assert eventos[1]['datos']['ok'] is True
    # Segunda petición: assistant(tool_use) + user(tool_result) añadidos al final, sin tocar lo anterior.
    segunda = claude.peticiones[1]['messages']
    assert segunda[0] == {'role': 'user', 'content': '¿Quién es el mejor cliente?'}
    assert segunda[2]['content'][0]['type'] == 'tool_result'
    assert segunda[2]['content'][0]['tool_use_id'] == 't1'
    p = claude.peticiones[0]
    assert p['model'] == 'claude-opus-5-5' and p['fallbacks'] == 'default'
    assert p['thinking']['type'] == 'adaptive' and 'temperature' not in p
    assert len(conversacion.historial) == 4
    assert conversacion.vista[-1]['bloques'][0]['estado'] == 'ok'


async def test_rechazo_descarta_el_turno(odoo):
    claude = ClaudeFalso([mensaje([bloque_texto('parcial')], stop='refusal')])
    conversacion, eventos = await _correr(claude, odoo)
    assert eventos[-1]['evento'] == 'error'
    assert conversacion.historial == []


async def test_error_de_api_no_deja_tool_use_huerfano(odoo):
    class ClaudeQueFalla(ClaudeFalso):
        def _stream(self, **kwargs):
            if self.peticiones:
                raise agente.anthropic.APIConnectionError(request=httpx.Request('POST', 'https://api.example'))
            return super()._stream(**kwargs)

    claude = ClaudeQueFalla([mensaje([bloque_herramienta('t1', 'estado_operacion', {})], stop='tool_use')])
    conversacion, eventos = await _correr(claude, odoo)
    assert eventos[-1] == {'evento': 'error', 'datos': {'mensaje': 'No hay conexión con la API de Claude.'}}
    assert conversacion.historial == []


def test_sanear_contenido_tras_fallback():
    bloques = [NS(type='thinking'), NS(type='text', text='a'), NS(type='tool_use'), NS(type='fallback'),
               NS(type='thinking'), NS(type='tool_use')]
    assert [b.type for b in agente.sanear_contenido(bloques)] == ['text', 'fallback', 'thinking', 'tool_use']
    sin = [NS(type='thinking'), NS(type='text')]
    assert agente.sanear_contenido(sin) == sin
