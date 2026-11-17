"""Herramientas de solo lectura del asistente del administrador.

Cada herramienta valida su entrada (pydantic), consulta Odoo con dominios fijos y devuelve un JSON
compacto. El modelo nunca escribe SQL ni elige modelos/campos: solo parametros acotados.
"""
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from .odoo import ErrorOdoo

ESTADOS_VENTA = ['sale', 'done']
ESTADOS_ENTREGA = {
    'pendiente_preparacion': 'Pendiente de preparación', 'en_preparacion': 'En preparación',
    'preparado': 'Preparado', 'asignado': 'Asignado', 'en_recorrido': 'En recorrido',
    'entregado': 'Entregado', 'no_entregado': 'No entregado',
    'pendiente_reprogramacion': 'Pendiente de reprogramación', 'devuelto_bodega': 'Devuelto a bodega',
}
PAGO = {'not_paid': 'sin pagar', 'partial': 'pago parcial', 'paid': 'pagada', 'in_payment': 'en proceso de pago',
        'reversed': 'revertida', 'invoicing_legacy': 'histórica'}
GPS_DESACTUALIZADO_MIN = 5


# ------------------------------------------------------------------ utilidades
def _rango(campo, desde, hasta, es_fecha_hora=True):
    dominio = []
    if desde:
        dominio.append((campo, '>=', f'{desde} 00:00:00' if es_fecha_hora else str(desde)))
    if hasta:
        dominio.append((campo, '<=', f'{hasta} 23:59:59' if es_fecha_hora else str(hasta)))
    return dominio


def _nombre(m2o):
    return m2o[1] if isinstance(m2o, (list, tuple)) and len(m2o) > 1 else None


def _id(m2o):
    return m2o[0] if isinstance(m2o, (list, tuple)) and m2o else None


def _dinero(valor):
    return round(float(valor or 0.0), 2)


async def _totales(odoo, modelo, dominio, sumas, por, minimos=(), maximos=()):
    """Totales de un dominio. Siempre agrupa por un campo y suma en Python: un read_group sin agrupar y sin
    filas hace que Odoo devuelva None, que su XML-RPC no puede enviar (TypeError: cannot marshal None)."""
    campos = [f'{c}:sum' for c in sumas] + [f'min_{c}:min({c})' for c in minimos] + [f'max_{c}:max({c})' for c in maximos]
    grupos = await odoo.read_group(modelo, dominio, campos, [por])
    total = {'__count': sum(g.get('__count', 0) for g in grupos)}
    for c in sumas:
        total[c] = sum(g.get(c) or 0 for g in grupos)
    for c in minimos:
        valores = [g[f'min_{c}'] for g in grupos if g.get(f'min_{c}')]
        total[f'min_{c}'] = min(valores) if valores else None
    for c in maximos:
        valores = [g[f'max_{c}'] for g in grupos if g.get(f'max_{c}')]
        total[f'max_{c}'] = max(valores) if valores else None
    return total


class _Periodo(BaseModel):
    desde: Optional[date] = Field(None, description='Fecha inicial (AAAA-MM-DD), incluida.')
    hasta: Optional[date] = Field(None, description='Fecha final (AAAA-MM-DD), incluida.')

    @field_validator('hasta')
    @classmethod
    def _orden(cls, hasta, info):
        desde = info.data.get('desde')
        if desde and hasta and hasta < desde:
            raise ValueError('hasta no puede ser anterior a desde')
        return hasta


# ------------------------------------------------------------------ entradas
class EntradaVentasPorCliente(_Periodo):
    top: int = Field(10, ge=1, le=50, description='Cuántos clientes devolver.')
    orden: Literal['monto', 'pedidos'] = Field('monto', description='Ordenar por monto vendido o por número de pedidos.')


class EntradaDetalleCliente(_Periodo):
    cliente: str = Field(min_length=2, max_length=120, description='Nombre (o parte del nombre) del cliente.')


class EntradaProductos(_Periodo):
    top: int = Field(10, ge=1, le=50)


class EntradaFacturas(_Periodo):
    estado: Literal['todas', 'pendientes', 'pagadas', 'vencidas'] = 'todas'
    cliente: Optional[str] = Field(None, max_length=120)
    limite: int = Field(25, ge=1, le=100)


class EntradaVentasPorPeriodo(_Periodo):
    agrupacion: Literal['dia', 'semana', 'mes'] = 'mes'


class EntradaOperacion(BaseModel):
    pass


