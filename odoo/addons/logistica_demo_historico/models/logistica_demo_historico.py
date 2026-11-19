# -*- coding: utf-8 -*-
"""Registro de días históricos para la demostración y el entrenamiento del ML.

Las acciones de negocio (confirmar pedido, aprobar ruta, entregar...) fijan sus fechas en «ahora» y algunos campos
(fechas de ruta y parada, eventos de entrega) están protegidos o son de solo inserción. Este modelo ejecuta las
mismas acciones y, al final, reescribe las fechas con SQL para que el histórico tenga la hora en que ocurrió.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

PREFIJO_CLAVE = 'historico:'
# Antes de confirmar la carga, la entrega se prepara y se asigna; se fechan unos minutos antes.
MIN_PREPARADO = 40
MIN_ASIGNADO = 20


def _ts(valor):
    return fields.Datetime.to_datetime(valor) if valor else None


class LogisticaDemoHistorico(models.AbstractModel):
    _name = 'logistica.demo.historico'
    _description = 'Registro de histórico de demostración'

    # ------------------------------------------------------------------ utilidades
    def _ultimo_evento(self):
        self.env['logistica.entrega.evento'].flush_model()
        self.env.cr.execute('SELECT COALESCE(MAX(id), 0) FROM logistica_entrega_evento')
        return self.env.cr.fetchone()[0]

    def _fechar_eventos(self, desde_id, momento, lat=None, lon=None):
        """Pone `momento` a los eventos creados después de `desde_id` (los de la acción que se acaba de ejecutar)."""
        self.env['logistica.entrega.evento'].flush_model()
        self.env.cr.execute(
            """UPDATE logistica_entrega_evento
                  SET event_time = %(t)s,
                      gps_time = CASE WHEN gps_available THEN %(t)s ELSE gps_time END,
                      gps_age_seconds = CASE WHEN gps_available THEN 0 ELSE gps_age_seconds END,
                      gps_latitude = CASE WHEN gps_available AND %(lat)s IS NOT NULL THEN %(lat)s ELSE gps_latitude END,
                      gps_longitude = CASE WHEN gps_available AND %(lon)s IS NOT NULL THEN %(lon)s ELSE gps_longitude END,
                      create_date = %(t)s
                WHERE id > %(desde)s""",
            {'t': momento, 'lat': lat, 'lon': lon, 'desde': desde_id})
        return self._ultimo_evento()

    # ------------------------------------------------------------------ pedidos
    def _registrar_pedido(self, p):
        """Crea y confirma un pedido con su fecha histórica. Devuelve True si lo creó."""
        Pedido = self.env['sale.order'].sudo()
        if Pedido.search_count([('client_order_ref', '=', p['ref'])]):
            return False
        momento = _ts(p['fecha'])
        marca = self._ultimo_evento()
        pedido = Pedido.create({
            'partner_id': p['partner_id'],
            'client_order_ref': p['ref'],
            'delivery_latitude': p['lat'],
            'delivery_longitude': p['lon'],
            'order_line': [(0, 0, {'product_id': pid, 'product_uom_qty': qty}) for pid, qty in p['lineas']],
        })
        pedido.action_confirm()
        self.env.flush_all()
        cr = self.env.cr
        cr.execute('UPDATE sale_order SET date_order = %s, create_date = %s WHERE id = %s',
                   (momento, momento, pedido.id))
        cr.execute('UPDATE sale_order_line SET create_date = %s WHERE order_id = %s', (momento, pedido.id))
        cr.execute('UPDATE logistica_entrega SET create_date = %s WHERE sale_order_id = %s', (momento, pedido.id))
        self._fechar_eventos(marca, momento)
        return True

    # ------------------------------------------------------------------ rutas
    def _preparar_entrega(self, entrega):
        """Deja la entrega en «preparado» para poder agregarla a una ruta. False si no se puede."""
        if entrega.state == 'en_preparacion':
            entrega.action_marcar_preparado()
        elif entrega.state in ('no_entregado', 'pendiente_reprogramacion'):
            entrega.action_reprogramar()
        return entrega.state == 'preparado'

    def _registrar_ruta(self, r):
        """Crea una ruta y la recorre de principio a fin. Devuelve el número de paradas o 0 si no la creó."""
        Ruta = self.env['logistica.ruta'].sudo()
        clave = PREFIJO_CLAVE + r['clave']
        if Ruta.search_count([('optimization_version', '=', clave)]):
            return 0
        carga, inicio, fin = _ts(r['carga']), _ts(r['inicio']), _ts(r['fin'])
        Entrega = self.env['logistica.entrega'].sudo()
        paradas, marca = [], self._ultimo_evento()
        for p in r['paradas']:
            entrega = Entrega.search([('sale_order_id.client_order_ref', '=', p['ref'])], limit=1)
            if not entrega or not self._preparar_entrega(entrega):
                _logger.info('historico: la entrega del pedido %s no se puede despachar; se omite', p['ref'])
                continue
            paradas.append((entrega, p))
        if not paradas:
            return 0
        marca = self._fechar_eventos(marca, carga - timedelta(minutes=MIN_PREPARADO))
        ruta = Ruta.create({
            'vehicle_id': r['vehicle_id'],
            'driver_id': r['driver_id'],
            'date': r['fecha'],
            'optimization_version': clave,
            'distance_source': 'estimado_haversine',
            'planned_distance_km': r.get('km') or 0.0,
            'planned_duration_min': r.get('min') or 0.0,
            'stop_ids': [(0, 0, {'entrega_id': e.id, 'sequence': (i + 1) * 10}) for i, (e, _p) in enumerate(paradas)],
        })
        ruta.action_aprobar_plan()
        marca = self._fechar_eventos(marca, carga - timedelta(minutes=MIN_ASIGNADO))
        ruta.action_confirmar_carga()
        marca = self._fechar_eventos(marca, carga)
        ruta.action_iniciar_recorrido()
        marca = self._fechar_eventos(marca, inicio)
        cr = self.env.cr
        for parada, (entrega, p) in zip(ruta.stop_ids.sorted('sequence'), paradas):
            llegada, cierre = _ts(p['llegada']), _ts(p['cierre'])
            parada.action_marcar_llegada()
            marca = self._fechar_eventos(marca, llegada, entrega.latitude, entrega.longitude)
            if p.get('resultado') == 'no_entregado':
                parada.action_marcar_no_entregado(p.get('motivo') or 'other')
            else:
                parada.action_marcar_entregado()
            marca = self._fechar_eventos(marca, cierre, entrega.latitude, entrega.longitude)
            self.env.flush_all()
            cr.execute('UPDATE logistica_ruta_parada SET actual_arrival_at = %s, completed_at = %s WHERE id = %s',
                       (llegada, cierre, parada.id))
        ruta.action_cerrar()
        marca = self._fechar_eventos(marca, fin)
        self.env.flush_all()
        cr.execute(
            """UPDATE logistica_ruta SET confirmed_load_at = %s, started_at = %s, finished_at = %s, create_date = %s
               WHERE id = %s""", (carga, inicio, fin, carga - timedelta(minutes=MIN_PREPARADO), ruta.id))
        return len(paradas)

    # ------------------------------------------------------------------ API
    @api.model
    def registrar_dia(self, datos):
        """datos = {'pedidos': [...], 'rutas': [...]} (fechas UTC 'AAAA-MM-DD HH:MM:SS'). Devuelve conteos.

        pedido: ref, partner_id, lat, lon, fecha, lineas [[product_id, cantidad], ...]
        ruta:   clave, vehicle_id, driver_id, fecha (AAAA-MM-DD), carga, inicio, fin, km, min,
                paradas [{ref, llegada, cierre, resultado ('entregado'|'no_entregado'), motivo}]
        """
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Solo un administrador puede registrar el histórico de demostración.'))
        if not isinstance(datos, dict):
            raise UserError(_('Datos del día no válidos.'))
        conteo = {'pedidos_creados': 0, 'pedidos_omitidos': 0, 'rutas_creadas': 0, 'rutas_omitidas': 0,
                  'paradas': 0}
        for p in datos.get('pedidos') or []:
            if self._registrar_pedido(p):
                conteo['pedidos_creados'] += 1
            else:
                conteo['pedidos_omitidos'] += 1
        for r in datos.get('rutas') or []:
            n = self._registrar_ruta(r)
            if n:
                conteo['rutas_creadas'] += 1
                conteo['paradas'] += n
            else:
                conteo['rutas_omitidas'] += 1
        self.env.invalidate_all()
        return conteo
