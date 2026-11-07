# -*- coding: utf-8 -*-
import json

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..models.logistica_prediccion_consulta import etiqueta_zona


class MapaPrediccionController(http.Controller):

    @http.route('/logistica/prediccion/<int:consulta_id>/mapa', type='http', auth='user')
    def mapa(self, consulta_id, **kwargs):
        if not request.env.user.has_group('fleet.fleet_group_user'):
            raise Forbidden()
        consulta = request.env['logistica.prediccion.consulta'].browse(consulta_id)
        try:
            if not consulta.exists():
                raise NotFound()
            geometria = json.loads(consulta.route_geometry or '[]')
        except AccessError:
            raise Forbidden()
        except ValueError:
            geometria = []
        return request.render('logistica_analitica_ia.mapa_pagina', {
            'consulta': consulta,
            'geometria': json.dumps(geometria),
            'origen': etiqueta_zona(consulta.origin_zone),
            'destino': etiqueta_zona(consulta.predicted_zone),
        })
