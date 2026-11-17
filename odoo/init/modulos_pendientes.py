"""Módulos propios (logistica_*) instalados cuya versión en el código no coincide con la de la base.

Imprime la lista separada por comas (vacía si no hay nada que actualizar). La usa odoo-init.sh para aplicar
cambios de código en cada despliegue sin reinstalar todo.
"""
import ast
import os
import sys
from pathlib import Path

import psycopg2

ADDONS = Path('/mnt/extra-addons')


def version_codigo(modulo):
    manifiesto = ADDONS / modulo / '__manifest__.py'
    if not manifiesto.is_file():
        return None
    return ast.literal_eval(manifiesto.read_text(encoding='utf-8')).get('version')


def main():
    conexion = psycopg2.connect(host='db', port=5432, user='odoo', password=os.environ['PASSWORD'],
                                dbname=os.environ.get('ODOO_DB') or 'logistica_dev')
    with conexion, conexion.cursor() as cr:
        cr.execute("SELECT name, latest_version FROM ir_module_module "
                   "WHERE name LIKE 'logistica\\_%%' AND state = 'installed'")
        instalados = cr.fetchall()
    conexion.close()
    pendientes = []
    for nombre, instalada in instalados:
        codigo = version_codigo(nombre)
        # Odoo guarda la versión completa (16.0.x.y.z); el manifiesto puede traerla corta (x.y.z).
        if codigo and instalada and not instalada.endswith(codigo):
            pendientes.append(nombre)
    print(','.join(sorted(pendientes)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
