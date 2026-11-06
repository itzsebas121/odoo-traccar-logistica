# -*- coding: utf-8 -*-
"""Mueve la contraseña de traccar.server (columna almacenada antigua) a traccar.server.clave (F1-R24).

Corre en la etapa post, cuando la tabla traccar_server_clave ya existe. Por cada servidor con valor:
- sin clave nueva: copia el valor y anula la columna antigua;
- con la misma clave nueva: anula la columna antigua;
- con una clave nueva distinta: no toca nada, para no perder el valor antiguo.
Solo se registran conteos, nunca el valor.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _columna_existe(cr, tabla, columna):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (tabla, columna))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _columna_existe(cr, 'traccar_server', 'password'):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Clave = env['traccar.server.clave']
    cr.execute("SELECT id, password FROM traccar_server WHERE password IS NOT NULL AND password <> ''")
    copiadas, conflictos = 0, 0
    for server_id, secreto in cr.fetchall():
        clave = Clave.search([('server_id', '=', server_id)], limit=1)
        if clave and clave.password != secreto:
            conflictos += 1
            continue
        if not clave:
            Clave.create({'server_id': server_id, 'password': secreto})
            copiadas += 1
        cr.execute("UPDATE traccar_server SET password = NULL WHERE id = %s", (server_id,))
    _logger.info('traccar_migracion_clave copiadas=%s conflictos=%s', copiadas, conflictos)
