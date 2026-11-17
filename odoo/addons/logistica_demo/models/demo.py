# -*- coding: utf-8 -*-
"""Carga del mercado de demostración. Lo llama seeds/seed.py por XML-RPC con los datos de seeds/data.

Todo es idempotente: productos por código, clientes por referencia, pedidos por referencia del cliente
(``client_order_ref``) y el historial por días ya procesados. El historial se procesa por lotes de días para no
superar el tiempo máximo de una petición de Odoo.
"""
import math
import random
from datetime import date, datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

TZ_OFFSET = timedelta(hours=5)          # Ecuador continental: UTC-5, sin horario de verano
PARAM_HASTA = 'logistica_demo.historial_hasta'
PARAM_DESPLAZAMIENTO = 'logistica_demo.historial_desplazamiento_dias'
PARAM_MODELO = 'logistica_demo.modelo_cobro'
MODELO_COBRO = 'contado'                 # venta directa: se paga al pedir; no hay crédito ni cuentas por cobrar
PARAM_VERSION = 'logistica_demo.version_datos'
PREFIJO_HISTORIAL = 'H-'
PREFIJOS_DEMO = ('H-', 'HOY-')            # pedidos que genera la demo (historial y pedidos de hoy)
FACTOR_VIAL = 1.35                       # distancia por calle frente a la recta


def _km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _utc(dia, hora_local):
    """Fecha local + hora decimal (9.5 = 09:30) → datetime UTC sin zona (formato de Odoo)."""
    return datetime.combine(dia, time()) + timedelta(hours=hora_local) + TZ_OFFSET


def _rumbo(origen, punto):
    return math.atan2(punto[1] - origen[1], punto[0] - origen[0])