# ------------------------------------------------------------------ implementaciones
async def ventas_por_cliente(odoo, e: EntradaVentasPorCliente):
    dominio = [('state', 'in', ESTADOS_VENTA)] + _rango('date_order', e.desde, e.hasta)
    orden = 'amount_total desc' if e.orden == 'monto' else '__count desc'
    try:
        grupos = await odoo.read_group('sale.order', dominio, ['amount_total:sum', 'ultima_compra:max(date_order)', 'partner_id'],
                                       ['partner_id'], orden=orden, limit=e.top)
    except ErrorOdoo:
        if e.orden != 'pedidos':
            raise
        # Algunas versiones no ordenan por __count: se ordena en Python.
        grupos = await odoo.read_group('sale.order', dominio, ['amount_total:sum', 'ultima_compra:max(date_order)', 'partner_id'],
                                       ['partner_id'])
        grupos = sorted(grupos, key=lambda g: g.get('__count', 0), reverse=True)[:e.top]
    total = await _totales(odoo, 'sale.order', dominio, ['amount_total'], 'state')
    total_general = _dinero(total['amount_total'])
    clientes = [{
        'cliente': _nombre(g['partner_id']), 'cliente_id': _id(g['partner_id']),
        'pedidos': g.get('__count', 0), 'total': _dinero(g.get('amount_total')),
        'participacion_pct': round(100 * _dinero(g.get('amount_total')) / total_general, 1) if total_general else 0.0,
        'ultima_compra': g.get('ultima_compra'),
    } for g in grupos]
    return {'criterio': f'ordenado por {e.orden}', 'periodo': _texto_periodo(e),
            'total_vendido_periodo': total_general,
            'pedidos_periodo': total['__count'],
            'clientes': clientes}


async def detalle_cliente(odoo, e: EntradaDetalleCliente):
    candidatos = await odoo.search_read('res.partner', [('name', 'ilike', e.cliente)], ['name'], limit=6)
    if not candidatos:
        return {'encontrado': False, 'mensaje': f'No hay clientes cuyo nombre contenga «{e.cliente}».'}
    if len(candidatos) > 1:
        exacto = [c for c in candidatos if c['name'].strip().lower() == e.cliente.strip().lower()]
        if len(exacto) != 1:
            return {'encontrado': False, 'ambiguo': True,
                    'candidatos': [c['name'] for c in candidatos],
                    'mensaje': 'Hay varios clientes con ese nombre; pide al usuario que elija uno.'}
        candidatos = exacto
    cliente = candidatos[0]
    dominio = [('partner_id', 'child_of', cliente['id']), ('state', 'in', ESTADOS_VENTA)] + \
        _rango('date_order', e.desde, e.hasta)
    pedidos = await odoo.search_read('sale.order', dominio, ['name', 'date_order', 'amount_total', 'invoice_status'],
                                     limit=20, order='date_order desc')
    r = await _totales(odoo, 'sale.order', dominio, ['amount_total'], 'state',
                       minimos=['date_order'], maximos=['date_order'])
    lineas = await odoo.read_group(
        'sale.order.line',
        [('order_id.partner_id', 'child_of', cliente['id']), ('order_id.state', 'in', ESTADOS_VENTA)]
        + _rango('order_id.date_order', e.desde, e.hasta),
        ['product_uom_qty:sum', 'price_subtotal:sum', 'product_id'], ['product_id'], orden='price_subtotal desc', limit=15)
    # Montos con signo: las notas de crédito restan.
    f = await _totales(
        odoo, 'account.move', [('partner_id', 'child_of', cliente['id']), ('move_type', 'in', ['out_invoice', 'out_refund']),
                               ('state', '=', 'posted')] + _rango('invoice_date', e.desde, e.hasta, es_fecha_hora=False),
        ['amount_total_signed', 'amount_residual_signed'], 'move_type')
    return {
        'encontrado': True, 'cliente': cliente['name'], 'periodo': _texto_periodo(e),
        'pedidos_confirmados': r['__count'], 'total_comprado': _dinero(r['amount_total']),
        'ticket_promedio': _dinero(r['amount_total'] / r['__count']) if r['__count'] else 0.0,
        'primera_compra': r['min_date_order'], 'ultima_compra': r['max_date_order'],
        'productos': [{'producto': _nombre(l['product_id']), 'cantidad': round(l.get('product_uom_qty') or 0, 2),
                       'subtotal': _dinero(l.get('price_subtotal'))} for l in lineas],
        'facturas_publicadas': f['__count'], 'facturado_neto': _dinero(f['amount_total_signed']),
        'por_cobrar': _dinero(f['amount_residual_signed']),
        'ultimos_pedidos': [{'pedido': p['name'], 'fecha': p['date_order'], 'total': _dinero(p['amount_total']),
                             'facturacion': p.get('invoice_status')} for p in pedidos],
    }


