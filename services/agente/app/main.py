"""Servicio del asistente del administrador: API (login, conversaciones, chat en streaming) + interfaz React.

La interfaz se sirve desde este mismo servicio: navegador y API comparten origen, así que no hay CORS.
"""
import asyncio
import hmac
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

import openai
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import agente, basedatos
from .config import cargar
from .conversaciones import Almacen
from .odoo import ClienteOdoo, ErrorOdoo

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger('agente')

config = cargar()
odoo = ClienteOdoo(config.odoo_url, config.odoo_db, config.odoo_user, config.odoo_password)
almacen = Almacen()
_cliente_ia = None
config_bd = basedatos.ConfigBD.desde_entorno()
operacion_bd = asyncio.Lock()
MAX_SUBIDA_BYTES = int(os.environ.get('AGENTE_MAX_SUBIDA_MB') or 2048) * 1024 * 1024
CONFIRMACION_RESTAURAR = 'RESTAURAR'

STATIC_DIR = Path(os.environ.get('AGENTE_STATIC_DIR') or Path(__file__).resolve().parent.parent / 'static')
CABECERA_CSRF = 'x-agente'


def cliente_ia():
    """Cliente de OpenAI creado al primer uso: sin OPENAI_API_KEY el servicio arranca igual y lo avisa en el chat."""
    global _cliente_ia
    if _cliente_ia is None:
        _cliente_ia = openai.AsyncOpenAI(timeout=600, max_retries=2)
    return _cliente_ia


class Limitador:
    """Ventana deslizante en memoria por clave (IP o usuario)."""

    def __init__(self, limite, ventana_s):
        self.limite, self.ventana = limite, ventana_s
        self._marcas = defaultdict(deque)

    def permitir(self, clave):
        ahora = time.monotonic()
        marcas = self._marcas[clave]
        while marcas and marcas[0] <= ahora - self.ventana:
            marcas.popleft()
        if len(marcas) >= self.limite:
            return False
        marcas.append(ahora)
        return True


limite_login = Limitador(10, 300)
limite_chat = Limitador(30, 600)
limite_maestra = Limitador(10, 900)

app = FastAPI(title='Asistente del administrador', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.session_secret, session_cookie='agente_sesion',
                   max_age=config.sesion_horas * 3600, same_site='lax', https_only=config.cookie_segura)


@app.middleware('http')
async def cabeceras_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    respuesta.headers.setdefault('X-Content-Type-Options', 'nosniff')
    respuesta.headers.setdefault('Referrer-Policy', 'same-origin')
    respuesta.headers.setdefault('X-Frame-Options', 'DENY')
    respuesta.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if request.url.path.startswith('/api/'):
        respuesta.headers.setdefault('Cache-Control', 'no-store')
    return respuesta


# ------------------------------------------------------------------ seguridad
def exigir_csrf(request: Request):
    # Una cabecera propia no se puede enviar desde otro sitio sin CORS (y este servicio no habilita CORS).
    if request.headers.get(CABECERA_CSRF) != '1':
        raise HTTPException(403, 'Solicitud no permitida.')


def usuario_actual(request: Request):
    usuario = request.session.get('usuario')
    if not usuario:
        raise HTTPException(401, 'Inicie sesión.')
    return usuario


def _ip(request: Request):
    return request.client.host if request.client else 'desconocida'


# ------------------------------------------------------------------ API
class EntradaLogin(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    clave: str = Field(min_length=1, max_length=500)


class EntradaChat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=4000)
    conversacion_id: str | None = Field(None, max_length=40)


@app.get('/api/salud')
async def salud():
    return {'estado': 'ok', 'modelo': config.modelo, 'ia_configurada': bool(os.environ.get('OPENAI_API_KEY'))}


@app.post('/api/login', dependencies=[Depends(exigir_csrf)])
async def login(datos: EntradaLogin, request: Request):
    if not limite_login.permitir(_ip(request)):
        raise HTTPException(429, 'Demasiados intentos. Espere unos minutos.')
    try:
        uid = await odoo.autenticar_persona(datos.login.strip(), datos.clave)
        usuario = await odoo.datos_admin(uid, config.grupo_admin) if uid else None
    except ErrorOdoo as exc:
        _logger.warning('login_odoo_error %s', exc)
        raise HTTPException(503, 'No se pudo contactar con Odoo. Intente de nuevo.') from None
    if not uid:
        raise HTTPException(401, 'Usuario o contraseña incorrectos.')
    if not usuario:
        raise HTTPException(403, 'El asistente es solo para administradores de Odoo.')
    request.session.clear()
    request.session['usuario'] = {'uid': uid, 'nombre': usuario['name'], 'login': usuario['login']}
    return {'nombre': usuario['name'], 'login': usuario['login']}


@app.post('/api/logout', dependencies=[Depends(exigir_csrf)])
async def logout(request: Request):
    request.session.clear()
    return {'ok': True}


