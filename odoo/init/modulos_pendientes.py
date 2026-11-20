"""Módulos propios (logistica_*) instalados cuya versión en el código no coincide con la de la base.

Imprime la lista separada por comas (vacía si no hay nada que actualizar). La usa odoo-init.sh para aplicar
cambios de código en cada despliegue sin reinstalar todo.

Con `--faltantes "<lista>"` imprime, en cambio, los módulos propios de esa lista (la de odoo-init.sh) que la base
todavía no tiene instalados: así un módulo nuevo (p. ej. logistica_tablero) se instala en un servidor existente.
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


def _conectar():
    return psycopg2.connect(host='db', port=5432, user='odoo', password=os.environ['PASSWORD'],
                            dbname=os.environ.get('ODOO_DB') or 'logistica_dev')


def faltantes(lista):
    propios = [m.strip() for m in lista.split(',') if m.strip().startswith('logistica_')]
    conexion = _conectar()
    with conexion, conexion.cursor() as cr:
        cr.execute("SELECT name FROM ir_module_module WHERE state = 'installed' AND name = ANY(%s)", (propios,))
        instalados = {fila[0] for fila in cr.fetchall()}
    conexion.close()
    # Solo los que existen en el código (un módulo borrado del repo no se intenta instalar).
    return [m for m in propios if m not in instalados and version_codigo(m) is not None]


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--faltantes':
        print(','.join(faltantes(sys.argv[2])))
        return 0
    conexion = _conectar()
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
