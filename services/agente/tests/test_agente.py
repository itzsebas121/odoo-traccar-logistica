import httpx
import openai

from app import agente
from app.config import cargar
from app.conversaciones import Almacen

from .conftest import IAFalsa, bloque_herramienta, bloque_rechazo, bloque_texto, mensaje


async def _correr(ia, odoo, texto='¿Quién es el mejor cliente?'):
    conversacion = Almacen().crear(2, texto)
    eventos = [e async for e in agente.ejecutar_turno(ia, odoo, cargar(), conversacion, texto)]
    return conversacion, eventos


async def test_turno_con_herramienta_y_respuesta(odoo):
    odoo.read_group_respuestas[('sale.order', ('partner_id',))] = [
        {'partner_id': [5, 'Cliente A'], '__count': 2, 'amount_total': 80.0}]
    ia = IAFalsa([
        mensaje([bloque_herramienta('c1', 'ventas_por_cliente', {'top': 3})]),
        mensaje([bloque_texto('El mejor cliente es **Cliente A**.')]),
    ])
    conversacion, eventos = await _correr(ia, odoo)
    tipos = [e['evento'] for e in eventos]
    assert tipos == ['pensamiento', 'herramienta', 'herramienta_resultado', 'pensamiento', 'texto', 'fin']
    assert eventos[2]['datos']['ok'] is True
    # Segunda petición: la llamada y su resultado añadidos al final, sin tocar lo anterior.
    segunda = ia.peticiones[1]['input']
    assert segunda[0] == {'role': 'user', 'content': '¿Quién es el mejor cliente?'}
    assert segunda[1]['type'] == 'function_call' and segunda[1]['call_id'] == 'c1'
    assert segunda[2]['type'] == 'function_call_output' and segunda[2]['call_id'] == 'c1'
    p = ia.peticiones[0]
    assert p['model'] == 'gpt-6.1-sol' and p['store'] is False and p['stream'] is True
    assert p['include'] == ['reasoning.encrypted_content']
    assert p['reasoning'] == {'effort': 'medium', 'summary': 'auto'}
    assert p['tools'][0]['type'] == 'function' and 'parameters' in p['tools'][0]
    assert len(conversacion.historial) == 4
    assert conversacion.vista[-1]['bloques'][1]['estado'] == 'ok'


async def test_argumentos_invalidos_vuelven_como_error_al_modelo(odoo):
    llamada = bloque_herramienta('c1', 'facturas', {})
    llamada.arguments = '{no es json'
    ia = IAFalsa([mensaje([llamada]), mensaje([bloque_texto('Lo intento de nuevo.')])])
    _conversacion, eventos = await _correr(ia, odoo)
    assert eventos[2]['evento'] == 'herramienta_resultado' and eventos[2]['datos']['ok'] is False
    assert eventos[-1]['evento'] == 'fin'


async def test_rechazo_descarta_el_turno(odoo):
    ia = IAFalsa([mensaje([bloque_rechazo()])])
    conversacion, eventos = await _correr(ia, odoo)
    assert eventos[-1]['evento'] == 'error'
    assert conversacion.historial == []


async def test_respuesta_cortada_con_herramienta_pendiente(odoo):
    ia = IAFalsa([mensaje([bloque_herramienta('c1', 'estado_operacion', {})], estado='incomplete',
                          motivo='max_output_tokens')])
    conversacion, eventos = await _correr(ia, odoo)
    assert eventos[-1]['evento'] == 'error' and conversacion.historial == []


async def test_error_de_api_no_deja_llamada_huerfana(odoo):
    ia = IAFalsa([mensaje([bloque_herramienta('c1', 'estado_operacion', {})])])
    original = ia.responses.create

    async def crear(**kwargs):
        if ia.peticiones:
            raise openai.APIConnectionError(request=httpx.Request('POST', 'https://api.example'))
        return await original(**kwargs)

    ia.responses.create = crear
    conversacion, eventos = await _correr(ia, odoo)
    assert eventos[-1] == {'evento': 'error', 'datos': {'mensaje': 'No hay conexión con la API de OpenAI.'}}
    assert conversacion.historial == []