class LogisticaDemo(models.AbstractModel):
    _name = 'logistica.demo'
    _description = 'Carga de datos de demostración'

    # ------------------------------------------------------------------ acceso
    def _env(self):
        if not (self.env.su or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Solo un administrador puede cargar los datos de demostración.'))
        return self.sudo().with_context(tracking_disable=True, mail_create_nolog=True, mail_notrack=True,
                                        mail_create_nosubscribe=True, lang='es_EC').env

    # ------------------------------------------------------------------ mercado
    @api.model
    def cargar_mercado(self, datos, productos):
        """Empresa, contabilidad (USD, plan contable, IVA), categorías, productos, clientes y cobertura."""
        env = self._env()
        resumen = {}
        self._empresa(env, datos['empresa'])
        impuestos = self._contabilidad(env)
        categorias = self._categorias(env, datos['categorias'])
        resumen['productos'] = self._productos(env, productos, categorias, impuestos)
        resumen['clientes'] = self._clientes(env, datos['clientes'])
        config = env['logistica.configuracion'].get_config()
        if 'coverage_radius_km' in config._fields and datos.get('cobertura_km'):
            config.coverage_radius_km = datos['cobertura_km']
        resumen['retirados'] = self._retirar(env, datos.get('retirar') or {})
        return resumen

    @api.model
    def productos_sin_imagen(self, codigos):
        env = self._env()
        plantillas = env['product.template'].with_context(active_test=False).search([('default_code', 'in', codigos)])
        return [p.default_code for p in plantillas if not p.image_1920]

    @api.model
    def poner_imagen(self, codigo, imagen_b64):
        env = self._env()
        plantilla = env['product.template'].with_context(active_test=False).search(
            [('default_code', '=', codigo)], limit=1)
        if not plantilla:
            raise UserError(_('No existe el producto %s.') % codigo)
        if not plantilla.image_1920:
            plantilla.image_1920 = imagen_b64
        return True

    @api.model
    def poner_logo(self, logo_b64):
        """Logo de la empresa y del sitio web (la tienda mostraba una imagen rota)."""
        env = self._env()
        env.company.logo = logo_b64
        env['website'].search([]).write({'logo': logo_b64})
        return True

    def _empresa(self, env, datos):
        empresa = env.company
        pais = env['res.country'].search([('code', '=', datos['pais'])], limit=1)
        provincia = env['res.country.state'].search(
            [('country_id', '=', pais.id), ('name', '=', datos['provincia'])], limit=1)
        empresa.write({
            'name': datos['name'], 'street': datos['street'], 'city': datos['city'], 'zip': datos.get('zip'),
            'country_id': pais.id, 'state_id': provincia.id, 'phone': datos.get('phone'),
            'email': datos.get('email'), 'website': datos.get('website'),
        })
        env['website'].search([]).write({'name': datos['name']})

    def _contabilidad(self, env):
        empresa = env.company
        usd = env.ref('base.USD')
        if not usd.active:
            usd.active = True
        if not env['account.journal'].search_count([('company_id', '=', empresa.id)]):
            if empresa.currency_id != usd:
                empresa.currency_id = usd
            env.ref('l10n_generic_coa.configurable_chart_template').try_loading(company=empresa, install_demo=False)
        env['product.pricelist'].with_context(active_test=False).search(
            [('company_id', 'in', [empresa.id, False]), ('currency_id', '!=', usd.id)]).write({'currency_id': usd.id})
        Impuesto = env['account.tax'].with_context(active_test=False)

        def iva(nombre, monto):
            tax = Impuesto.search([('name', '=', nombre), ('company_id', '=', empresa.id),
                                   ('type_tax_use', '=', 'sale')], limit=1)
            if not tax:
                base = Impuesto.search([('type_tax_use', '=', 'sale'), ('company_id', '=', empresa.id),
                                        ('amount_type', '=', 'percent')], limit=1)
                if not base:
                    raise UserError(_('El plan contable no tiene un impuesto de venta para copiar.'))
                tax = base.copy({'name': nombre, 'amount': monto, 'description': nombre,
                                 'price_include': True, 'include_base_amount': False, 'active': True})
            return tax

        impuestos = {0: iva('IVA 0%', 0.0), 15: iva('IVA 15%', 15.0)}
        empresa.account_sale_tax_id = impuestos[0]
        return impuestos

    def _categorias(self, env, nombres):
        raiz = env['product.category'].search([('name', '=', 'Mercado'), ('parent_id', '=', False)], limit=1) \
            or env['product.category'].create({'name': 'Mercado'})
        salida = {}
        for nombre in nombres:
            interna = env['product.category'].search([('name', '=', nombre), ('parent_id', '=', raiz.id)], limit=1) \
                or env['product.category'].create({'name': nombre, 'parent_id': raiz.id})
            web = env['product.public.category'].search([('name', '=', nombre)], limit=1) \
                or env['product.public.category'].create({'name': nombre})
            salida[nombre] = (interna, web)
        return salida

    def _productos(self, env, productos, categorias, impuestos):
        Plantilla = env['product.template'].with_context(active_test=False)
        contador = {'creados': 0, 'actualizados': 0, 'archivados': 0}
        for p in productos:
            interna, web = categorias[p['categoria']]
            valores = {
                'name': p['name'], 'default_code': p['default_code'], 'list_price': p['list_price'],
                'categ_id': interna.id, 'public_categ_ids': [(6, 0, web.ids)], 'detailed_type': 'consu',
                'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'active': True,
                'is_published': True, 'description_sale': p.get('description_sale'),
                'taxes_id': [(6, 0, impuestos[int(p.get('iva') or 0)].ids)],
            }
            plantilla = Plantilla.search([('default_code', '=', p['default_code'])], limit=1)
            if plantilla:
                plantilla.write(valores)
                contador['actualizados'] += 1
            else:
                Plantilla.create(valores)
                contador['creados'] += 1
        # Lo que estaba en el catálogo de la demo y ya no está: se archiva (no se borra: puede tener ventas).
        raiz = env['product.category'].search([('name', '=', 'Mercado'), ('parent_id', '=', False)], limit=1)
        codigos = [p['default_code'] for p in productos]
        viejos = Plantilla.search([('categ_id', 'child_of', raiz.id), ('default_code', 'not in', codigos),
                                   ('active', '=', True)])
        if viejos:
            viejos.write({'active': False, 'is_published': False, 'public_categ_ids': [(5, 0, 0)], 'categ_id': raiz.id})
            contador['archivados'] = len(viejos)
        actuales = {c[0].id for c in categorias.values()}
        sobrantes = env['product.category'].search([('parent_id', '=', raiz.id), ('id', 'not in', list(actuales))])
        Plantilla.search([('categ_id', 'in', sobrantes.ids)]).write({'categ_id': raiz.id})
        sobrantes.unlink()
        web = {c[1].id for c in categorias.values()}
        env['product.public.category'].search([('id', 'not in', list(web))]).filtered(
            lambda c: not Plantilla.search_count([('public_categ_ids', 'in', c.ids), ('active', '=', True)])).unlink()
        return contador

    def _clientes(self, env, clientes):
        Partner = env['res.partner'].with_context(active_test=False)
        pais = env['res.country'].search([('code', '=', 'EC')], limit=1)
        provincia = env['res.country.state'].search([('country_id', '=', pais.id), ('name', '=', 'Tungurahua')],
                                                    limit=1)
        contador = {'creados': 0, 'actualizados': 0}
        for c in clientes:
            valores = {
                'name': c['name'], 'ref': c['ref'], 'is_company': c['tipo'] == 'empresa',
                'company_type': 'company' if c['tipo'] == 'empresa' else 'person',
                'street': c['calle'], 'street2': c['sector'], 'city': c['ciudad'],
                'country_id': pais.id, 'state_id': provincia.id, 'mobile': c['telefono'], 'phone': c['telefono'],
                'email': c['email'], 'lang': 'es_EC', 'customer_rank': 1, 'active': True,
                'delivery_latitude': c['latitud'] or 0.0, 'delivery_longitude': c['longitud'] or 0.0,
                'delivery_zone': c.get('zona') or 'otra',
            }
            partner = Partner.search([('ref', '=', c['ref'])], limit=1)
            if partner:
                partner.write(valores)
                contador['actualizados'] += 1
            else:
                partner = Partner.create(valores)
                contador['creados'] += 1
            if partner.property_payment_term_id:
                partner.property_payment_term_id = False   # venta directa: pago inmediato
        return contador

    def _retirar(self, env, retirar):
        """Quita los datos de la demo anterior (productos genéricos, pedidos sin despachar y sus clientes)."""
        contador = {'productos': 0, 'pedidos': 0, 'clientes': 0}
        viejos = env['product.template'].search([('name', 'in', retirar.get('productos') or [])])
        if viejos:
            viejos.write({'active': False, 'is_published': False})
            contador['productos'] = len(viejos)
        pedidos = env['sale.order'].search([('client_order_ref', 'in', retirar.get('pedidos') or [])])
        for pedido in pedidos:
            entregas = pedido.logistica_entrega_ids
            if any(e.state not in ('pendiente_preparacion', 'en_preparacion', 'preparado') for e in entregas):
                continue
            paradas = env['logistica.ruta.parada'].search([('entrega_id', 'in', entregas.ids)])
            if paradas:
                continue
            if entregas:
                # Los eventos son auditoría inmutable por ORM; aquí se borran los de la demo anterior.
                env.cr.execute('DELETE FROM logistica_entrega_evento WHERE entrega_id IN %s', (tuple(entregas.ids),))
                env['logistica.entrega.evento'].invalidate_model()
            entregas.unlink()
            pedido._action_cancel()
            pedido.unlink()
            contador['pedidos'] += 1
        for nombre in retirar.get('clientes') or []:
            partner = env['res.partner'].search([('name', '=', nombre)], limit=1)
            if partner and not env['sale.order'].search_count([('partner_id', '=', partner.id)]):
                try:
                    with env.cr.savepoint():
                        partner.unlink()
                except Exception:  # noqa: BLE001 - si algo lo referencia, se archiva
                    partner.active = False
                contador['clientes'] += 1
        return contador

    # ------------------------------------------------------------------ historial
    @api.model
    def cargar_historial(self, datos, max_dias=6):
        """Procesa los siguientes ``max_dias`` días de reparto. Devuelve {'procesados', 'pendientes'}."""
        env = self._env()
        icp = env['ir.config_parameter']
        version = str(datos.get('version_datos') or 1)
        if icp.get_param(PARAM_HASTA) and (icp.get_param(PARAM_MODELO) != MODELO_COBRO
                                           or icp.get_param(PARAM_VERSION) != version):
            # Historial de una versión anterior (otro catálogo o modelo de cobro): se borra en esta llamada y se
            # regenera en las siguientes (cada llamada debe terminar antes del límite de tiempo de una petición).
            borrado = self.reiniciar_historial()
            icp.set_param(PARAM_MODELO, MODELO_COBRO)
            icp.set_param(PARAM_VERSION, version)
            return {'procesados': [], 'pendientes': 1, 'reiniciado': borrado}
        icp.set_param(PARAM_MODELO, MODELO_COBRO)
        icp.set_param(PARAM_VERSION, version)
        params = datos['historial']
        desplazamiento = icp.get_param(PARAM_DESPLAZAMIENTO)
        if not desplazamiento:
            # El historial termina ayer: se desplaza por semanas completas para conservar los días de la semana.
            ayer = fields.Date.context_today(self) - timedelta(days=1)
            hasta = date.fromisoformat(params['hasta'])
            desplazamiento = str(max(0, (ayer - hasta).days // 7 * 7))
            icp.set_param(PARAM_DESPLAZAMIENTO, desplazamiento)
        desplazamiento = timedelta(days=int(desplazamiento))
        desde = date.fromisoformat(params['desde']) + desplazamiento
        hasta = date.fromisoformat(params['hasta']) + desplazamiento
        hecho = icp.get_param(PARAM_HASTA)
        hecho = date.fromisoformat(hecho) if hecho else None
        dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
        dias = [d for d in dias if d.weekday() != 6 and (hecho is None or d > hecho)]
        lote = dias[:max_dias]
        contexto = {'desplazamiento': desplazamiento, 'hasta': hasta}
        for dia in lote:
            self._dia_historial(env, dia, datos, contexto)
            icp.set_param(PARAM_HASTA, dia.isoformat())
        return {'procesados': [d.isoformat() for d in lote], 'pendientes': len(dias) - len(lote)}

    def _clientes_del_dia(self, dia, datos, contexto, rnd):
        elegidos = []
        segmentos = datos['segmentos']
        inicio = date.fromisoformat(datos['historial']['desde']) + contexto['desplazamiento']
        semana = (dia - inicio).days // 7
        for c in datos['clientes']:
            seg = segmentos.get(c['segmento']) or {}
            if not seg.get('probabilidad') or c.get('latitud') is None:
                continue
            if seg.get('hasta') and dia > date.fromisoformat(seg['hasta']) + contexto['desplazamiento']:
                continue
            if seg.get('desde') and dia < date.fromisoformat(seg['desde']) + contexto['desplazamiento']:
                continue
            if seg.get('diario'):
                toca = True
            else:
                cada = seg.get('cada_semanas') or 1
                desfase = sum(map(ord, c['ref'])) % cada
                toca = dia.weekday() == c['dia_preferido'] and semana % cada == desfase
            if toca and rnd.random() < seg['probabilidad']:
                elegidos.append(c)
        return elegidos

    def _lineas(self, cliente, datos, productos, rnd):
        perfil = datos['perfiles'][cliente['perfil']]
        codigos = list(perfil['productos'])
        pesos = [perfil['productos'][k] for k in codigos]
        cuantas = rnd.randint(*perfil['lineas'])
        elegidos = []
        while len(elegidos) < min(cuantas, len(codigos)):
            codigo = rnd.choices(codigos, weights=pesos)[0]
            if codigo not in elegidos:
                elegidos.append(codigo)
        lineas = [(0, 0, {'product_id': productos[k].id, 'product_uom_qty': rnd.randint(*perfil['cantidad'])})
                  for k in elegidos if k in productos]
        extras = perfil.get('extras')
        if extras and rnd.random() < extras['probabilidad']:
            codigos_extra = list(extras['productos'])
            codigo = rnd.choices(codigos_extra, weights=[extras['productos'][k] for k in codigos_extra])[0]
            if codigo in productos and codigo not in elegidos:
                lineas.append((0, 0, {'product_id': productos[codigo].id,
                                      'product_uom_qty': rnd.randint(*extras['cantidad'])}))
        return lineas

    def _dia_historial(self, env, dia, datos, contexto):
        params = datos['historial']
        rnd = random.Random(f"{params['semilla']}-{dia.isoformat()}")
        productos = {p.default_code: p for p in env['product.product'].search([('default_code', '!=', False)])}
        partners = {p.ref: p for p in env['res.partner'].search([('ref', 'like', 'CLI-')])}
        dia_pedido = dia - timedelta(days=2 if dia.weekday() == 0 else 1)
        Entrega = env['logistica.entrega']
        Evento = env['logistica.entrega.evento']
        primer_evento = Evento.search([], order='id desc', limit=1).id or 0

        # 1) Pedidos del día anterior (los de hoy se reparten hoy).
        horas_pedido = {}
        nuevos = Entrega
        for n, cliente in enumerate(self._clientes_del_dia(dia, datos, contexto, rnd), start=1):
            referencia = f'{PREFIJO_HISTORIAL}{dia:%Y%m%d}-{n:02d}'
            if env['sale.order'].search_count([('client_order_ref', '=', referencia)]):
                continue
            partner = partners.get(cliente['ref'])
            lineas = self._lineas(cliente, datos, productos, rnd)
            if not partner or not lineas:
                continue
            hora = _utc(dia_pedido, rnd.uniform(8.0, 21.0))
            pedido = env['sale.order'].create({
                'partner_id': partner.id, 'client_order_ref': referencia, 'order_line': lineas,
                'delivery_latitude': cliente['latitud'], 'delivery_longitude': cliente['longitud'],
                'delivery_zone': cliente.get('zona') or 'otra',
            })
            pedido.action_confirm()
            pedido.write({'date_order': hora})
            self._fechar(env, 'sale_order', pedido.ids, hora)
            self._fechar_mensajes(env, 'sale.order', pedido.ids, hora)
            self._facturar_y_cobrar(env, pedido, dia_pedido, hora + timedelta(minutes=2), rnd)
            entrega = pedido.logistica_entrega_ids[:1]
            if entrega.state == 'en_preparacion':
                entrega.action_marcar_preparado()
            self._fechar(env, 'logistica_entrega', entrega.ids, hora)
            horas_pedido[entrega.id] = hora
            nuevos |= entrega

        # 2) Entregas reprogramadas de días anteriores (segundo intento).
        rutas_activas = env['logistica.ruta.parada'].search(
            [('route_id.state', 'in', ('borrador', 'planificada', 'carga_confirmada', 'en_recorrido'))]).entrega_id
        reprogramadas = Entrega.search([
            ('state', '=', 'preparado'), ('sale_order_id.client_order_ref', '=like', PREFIJO_HISTORIAL + '%'),
            ('id', 'not in', nuevos.ids), ('id', 'not in', rutas_activas.ids)])
        entregas = nuevos | reprogramadas
        if not entregas:
            return

        # 3) Rutas: barrido por rumbo desde la sede, orden por vecino más cercano.
        bodega = env['logistica.bodega'].get_bodega_activa()
        sede = (bodega.latitude, bodega.longitude)
        vehiculos = env['fleet.vehicle'].search([('driver_id', '!=', False)], order='license_plate')
        if not vehiculos:
            raise UserError(_('No hay vehículos con conductor para el historial.'))
        ordenadas = sorted(entregas, key=lambda e: _rumbo(sede, (e.latitude, e.longitude)))
        n_rutas = min(len(vehiculos), max(1, math.ceil(len(ordenadas) / params['paradas_por_ruta'])))
        tam = math.ceil(len(ordenadas) / n_rutas)
        grupos = [ordenadas[i:i + tam] for i in range(0, len(ordenadas), tam)]
        motivos = list(params['motivos_no_entrega'])
        pesos_motivo = [params['motivos_no_entrega'][m] for m in motivos]
        entregadas = Entrega
        tiempos = {}  # entrega_id -> dict de horas por tipo de evento

        for vehiculo, grupo in zip(vehiculos, grupos):
            secuencia, actual, pendientes = [], sede, list(grupo)
            while pendientes:
                siguiente = min(pendientes, key=lambda e: _km(actual, (e.latitude, e.longitude)))
                pendientes.remove(siguiente)
                secuencia.append(siguiente)
                actual = (siguiente.latitude, siguiente.longitude)
            ruta = env['logistica.ruta'].create({
                'date': dia, 'bodega_id': bodega.id, 'vehicle_id': vehiculo.id, 'driver_id': vehiculo.driver_id.id,
                'optimization_version': 'historial-demo', 'distance_source': 'estimado_haversine',
                'stop_ids': [(0, 0, {'entrega_id': e.id, 'sequence': i}) for i, e in enumerate(secuencia, start=1)],
            })
            salida = _utc(dia, params['hora_salida'] + rnd.uniform(0, 0.5))
            asignado = salida - timedelta(minutes=rnd.randint(60, 90))
            carga = salida - timedelta(minutes=rnd.randint(15, 30))
            ruta.action_aprobar_plan()
            ruta.action_confirmar_carga()
            ruta.action_iniciar_recorrido()
            hora, actual, km_total = salida, sede, 0.0
            for parada in ruta.stop_ids.sorted('sequence'):
                entrega = parada.entrega_id
                destino = (entrega.latitude, entrega.longitude)
                tramo = _km(actual, destino) * FACTOR_VIAL
                km_total += tramo
                llegada = hora + timedelta(hours=tramo / params['velocidad_kmh'])
                fin = llegada + timedelta(minutes=params['minutos_por_parada'] + rnd.uniform(-2, 3))
                parada.action_marcar_llegada()
                intentos = len(entrega.event_ids.filtered(lambda ev: ev.event_type == 'no_entregado'))
                if intentos == 0 and rnd.random() < params['probabilidad_no_entrega']:
                    motivo = rnd.choices(motivos, weights=pesos_motivo)[0]
                    parada.action_marcar_no_entregado(motivo, _('Registrado por el conductor.'))
                else:
                    parada.action_marcar_entregado()
                    entregadas |= entrega
                parada.write({'actual_arrival_at': llegada, 'arrival_candidate_at': llegada - timedelta(minutes=1),
                              'completed_at': fin})
                tiempos[entrega.id] = {
                    'asignado': asignado, 'carga_confirmada': carga, 'inicio_recorrido': salida,
                    'llegada_registrada': llegada, 'entregado': fin, 'no_entregado': fin, 'destino': destino}
                hora, actual = fin, destino
            regreso = _km(actual, sede) * FACTOR_VIAL
            km_total += regreso
            cierre = hora + timedelta(hours=regreso / params['velocidad_kmh'])
            if ruta.state == 'en_recorrido':
                ruta.action_cerrar()
            ruta.write({'confirmed_load_at': carga, 'started_at': salida, 'finished_at': cierre,
                        'planned_distance_km': round(km_total, 2),
                        'planned_duration_min': round((cierre - salida).total_seconds() / 60, 1)})
            self._fechar(env, 'logistica_ruta', ruta.ids, asignado)
            for parada in ruta.stop_ids:
                tiempos[parada.entrega_id.id]['cierre'] = cierre
            # Lo no entregado: segundo intento al día siguiente, o vuelve a bodega si la dirección está mal.
            # Pedido ya pagado: lo que falló se vuelve a intentar al día siguiente (sin devoluciones).
            for parada in ruta.stop_ids.filtered(lambda p: p.state == 'no_entregado'):
                if parada.entrega_id.state == 'pendiente_reprogramacion':
                    parada.entrega_id.action_reprogramar()

        self._fechar_eventos(env, primer_evento, horas_pedido, tiempos, sede)

    # ------------------------------------------------------------------ factura y cobro al pedir
    def _facturar_y_cobrar(self, env, pedido, fecha, cuando, rnd=None):
        """Venta directa: el pedido se paga al hacerlo (transferencia o tarjeta; a veces efectivo en mostrador)."""
        if pedido.invoice_ids.filtered(lambda f: f.state == 'posted'):
            return
        diarios = env['account.journal'].search([('type', 'in', ('bank', 'cash')), ('company_id', '=', env.company.id)])
        banco = diarios.filtered(lambda d: d.type == 'bank')[:1]
        caja = diarios.filtered(lambda d: d.type == 'cash')[:1]
        diario = caja if (caja and rnd and rnd.random() < 0.15) else (banco or caja)
        factura = pedido._create_invoices(final=True)
        factura.write({'invoice_date': fecha, 'date': fecha, 'invoice_payment_term_id': False})
        factura.with_context(skip_auto_pago_directo=True).action_post()
        self._fechar(env, 'account_move', factura.ids, cuando)
        self._fechar_mensajes(env, 'account.move', factura.ids, cuando)
        if diario:
            pagos = env['account.payment.register'].with_context(
                active_model='account.move', active_ids=factura.ids).create(
                    {'payment_date': fecha, 'journal_id': diario.id})._create_payments()
            self._fechar(env, 'account_payment', pagos.ids, cuando)
            self._fechar(env, 'account_move', pagos.move_id.ids, cuando)

    @api.model
    def reiniciar_historial(self):
        """Borra el historial de demostración (pedidos H-*, sus facturas, pagos, entregas y rutas) para regenerarlo."""
        env = self._env()
        dominio = ['|'] * (len(PREFIJOS_DEMO) - 1) + [('client_order_ref', '=like', p + '%') for p in PREFIJOS_DEMO]
        pedidos = env['sale.order'].search(dominio)
        facturas = pedidos.invoice_ids
        pagos = facturas._get_reconciled_payments()
        if pagos:
            pagos.action_draft()
            pagos.with_context(force_delete=True).unlink()
        if facturas:
            facturas.filtered(lambda f: f.state != 'draft').button_draft()
            facturas.with_context(force_delete=True).unlink()
        entregas = pedidos.logistica_entrega_ids
        paradas = env['logistica.ruta.parada'].search([('entrega_id', 'in', entregas.ids)])
        rutas = paradas.route_id
        if rutas:
            # Rutas cerradas: solo se pueden borrar durante una desinstalación; aquí se borra demo sintética.
            rutas.with_context(module_uninstall=True).unlink()
        if entregas:
            env.cr.execute('DELETE FROM logistica_entrega_evento WHERE entrega_id IN %s', (tuple(entregas.ids),))
            env['logistica.entrega.evento'].invalidate_model()
            entregas.unlink()
        for pedido in pedidos:
            pedido._action_cancel()
        pedidos.unlink()
        icp = env['ir.config_parameter']
        for clave in (PARAM_HASTA, PARAM_DESPLAZAMIENTO):
            icp.set_param(clave, False)
        return {'pedidos': len(pedidos), 'facturas': len(facturas), 'pagos': len(pagos), 'rutas': len(rutas)}

    # ------------------------------------------------------------------ fechas reales
    def _fechar(self, env, tabla, ids, cuando):
        if ids:
            env.cr.execute(f'UPDATE {tabla} SET create_date = %s, write_date = %s WHERE id IN %s',
                           (cuando, cuando, tuple(ids)))

    def _fechar_mensajes(self, env, modelo, ids, cuando):
        if ids:
            env.cr.execute('UPDATE mail_message SET date = %s, create_date = %s WHERE model = %s AND res_id IN %s',
                           (cuando, cuando, modelo, tuple(ids)))

    def _fechar_eventos(self, env, primer_evento, horas_pedido, tiempos, sede):
        """Pone a cada evento nuevo la hora en que habría ocurrido y la posición GPS correspondiente.

        Los eventos son auditoría y el ORM no deja tocarlos; como esto es historia sintética de la demo, se
        ajustan por SQL (solo los eventos creados durante este día de historial)."""
        Evento = env['logistica.entrega.evento']
        eventos = Evento.search([('id', '>', primer_evento)], order='id')
        sin_gps = eventos.filtered(lambda ev: ev.event_type == 'gps_no_disponible')
        if sin_gps:
            env.cr.execute('DELETE FROM logistica_entrega_evento WHERE id IN %s', (tuple(sin_gps.ids),))
        for ev in eventos - sin_gps:
            t = tiempos.get(ev.entrega_id.id, {})
            if ev.event_type in ('creado', 'preparado'):
                cuando = horas_pedido.get(ev.entrega_id.id)
                if cuando and ev.event_type == 'preparado':
                    cuando += timedelta(minutes=45)
            elif ev.event_type in ('reprogramado', 'devuelto_bodega'):
                cuando = t.get('cierre') and t['cierre'] + timedelta(minutes=10)
            else:
                cuando = t.get(ev.event_type)
            if not cuando:
                continue
            gps = None
            if ev.event_type == 'inicio_recorrido':
                gps = (sede[0], sede[1], 5)
            elif ev.event_type in ('llegada_registrada', 'entregado', 'no_entregado') and t.get('destino'):
                gps = (t['destino'][0] + 0.00004, t['destino'][1] - 0.00003, 8)
            if gps:
                env.cr.execute(
                    'UPDATE logistica_entrega_evento SET event_time = %s, create_date = %s, gps_available = TRUE, '
                    'gps_latitude = %s, gps_longitude = %s, gps_time = %s, gps_age_seconds = %s WHERE id = %s',
                    (cuando, cuando, gps[0], gps[1], cuando, gps[2], ev.id))
            else:
                env.cr.execute('UPDATE logistica_entrega_evento SET event_time = %s, create_date = %s WHERE id = %s',
                               (cuando, cuando, ev.id))
        Evento.invalidate_model()

    # ------------------------------------------------------------------ pedidos de hoy
    @api.model
    def cargar_pedidos_hoy(self, pedidos):
        """Pedidos del día para despachar. Sin ubicación quedan en cotización (no se pueden confirmar)."""
        env = self._env()
        productos = {p.default_code: p for p in env['product.product'].search([('default_code', '!=', False)])}
        resumen = {'creados': [], 'existentes': [], 'sin_ubicacion': []}
        hoy = fields.Date.context_today(self)
        for p in pedidos:
            existente = env['sale.order'].search([('client_order_ref', '=', p['ref'])], limit=1)
            if existente:
                if existente.state == 'sale':
                    self._facturar_y_cobrar(env, existente, hoy, fields.Datetime.now())
                resumen['existentes'].append(p['ref'])
                continue
            partner = env['res.partner'].search([('ref', '=', p['cliente_ref'])], limit=1)
            if not partner:
                raise UserError(_('No existe el cliente %s.') % p['cliente_ref'])
            valores = {
                'partner_id': partner.id, 'client_order_ref': p['ref'],
                'order_line': [(0, 0, {'product_id': productos[l['producto']].id, 'product_uom_qty': l['cantidad']})
                               for l in p['lineas']],
            }
            if p.get('latitud') is not None:
                valores.update(delivery_latitude=p['latitud'], delivery_longitude=p['longitud'],
                               delivery_zone=partner.delivery_zone or 'otra')
            pedido = env['sale.order'].create(valores)
            if p.get('latitud') is None:
                resumen['sin_ubicacion'].append(p['ref'])
                continue
            pedido.action_confirm()
            self._facturar_y_cobrar(env, pedido, hoy, fields.Datetime.now())
            resumen['creados'].append(p['ref'])
        return resumen