@app.get('/api/yo')
async def yo(usuario=Depends(usuario_actual)):
    return {'nombre': usuario['nombre'], 'login': usuario['login'], 'modelo': config.modelo}


@app.get('/api/conversaciones')
async def listar(usuario=Depends(usuario_actual)):
    return almacen.listar(usuario['uid'])


@app.get('/api/conversaciones/{cid}')
async def detalle(cid: str, usuario=Depends(usuario_actual)):
    conversacion = almacen.obtener(usuario['uid'], cid)
    if not conversacion:
        raise HTTPException(404, 'Conversación no encontrada.')
    return {**conversacion.resumen(), 'mensajes': conversacion.vista}


@app.delete('/api/conversaciones/{cid}', dependencies=[Depends(exigir_csrf)])
async def borrar(cid: str, usuario=Depends(usuario_actual)):
    if not almacen.borrar(usuario['uid'], cid):
        raise HTTPException(404, 'Conversación no encontrada o en uso.')
    return {'ok': True}


def _sse(evento, datos):
    return f'event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False, default=str)}\n\n'


@app.post('/api/chat', dependencies=[Depends(exigir_csrf)])
async def chat(datos: EntradaChat, usuario=Depends(usuario_actual)):
    uid = usuario['uid']
    if not limite_chat.permitir(uid):
        raise HTTPException(429, 'Demasiados mensajes seguidos. Espere unos minutos.')
    if datos.conversacion_id:
        conversacion = almacen.obtener(uid, datos.conversacion_id)
        if not conversacion:
            raise HTTPException(404, 'Conversación no encontrada.')
    else:
        conversacion = almacen.crear(uid, datos.mensaje)
    if conversacion.candado.locked():
        raise HTTPException(409, 'Esta conversación ya está respondiendo.')

    async def flujo():
        async with conversacion.candado:
            conversacion.vista.append({'rol': 'usuario', 'bloques': [{'tipo': 'texto', 'texto': datos.mensaje}]})
            yield _sse('conversacion', conversacion.resumen())
            if not os.environ.get('OPENAI_API_KEY'):
                mensaje = 'Falta configurar OPENAI_API_KEY en el servicio del asistente.'
                conversacion.vista.append({'rol': 'asistente', 'bloques': [{'tipo': 'error', 'texto': mensaje}]})
                yield _sse('error', {'mensaje': mensaje})
                return
            async for evento in agente.ejecutar_turno(cliente_ia(), odoo, config, conversacion, datos.mensaje):
                yield _sse(evento['evento'], evento['datos'])

    return StreamingResponse(flujo(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ------------------------------------------------------------------ base de datos (respaldos y restauración)
def _exigir_bd_disponible():
    if not config_bd.disponible:
        raise HTTPException(503, 'La gestión de la base no está configurada en este servicio (falta PGPASSWORD).')


def _exigir_clave_maestra(usuario, clave):
    """Cada operación sobre la base pide la contraseña maestra de Odoo (además de la sesión de administrador)."""
    esperada = os.environ.get('ODOO_MASTER_PASSWORD') or ''
    if not esperada:
        raise HTTPException(503, 'Falta ODOO_MASTER_PASSWORD en el servicio del asistente.')
    if not limite_maestra.permitir(usuario['uid']):
        raise HTTPException(429, 'Demasiados intentos con la contraseña maestra. Espere unos minutos.')
    if not hmac.compare_digest((clave or '').encode(), esperada.encode()):
        _logger.warning('bd_clave_maestra_incorrecta usuario=%s', usuario['login'])
        raise HTTPException(403, 'Contraseña maestra incorrecta.')


async def _en_exclusiva(funcion, *args):
    if operacion_bd.locked():
        raise HTTPException(409, 'Ya hay una operación de base de datos en curso. Espere a que termine.')
    async with operacion_bd:
        try:
            return await asyncio.to_thread(funcion, *args)
        except basedatos.ErrorBD as exc:
            raise HTTPException(400, str(exc)) from None


class EntradaRespaldo(BaseModel):
    base: str = Field(pattern='^(odoo|traccar)$')
    clave_maestra: str = Field(min_length=1, max_length=500)


class EntradaClave(BaseModel):
    clave_maestra: str = Field(min_length=1, max_length=500)


@app.get('/api/bd')
async def bd_estado(_usuario=Depends(usuario_actual)):
    _exigir_bd_disponible()
    datos = await asyncio.to_thread(basedatos.estado, config_bd)
    return {**datos, 'en_curso': operacion_bd.locked(), 'max_subida_mb': MAX_SUBIDA_BYTES // (1024 * 1024)}


@app.post('/api/bd/respaldos', dependencies=[Depends(exigir_csrf)])
async def bd_respaldar(datos: EntradaRespaldo, usuario=Depends(usuario_actual)):
    _exigir_bd_disponible()
    _exigir_clave_maestra(usuario, datos.clave_maestra)
    _logger.info('bd_respaldo base=%s usuario=%s', datos.base, usuario['login'])
    ruta = await _en_exclusiva(basedatos.respaldar, config_bd, datos.base)
    return {'nombre': ruta.name, 'tamano_bytes': ruta.stat().st_size}


@app.get('/api/bd/respaldos/{nombre}')
async def bd_descargar(nombre: str, usuario=Depends(usuario_actual)):
    _exigir_bd_disponible()
    try:
        ruta = basedatos.ruta_respaldo(config_bd, nombre)
    except basedatos.ErrorBD as exc:
        raise HTTPException(404, str(exc)) from None
    _logger.info('bd_descarga archivo=%s usuario=%s', nombre, usuario['login'])
    return FileResponse(ruta, filename=ruta.name, media_type='application/octet-stream')


@app.post('/api/bd/respaldos/{nombre}/borrar', dependencies=[Depends(exigir_csrf)])
async def bd_borrar(nombre: str, datos: EntradaClave, usuario=Depends(usuario_actual)):
    _exigir_bd_disponible()
    _exigir_clave_maestra(usuario, datos.clave_maestra)
    try:
        basedatos.borrar(config_bd, nombre)
    except basedatos.ErrorBD as exc:
        raise HTTPException(404, str(exc)) from None
    _logger.info('bd_borrado archivo=%s usuario=%s', nombre, usuario['login'])
    return {'ok': True}


@app.post('/api/bd/restaurar', dependencies=[Depends(exigir_csrf)])
async def bd_restaurar(
    usuario=Depends(usuario_actual),
    base: str = Form(pattern='^(odoo|traccar)$'),
    clave_maestra: str = Form(min_length=1, max_length=500),
    confirmacion: str = Form(max_length=40),
    nombre: str | None = Form(None, max_length=200),
    archivo: UploadFile | None = File(None),
):
    """Restaura desde un respaldo guardado (`nombre`) o desde un archivo subido (`archivo`)."""
    _exigir_bd_disponible()
    _exigir_clave_maestra(usuario, clave_maestra)
    if confirmacion.strip().upper() != CONFIRMACION_RESTAURAR:
        raise HTTPException(400, f'Escriba {CONFIRMACION_RESTAURAR} para confirmar.')
    if operacion_bd.locked():
        raise HTTPException(409, 'Ya hay una operación de base de datos en curso. Espere a que termine.')
    if archivo is not None and archivo.filename:
        try:
            destino = config_bd.dir_respaldos / basedatos.nombre_para_subida(base, archivo.filename)
        except basedatos.ErrorBD as exc:
            raise HTTPException(400, str(exc)) from None
        config_bd.dir_respaldos.mkdir(parents=True, exist_ok=True)
        await _guardar_subida(archivo, destino)
        ruta = destino
    elif nombre:
        try:
            ruta = basedatos.ruta_respaldo(config_bd, nombre)
        except basedatos.ErrorBD as exc:
            raise HTTPException(404, str(exc)) from None
        if not ruta.name.startswith(f'{base}_'):
            raise HTTPException(400, f'Ese respaldo no es de {base}.')
    else:
        raise HTTPException(400, 'Elija un respaldo guardado o suba un archivo.')
    return await _en_exclusiva(basedatos.restaurar, config_bd, base, ruta, usuario['login'])


async def _guardar_subida(archivo: UploadFile, destino):
    parcial = destino.with_suffix('.parcial')
    total = 0
    try:
        with open(parcial, 'wb') as salida:
            while bloque := await archivo.read(1024 * 1024):
                total += len(bloque)
                if total > MAX_SUBIDA_BYTES:
                    raise HTTPException(413, f'El archivo supera {MAX_SUBIDA_BYTES // (1024 * 1024)} MB.')
                salida.write(bloque)
        parcial.rename(destino)
    finally:
        parcial.unlink(missing_ok=True)
        await archivo.close()


@app.exception_handler(HTTPException)
async def error_http(_request: Request, exc: HTTPException):
    return JSONResponse({'detalle': exc.detail}, status_code=exc.status_code)


# ------------------------------------------------------------------ interfaz (SPA)
if STATIC_DIR.is_dir():
    app.mount('/assets', StaticFiles(directory=STATIC_DIR / 'assets'), name='assets')

    @app.get('/{ruta:path}', include_in_schema=False)
    async def spa(ruta: str):
        if ruta.startswith('api/'):
            raise HTTPException(404, 'No encontrado.')
        archivo = (STATIC_DIR / ruta).resolve()
        if ruta and archivo.is_file() and archivo.is_relative_to(STATIC_DIR.resolve()):
            return FileResponse(archivo)
        return FileResponse(STATIC_DIR / 'index.html', headers={'Cache-Control': 'no-cache'})
