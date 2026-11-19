"""Aplica ODOO_ADMIN_PASSWORD al usuario administrador de Odoo (base.user_admin).

Solo escribe si la clave guardada no coincide: cambiar el hash cierra las sesiones abiertas del
administrador, asi que no se hace en cada arranque. Vacia o con marcador CAMBIAR_ = no se toca nada.
La clave nunca se imprime.
"""
import os
import sys

import psycopg2
from passlib.context import CryptContext

# Mismo esquema que Odoo 16 (odoo/addons/base/models/res_users.py).
CONTEXTO = CryptContext(['pbkdf2_sha512', 'plaintext'], deprecated=['plaintext'],
                        pbkdf2_sha512__rounds=600_000)


def main():
    clave = (os.environ.get('ODOO_ADMIN_PASSWORD') or '').strip()
    if not clave or clave.startswith('CAMBIAR_'):
        print('admin_password: ODOO_ADMIN_PASSWORD vacia o de marcador; no se cambia la clave de admin.')
        return 0
    conexion = psycopg2.connect(host='db', port=5432, user='odoo', password=os.environ['PASSWORD'],
                                dbname=os.environ.get('ODOO_DB') or 'logistica_dev')
    with conexion, conexion.cursor() as cr:
        cr.execute("""SELECT u.id, COALESCE(u.password, '') FROM res_users u
                      JOIN ir_model_data d ON d.res_id = u.id AND d.model = 'res.users'
                      WHERE d.module = 'base' AND d.name = 'user_admin'""")
        fila = cr.fetchone()
        if not fila:
            print('admin_password: no se encontro base.user_admin; nada que hacer.')
            return 0
        usuario_id, actual = fila
        if actual and CONTEXTO.identify(actual, required=False) and CONTEXTO.verify(clave, actual):
            print('admin_password: la clave de admin ya coincide con ODOO_ADMIN_PASSWORD.')
            return 0
        cr.execute('UPDATE res_users SET password = %s WHERE id = %s',
                   (CONTEXTO.hash(clave, scheme='pbkdf2_sha512'), usuario_id))
    conexion.close()
    print('admin_password: clave de admin actualizada desde ODOO_ADMIN_PASSWORD.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
