"""Cliente XML-RPC minimo de Odoo. Solo expone lecturas; las herramientas no pueden escribir."""
import asyncio
import xmlrpc.client

TIMEOUT_S = 20


class ErrorOdoo(RuntimeError):
    """Odoo no respondio o rechazo la consulta (mensaje sin credenciales)."""


class _Transporte(xmlrpc.client.Transport):
    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conexion = super().make_connection(host)
        conexion.timeout = self._timeout
        return conexion


class _TransporteSeguro(xmlrpc.client.SafeTransport):
    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conexion = super().make_connection(host)
        conexion.timeout = self._timeout
        return conexion


class ClienteOdoo:
    # Unicas operaciones permitidas sobre los modelos (lectura).
    METODOS_LECTURA = frozenset({'search_read', 'read_group', 'search_count', 'read'})

    def __init__(self, url, db, usuario, clave):
        self.url = url
        self.db = db
        self.usuario = usuario
        self.clave = clave
        self._uid = None

    # ServerProxy no es seguro entre hilos: uno nuevo por llamada.
    def _proxy(self, ruta):
        transporte = (_TransporteSeguro if self.url.startswith('https') else _Transporte)(TIMEOUT_S)
        return xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/{ruta}', allow_none=True, transport=transporte)

    def _autenticar(self, login, clave):
        try:
            return self._proxy('common').authenticate(self.db, login, clave, {}) or None
        except (OSError, xmlrpc.client.Error) as exc:
            raise ErrorOdoo(f'Odoo no responde ({type(exc).__name__}).') from None

    def _uid_servicio(self):
        if not self._uid:
            if not self.clave:
                raise ErrorOdoo('Falta ODOO_PASSWORD / ODOO_ADMIN_PASSWORD para consultar Odoo.')
            self._uid = self._autenticar(self.usuario, self.clave)
            if not self._uid:
                raise ErrorOdoo('La cuenta de servicio de Odoo no pudo iniciar sesion.')
        return self._uid

    def _ejecutar(self, modelo, metodo, args, kwargs=None):
        if metodo not in self.METODOS_LECTURA:
            raise ErrorOdoo(f'Operacion no permitida: {metodo}')
        try:
            return self._proxy('object').execute_kw(
                self.db, self._uid_servicio(), self.clave, modelo, metodo, args, kwargs or {})
        except xmlrpc.client.Fault as exc:
            # El texto de Odoo puede ser largo (traceback): se recorta.
            raise ErrorOdoo(f'Odoo rechazo la consulta sobre {modelo}: {str(exc.faultString)[-300:]}') from None
        except (OSError, xmlrpc.client.Error) as exc:
            raise ErrorOdoo(f'Odoo no responde ({type(exc).__name__}).') from None

    # --- API asincrona (XML-RPC es bloqueante: se ejecuta en un hilo) ---
    async def search_read(self, modelo, dominio, campos, limit=None, order=None):
        kwargs = {'fields': campos}
        if limit:
            kwargs['limit'] = limit
        if order:
            kwargs['order'] = order
        return await asyncio.to_thread(self._ejecutar, modelo, 'search_read', [dominio], kwargs)

    async def read_group(self, modelo, dominio, campos, agrupar, orden=None, limit=None):
        kwargs = {'lazy': False}
        if orden:
            kwargs['orderby'] = orden
        if limit:
            kwargs['limit'] = limit
        return await asyncio.to_thread(self._ejecutar, modelo, 'read_group', [dominio, campos, agrupar], kwargs)

    async def search_count(self, modelo, dominio):
        return await asyncio.to_thread(self._ejecutar, modelo, 'search_count', [dominio])

    # --- Inicio de sesion de personas (no usa la cuenta de servicio para autenticar) ---
    async def autenticar_persona(self, login, clave):
        return await asyncio.to_thread(self._autenticar, login, clave)

    async def datos_admin(self, uid, grupo_xmlid):
        """Nombre y login del usuario si pertenece al grupo de administradores; None si no."""
        modulo, nombre = grupo_xmlid.split('.', 1)
        grupo = await self.search_read('ir.model.data', [('module', '=', modulo), ('name', '=', nombre),
                                                         ('model', '=', 'res.groups')], ['res_id'], limit=1)
        if not grupo:
            raise ErrorOdoo(f'No existe el grupo {grupo_xmlid} en Odoo.')
        usuarios = await self.search_read('res.users', [('id', '=', uid), ('groups_id', 'in', [grupo[0]['res_id']])],
                                          ['name', 'login'], limit=1)
        return usuarios[0] if usuarios else None