async def productos_mas_vendidos(odoo, e: EntradaProductos):
    dominio = [('order_id.state', 'in', ESTADOS_VENTA)] + _rango('order_id.date_order', e.desde, e.hasta)
    grupos = await odoo.read_group('sale.order.line', dominio, ['product_uom_qty:sum', 'price_subtotal:sum', 'product_id'],
                                   ['product_id'], orden='price_subtotal desc', limit=e.top)
    return {'periodo': _texto_periodo(e), 'productos': [{
        'producto': _nombre(g['product_id']), 'lineas': g.get('__count', 0),
        'cantidad': round(g.get('product_uom_qty') or 0, 2), 'subtotal_sin_impuestos': _dinero(g.get('price_subtotal')),
    } for g in grupos]}


async def facturas(odoo, e: EntradaFacturas):
    dominio = [('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted')] + \
        _rango('invoice_date', e.desde, e.hasta, es_fecha_hora=False)
    if e.estado == 'pendientes':
        dominio.append(('payment_state', 'in', ['not_paid', 'partial']))
    elif e.estado == 'pagadas':
        dominio.append(('payment_state', 'in', ['paid', 'in_payment']))
    elif e.estado == 'vencidas':
        dominio += [('payment_state', 'in', ['not_paid', 'partial']), ('invoice_date_due', '<', date.today().isoformat())]
    if e.cliente:
        dominio.append(('partner_id.name', 'ilike', e.cliente))
    filas = await odoo.search_read('account.move', dominio, [
        'name', 'partner_id', 'invoice_date', 'invoice_date_due', 'amount_total', 'amount_residual', 'payment_state',
        'move_type'], limit=e.limite, order='invoice_date desc, id desc')
    t = await _totales(odoo, 'account.move', dominio, ['amount_total_signed', 'amount_residual_signed'], 'move_type')
    borradores = await odoo.search_count('account.move', [('move_type', '=', 'out_invoice'), ('state', '=', 'draft')])
    hoy = date.today()
    return {
        'filtro': e.estado, 'periodo': _texto_periodo(e), 'cantidad': t['__count'],
        'total_facturado_neto': _dinero(t['amount_total_signed']), 'total_por_cobrar': _dinero(t['amount_residual_signed']),
        'facturas_en_borrador_sin_publicar': borradores,
        'mostradas': len(filas),
        'facturas': [{
            'numero': f['name'], 'cliente': _nombre(f['partner_id']), 'fecha': f.get('invoice_date') or None,
            'vence': f.get('invoice_date_due') or None, 'total': _dinero(f['amount_total']),
            'saldo': _dinero(f['amount_residual']), 'estado_pago': PAGO.get(f.get('payment_state'), f.get('payment_state')),
            'nota_credito': f.get('move_type') == 'out_refund',
            'dias_vencida': (hoy - date.fromisoformat(f['invoice_date_due'])).days
            if f.get('invoice_date_due') and f.get('amount_residual') and date.fromisoformat(f['invoice_date_due']) < hoy else 0,
        } for f in filas],
    }


async def ventas_por_periodo(odoo, e: EntradaVentasPorPeriodo):
    agrupar = {'dia': 'date_order:day', 'semana': 'date_order:week', 'mes': 'date_order:month'}[e.agrupacion]
    dominio = [('state', 'in', ESTADOS_VENTA)] + _rango('date_order', e.desde, e.hasta)
    grupos = await odoo.read_group('sale.order', dominio, ['amount_total:sum'], [agrupar], orden='date_order asc')
    return {'agrupacion': e.agrupacion, 'periodo': _texto_periodo(e), 'serie': [{
        'periodo': g.get(agrupar) or g.get('date_order'), 'pedidos': g.get('__count', 0),
        'total': _dinero(g.get('amount_total'))} for g in grupos]}


async def estado_operacion(odoo, _e: EntradaOperacion):
    entregas = await odoo.read_group('logistica.entrega', [], ['state'], ['state'])
    rutas = await odoo.search_read('logistica.ruta', [('state', 'in', ['planificada', 'carga_confirmada', 'en_recorrido'])],
                                   ['name', 'state', 'vehicle_plate', 'driver_id', 'date'], limit=30, order='date desc')
    dispositivos = await odoo.search_read('traccar.device', [], ['name', 'vehicle_id', 'last_position_time', 'last_speed'],
                                          limit=100)
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    vehiculos = []
    for d in dispositivos:
        ultima = d.get('last_position_time')
        minutos = round((ahora - datetime.fromisoformat(ultima)).total_seconds() / 60, 1) if ultima else None
        vehiculos.append({'vehiculo': _nombre(d.get('vehicle_id')) or d['name'], 'dispositivo': d['name'],
                          'ultima_posicion_utc': ultima or None, 'minutos_sin_senal': minutos,
                          'gps_desactualizado': minutos is None or minutos > GPS_DESACTUALIZADO_MIN,
                          'velocidad_kmh': round(d.get('last_speed') or 0, 1)})
    return {
        'entregas_por_estado': [{'estado': ESTADOS_ENTREGA.get(g['state'], g['state']), 'cantidad': g.get('__count', 0)}
                                for g in entregas],
        'rutas_activas': [{'ruta': r['name'], 'estado': r['state'], 'vehiculo': r.get('vehicle_plate'),
                           'conductor': _nombre(r.get('driver_id')), 'fecha': r.get('date')} for r in rutas],
        'vehiculos': vehiculos,
    }


