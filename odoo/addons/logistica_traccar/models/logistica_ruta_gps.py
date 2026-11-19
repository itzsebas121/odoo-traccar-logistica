# -*- coding: utf-8 -*-
from odoo import fields, models

# Tope de puntos que se envían a un mapa. Traccar Client manda un punto cada pocos segundos; una ruta larga
# se reduce tomando uno de cada N (se conservan siempre el primero y el último).
MAX_PUNTOS_RECORRIDO = 2000


class LogisticaRutaGps(models.Model):
    _inherit = 'logistica.ruta'

    def _recorrido_gps(self):
        """Recorrido real de la ruta: [[lat, lon], ...] en orden de hora del fix.

        Sale de las posiciones que el cron ya guardó en Odoo (logistica.traccar.posicion), no de una consulta a
        Traccar por cada refresco de mapa. La ventana es por vehículo y hora: desde la salida (started_at)
        hasta el cierre o interrupción (finished_at) o, si sigue en recorrido, hasta ahora. Lista vacía si la
        ruta no salió o no tiene vehículo. Lo usan el mapa de monitoreo y el portal del conductor."""
        self.ensure_one()
        ruta = self.sudo()
        if not ruta.started_at or not ruta.vehicle_id:
            return []
        hasta = ruta.finished_at or fields.Datetime.now()
        filas = self.env['logistica.traccar.posicion'].sudo().search_read(
            [('vehicle_id', '=', ruta.vehicle_id.id),
             ('fix_time', '>=', ruta.started_at),
             ('fix_time', '<=', hasta)],
            ['latitude', 'longitude'], order='fix_time asc, id asc')
        puntos = [[f['latitude'], f['longitude']] for f in filas]
        if len(puntos) > MAX_PUNTOS_RECORRIDO:
            paso = -(-len(puntos) // MAX_PUNTOS_RECORRIDO)  # división hacia arriba
            puntos = puntos[::paso] + ([puntos[-1]] if (len(puntos) - 1) % paso else [])
        return puntos
