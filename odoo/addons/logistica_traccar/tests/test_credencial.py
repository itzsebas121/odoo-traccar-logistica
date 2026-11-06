# -*- coding: utf-8 -*-
import base64
import importlib.util
import os
import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

# Script de migración de la versión 16.0.1.1.0. No es un paquete de Python, así que se carga por ruta.
_RUTA_MIGRACION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'migrations', '16.0.1.1.0', 'post-migrar_clave.py')


def _valores(filas):
    return [valor for fila in filas for valor in fila.values()]


@tagged('post_install', '-at_install', 'logistica_traccar')
class TestCredencialTraccar(TransactionCase):
    """La credencial de Traccar solo la ve un gestor de flota; ni lectura, ni agrupación, ni búsqueda la exponen (F1-R24)."""

    def setUp(self):
        super().setUp()
        self.servidor = self.env['traccar.server'].create({'name': 'Servidor de credencial'})
        # Valor generado para cada prueba; no es una credencial real.
        self.secreto = 'clave-%s' % uuid.uuid4().hex
        self.usuario = self._usuario('usuario-credencial-plano')
        self.gestor = self._usuario('usuario-credencial-gestor', 'fleet.fleet_group_manager')

    def _usuario(self, login, *grupos_xmlid):
        ids = [self.env.ref(x).id for x in ('base.group_user',) + grupos_xmlid]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'groups_id': [(6, 0, ids)]})

    def _visibles(self, registro):
        """Valores de password que devuelven read y search_read. Vacío si Odoo rechaza la lectura."""
        valores = []
        lecturas = (
            lambda: registro.read(['password']),
            lambda: registro.search_read([('id', '=', registro.id)], ['password']),
        )
        for lectura in lecturas:
            try:
                valores += _valores(lectura())
            except AccessError:
                pass
        return valores

    # ------------------------------------------------------------------
    # Usuario interno y gestor
    # ------------------------------------------------------------------

    def test_usuario_interno_no_ve_secreto_en_read(self):
        self.servidor.password = self.secreto
        self.assertNotIn(self.secreto, self._visibles(self.servidor.with_user(self.usuario)))

    def test_usuario_interno_no_agrupa_por_secreto(self):
        self.servidor.password = self.secreto
        with self.assertRaises(UserError):
            self.env['traccar.server'].with_user(self.usuario).read_group(
                [], ['id:count'], ['password'])

    def test_usuario_interno_no_busca_por_secreto(self):
        self.servidor.password = self.secreto
        with self.assertRaises(UserError):
            self.env['traccar.server'].with_user(self.usuario).search_count(
                [('password', '=', self.secreto)])

    def test_gestor_de_flota_lee_el_secreto(self):
        self.servidor.password = self.secreto
        leido = self.servidor.with_user(self.gestor).read(['password'])
        self.assertEqual(leido[0]['password'], self.secreto)

    def test_cache_no_filtra_secreto_entre_usuarios(self):
        """El gestor lee primero; el usuario interno no debe recibir el valor desde la caché de la transacción."""
        self.servidor.password = self.secreto
        self.assertEqual(self.servidor.with_user(self.gestor).password, self.secreto)
        self.assertNotIn(self.secreto, self._visibles(self.servidor.with_user(self.usuario)))

    def test_password_no_se_almacena(self):
        """Campo no almacenado: no existe columna que agrupar ni buscar en traccar_server (F1-R24)."""
        self.assertFalse(self.env['traccar.server']._fields['password'].store)

    # ------------------------------------------------------------------
    # Tabla traccar.server.clave
    # ------------------------------------------------------------------

    def test_inverso_escribe_en_traccar_server_clave(self):
        self.servidor.password = self.secreto
        Clave = self.env['traccar.server.clave'].sudo()
        clave = Clave.search([('server_id', '=', self.servidor.id)])
        self.assertEqual(len(clave), 1)
        self.assertEqual(clave.password, self.secreto)
        otro = 'otro-%s' % uuid.uuid4().hex
        self.servidor.password = otro
        self.assertEqual(Clave.search([('server_id', '=', self.servidor.id)]), clave)
        self.assertEqual(clave.password, otro)

    def test_usuario_interno_sin_acceso_a_clave(self):
        Clave = self.env['traccar.server.clave'].with_user(self.usuario)
        with self.assertRaises(AccessError):
            Clave.search([])
        for operacion in ('read', 'write', 'create', 'unlink'):
            self.assertFalse(Clave.check_access_rights(operacion, raise_exception=False), operacion)
        filas = self.env['ir.model.access'].search([
            ('model_id.model', '=', 'traccar.server.clave'),
            ('group_id', '=', self.env.ref('base.group_user').id)])
        self.assertFalse(any(f.perm_read or f.perm_write or f.perm_create or f.perm_unlink for f in filas))

    def test_conector_construye_basic_desde_la_clave(self):
        self.env['traccar.server.clave'].sudo().create({
            'server_id': self.servidor.id, 'password': self.secreto})
        cabeceras = self.servidor.with_user(self.usuario)._get_auth_headers()
        esperada = base64.b64encode(f'{self.servidor.username}:{self.secreto}'.encode('utf-8')).decode('utf-8')
        self.assertEqual(cabeceras['Authorization'], f'Basic {esperada}')

    # ------------------------------------------------------------------
    # Migración de traccar_server.password a traccar.server.clave
    # ------------------------------------------------------------------

    def _migracion(self):
        especificacion = importlib.util.spec_from_file_location('migrar_clave', _RUTA_MIGRACION)
        migracion = importlib.util.module_from_spec(especificacion)
        especificacion.loader.exec_module(migracion)
        return migracion

    def _columna_antigua(self, valor):
        """Base anterior: traccar_server.password era una columna almacenada con el valor viejo."""
        cr = self.env.cr
        cr.execute('ALTER TABLE traccar_server ADD COLUMN IF NOT EXISTS password VARCHAR')
        cr.execute('UPDATE traccar_server SET password = %s WHERE id = %s', (valor, self.servidor.id))

    def _columna_del_servidor(self):
        self.env.cr.execute('SELECT password FROM traccar_server WHERE id = %s', (self.servidor.id,))
        return self.env.cr.fetchone()[0]

    def test_migracion_copia_el_secreto_y_anula_la_columna(self):
        self._columna_antigua(self.secreto)
        vacio = self.env['traccar.server'].create({'name': 'Servidor sin clave'})
        self.env.cr.execute('UPDATE traccar_server SET password = %s WHERE id = %s', ('', vacio.id))
        self._migracion().migrate(self.env.cr, '16.0.1.0.0')
        clave = self.env['traccar.server.clave'].sudo().search([('server_id', '=', self.servidor.id)])
        self.assertEqual(clave.password, self.secreto)
        self.assertIsNone(self._columna_del_servidor())
        self.assertFalse(self.env['traccar.server.clave'].sudo().search_count([('server_id', '=', vacio.id)]))

    def test_migracion_no_pisa_una_clave_existente(self):
        """Si ya hay una clave nueva, manda la nueva y el valor viejo se conserva en la columna."""
        valor_viejo = 'antiguo-%s' % uuid.uuid4().hex
        self._columna_antigua(valor_viejo)
        self.env['traccar.server.clave'].sudo().create({
            'server_id': self.servidor.id, 'password': self.secreto})
        self._migracion().migrate(self.env.cr, '16.0.1.0.0')
        clave = self.env['traccar.server.clave'].sudo().search([('server_id', '=', self.servidor.id)])
        self.assertEqual(clave.password, self.secreto)
        self.assertEqual(self._columna_del_servidor(), valor_viejo)

    def test_migracion_sin_columna_no_hace_nada(self):
        self.env.cr.execute('ALTER TABLE traccar_server DROP COLUMN IF EXISTS password')
        self._migracion().migrate(self.env.cr, '16.0.1.0.0')
        self.assertFalse(self.env['traccar.server.clave'].sudo().search_count(
            [('server_id', '=', self.servidor.id)]))