def _texto_periodo(e):
    if e.desde and e.hasta:
        return f'{e.desde} a {e.hasta}'
    if e.desde:
        return f'desde {e.desde}'
    if e.hasta:
        return f'hasta {e.hasta}'
    return 'todo el historial'


# ------------------------------------------------------------------ registro
_PERIODO = ('Si el usuario no da fechas, no las envíes (se usa todo el historial). Para "este mes", '
            '"el mes pasado", etc., calcula las fechas a partir de la fecha actual indicada en el sistema.')

REGISTRO = {
    'ventas_por_cliente': {
        'etiqueta': 'Ranking de clientes',
        'entrada': EntradaVentasPorCliente, 'funcion': ventas_por_cliente,
        'descripcion': ('Ranking de clientes por ventas confirmadas (pedidos de venta en estado confirmado), con monto, '
                        'número de pedidos, % del total y última compra. Úsala para "mejor cliente", "quién compra '
                        'más", "top clientes". ' + _PERIODO),
    },
    'detalle_cliente': {
        'etiqueta': 'Ficha del cliente',
        'entrada': EntradaDetalleCliente, 'funcion': detalle_cliente,
        'descripcion': ('Consumo de un cliente: total comprado, ticket promedio, primera y última compra, productos que '
                        'más compra, facturado y saldo por cobrar, y sus últimos pedidos. ' + _PERIODO),
    },
    'productos_mas_vendidos': {
        'etiqueta': 'Productos más vendidos',
        'entrada': EntradaProductos, 'funcion': productos_mas_vendidos,
        'descripcion': 'Productos más vendidos por subtotal sin impuestos y cantidad. ' + _PERIODO,
    },
    'facturas': {
        'etiqueta': 'Facturas',
        'entrada': EntradaFacturas, 'funcion': facturas,
        'descripcion': ('Facturas de cliente publicadas (y notas de crédito): total facturado, saldo por cobrar, '
                        'facturas pendientes, pagadas o vencidas, opcionalmente de un cliente. También informa cuántas '
                        'facturas hay en borrador sin publicar. ' + _PERIODO),
    },
    'ventas_por_periodo': {
        'etiqueta': 'Evolución de ventas',
        'entrada': EntradaVentasPorPeriodo, 'funcion': ventas_por_periodo,
        'descripcion': 'Serie de ventas confirmadas por día, semana o mes, para ver tendencias. ' + _PERIODO,
    },
    'estado_operacion': {
        'etiqueta': 'Estado de la operación',
        'entrada': EntradaOperacion, 'funcion': estado_operacion,
        'descripcion': ('Foto actual de la operación logística: entregas por estado, rutas activas con vehículo y '
                        'conductor, y vehículos con su última señal GPS (marca los desactualizados).'),
    },
}


def definiciones():
    """Herramientas en el formato de la API, en orden fijo (estable para el caché de prompts)."""
    salida = []
    for nombre, h in REGISTRO.items():
        esquema = h['entrada'].model_json_schema()
        esquema.pop('title', None)
        for propiedad in esquema.get('properties', {}).values():
            propiedad.pop('title', None)
        esquema['additionalProperties'] = False
        salida.append({'name': nombre, 'description': h['descripcion'], 'input_schema': esquema,
                       'eager_input_streaming': True})
    return salida


async def ejecutar(odoo, nombre, entrada):
    """Devuelve (ok, contenido_json, ms). Nunca lanza: los errores vuelven como resultado de error."""
    inicio = time.monotonic()
    h = REGISTRO.get(nombre)
    if not h:
        return False, json.dumps({'error': f'herramienta desconocida: {nombre}'}), 0
    try:
        if not isinstance(entrada, dict):
            raise ValueError('la entrada debe ser un objeto JSON')
        datos = h['entrada'].model_validate(entrada)
        resultado = await h['funcion'](odoo, datos)
        ok = True
    except ValidationError as exc:
        resultado = {'error': 'parametros_invalidos',
                     'detalle': [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]}
        ok = False
    except (ErrorOdoo, ValueError) as exc:
        resultado = {'error': str(exc)}
        ok = False
    ms = int((time.monotonic() - inicio) * 1000)
    return ok, json.dumps(resultado, ensure_ascii=False, default=str), ms
