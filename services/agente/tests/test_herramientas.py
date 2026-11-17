import json

from app import herramientas


async def test_ranking_clientes_calcula_participacion_y_filtra_estado(odoo):
    odoo.read_group_respuestas[('sale.order', ('partner_id',))] = [
        {'partner_id': [5, 'Cliente A'], '__count': 3, 'amount_total': 300.0, 'ultima_compra': '2026-11-01 10:00:00'},
        {'partner_id': [6, 'Cliente B'], '__count': 1, 'amount_total': 100.0, 'ultima_compra': '2026-10-01 10:00:00'}]
    odoo.read_group_respuestas[('sale.order', ('state',))] = [{'__count': 3, 'amount_total': 300.0},
                                                         {'__count': 1, 'amount_total': 100.0}]
    ok, contenido, _ms = await herramientas.ejecutar(odoo, 'ventas_por_cliente', {'desde': '2026-10-01', 'top': 5})
    datos = json.loads(contenido)
    assert ok
    assert datos['clientes'][0] == {'cliente': 'Cliente A', 'cliente_id': 5, 'pedidos': 3, 'total': 300.0,
                                    'participacion_pct': 75.0, 'ultima_compra': '2026-11-01 10:00:00'}
    dominio = odoo.llamadas[0][2]
    assert ('state', 'in', ['sale', 'done']) in dominio
    assert ('date_order', '>=', '2026-10-01 00:00:00') in dominio


async def test_parametros_invalidos_vuelven_como_error_sin_consultar(odoo):
    ok, contenido, _ = await herramientas.ejecutar(odoo, 'ventas_por_cliente',
                                                   {'top': 500, 'desde': '2026-12-01', 'hasta': '2026-01-01'})
    assert not ok
    assert json.loads(contenido)['error'] == 'parametros_invalidos'
    assert odoo.llamadas == []


async def test_herramienta_desconocida_y_valor_fuera_de_lista(odoo):
    ok, _, _ = await herramientas.ejecutar(odoo, 'borrar_todo', {})
    assert not ok
    ok, contenido, _ = await herramientas.ejecutar(odoo, 'facturas', {'limite': 9999})
    assert not ok and 'parametros_invalidos' in contenido


async def test_cliente_ambiguo_pide_aclaracion(odoo):
    odoo.search_read_respuestas['res.partner'] = [{'id': 1, 'name': 'Cliente Norte'},
                                                  {'id': 2, 'name': 'Cliente Norte 2'}]
    ok, contenido, _ = await herramientas.ejecutar(odoo, 'detalle_cliente', {'cliente': 'Norte'})
    datos = json.loads(contenido)
    assert ok and datos['ambiguo'] and len(datos['candidatos']) == 2


async def test_facturas_venta_directa_sin_saldos(odoo):
    odoo.search_read_respuestas['account.move'] = [{
        'name': 'FAC/001', 'partner_id': [5, 'Cliente A'], 'invoice_date': '2026-01-01', 'amount_total': 50.0,
        'amount_untaxed': 50.0, 'payment_state': 'paid', 'move_type': 'out_invoice', 'invoice_origin': 'S00001'}]
    ok, contenido, _ = await herramientas.ejecutar(odoo, 'facturas', {'cliente': 'Cliente A'})
    datos = json.loads(contenido)
    assert ok
    assert datos['facturas'][0] == {'numero': 'FAC/001', 'pedido': 'S00001', 'cliente': 'Cliente A',
                                    'fecha': '2026-01-01', 'total': 50.0, 'sin_impuestos': 50.0, 'pagada': True,
                                    'nota_credito': False}
    assert 'total_por_cobrar' not in datos and datos['facturas_sin_pagar_anomalia'] == 0
    ok, contenido, _ = await herramientas.ejecutar(odoo, 'facturas', {'estado': 'vencidas'})
    assert not ok and 'parametros_invalidos' in contenido  # ya no existen filtros de deuda


def test_definiciones_estables_y_sin_campos_extra():
    defs = herramientas.definiciones()
    assert [d['name'] for d in defs] == list(herramientas.REGISTRO)
    assert all(d['type'] == 'function' and d['parameters']['additionalProperties'] is False for d in defs)
    assert defs == herramientas.definiciones()  # mismo orden y contenido: no rompe el caché


async def test_totales_sin_filas_no_usa_read_group_sin_agrupar(odoo):
    ok, contenido, _ = await herramientas.ejecutar(odoo, 'facturas', {})
    datos = json.loads(contenido)
    assert ok and datos['cantidad'] == 0 and datos['total_facturado'] == 0.0
    assert all(llamada[4] for llamada in odoo.llamadas if llamada[0] == 'read_group')
