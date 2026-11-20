# -*- coding: utf-8 -*-
"""Repara los Tableros de Odoo (spreadsheet.dashboard) cuyo JSON se perdio del filestore.

Se ejecuta dentro de `odoo shell` (lo llama odoo-init.sh en cada arranque; `env` ya existe):
    odoo shell -d <base> --no-http < reparar_tableros.py

Por que: el JSON de cada tablero (Sales, Product, Invoicing...) es un adjunto en el filestore. Si el archivo no
existe (instalacion hecha sin el volumen de datos, restauracion de un .dump sin filestore), Odoo lo entrega vacio y el
navegador falla con "Unexpected end of JSON input". Para cada tablero vacio o ilegible se vuelve a leer el archivo
`file=` del XML de datos del modulo que lo define y se guarda de nuevo. Solo toca tableros danados. Tambien informa
cuantos adjuntos del filestore faltan (no los toca: solo un respaldo con filestore los recupera).
"""
import base64
import json
import os

from lxml import etree

from odoo.modules.module import get_manifest, get_module_path


def _json_valido(contenido):
    try:
        json.loads(base64.b64decode(contenido or b"") or b"")
        return True
    except ValueError:
        return False


def _archivo_original(modulo, xmlid):
    """Ruta del JSON con que el modulo define el tablero (atributo file= del campo data), o None."""
    ruta_modulo = get_module_path(modulo)
    if not ruta_modulo:
        return None
    for datos in get_manifest(modulo).get("data", []):
        if not datos.endswith(".xml"):
            continue
        try:
            arbol = etree.parse(os.path.join(ruta_modulo, datos))
        except (OSError, etree.XMLSyntaxError):
            continue
        for campo in arbol.xpath("//record[@id=$id]/field[@name='data'][@file]", id=xmlid):
            archivo = campo.get("file")            # "modulo/data/files/x.json", relativo a la carpeta de addons
            ruta = os.path.join(os.path.dirname(ruta_modulo), archivo)
            if os.path.isfile(ruta):
                return ruta
    return None


def reparar(env):
    if "spreadsheet.dashboard" not in env:
        print("reparar_tableros: la app Tableros no esta instalada; nada que hacer.")
        return 0
    reparados, sin_origen = [], []
    tableros = env["spreadsheet.dashboard"].sudo().with_context(active_test=False, bin_size=False).search([])
    for tablero in tableros:
        if _json_valido(tablero.data):
            continue
        datos = env["ir.model.data"].sudo().search([("model", "=", "spreadsheet.dashboard"),
                                                     ("res_id", "=", tablero.id)], limit=1)
        ruta = _archivo_original(datos.module, datos.name) if datos else None
        if not ruta:
            sin_origen.append(tablero.name)
            continue
        with open(ruta, "rb") as f:
            tablero.data = base64.b64encode(f.read())
        reparados.append(tablero.name)
    env.cr.commit()
    print("reparar_tableros: %d tableros, reparados: %s%s" % (
        len(tableros), ", ".join(reparados) or "ninguno",
        "; sin archivo de origen (crearlos de nuevo en Odoo): %s" % ", ".join(sin_origen) if sin_origen else ""))

    # Diagnostico: adjuntos cuyo archivo falta en el filestore.
    adjuntos = env["ir.attachment"].sudo()
    env.cr.execute("SELECT store_fname FROM ir_attachment WHERE store_fname IS NOT NULL")
    faltan = sum(1 for (nombre,) in env.cr.fetchall() if not os.path.isfile(adjuntos._full_path(nombre)))
    if faltan:
        print("reparar_tableros: AVISO: faltan %d archivos de adjuntos en el filestore (%s). Solo un respaldo con "
              "filestore (ZIP de Odoo) los recupera." % (faltan, adjuntos._filestore()))
    return len(reparados)


reparar(env)  # noqa: F821  (env lo define `odoo shell`)
