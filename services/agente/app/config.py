"""Configuracion del servicio del asistente (solo variables de entorno; nada de secretos en el codigo)."""
import os
from dataclasses import dataclass


def _bool(nombre, defecto):
    valor = os.environ.get(nombre)
    if valor is None or valor.strip() == '':
        return defecto
    return valor.strip().lower() in ('1', 'true', 'si', 'sí', 'yes')


@dataclass(frozen=True)
class Config:
    # Odoo: la cuenta de servicio solo se usa para LEER (search_read / read_group) en las herramientas.
    odoo_url: str
    odoo_db: str
    odoo_user: str
    odoo_password: str
    grupo_admin: str
    # Claude
    modelo: str
    esfuerzo: str
    max_vueltas: int
    # Sesion web
    session_secret: str
    cookie_segura: bool
    sesion_horas: int
    zona_horaria: str


def cargar():
    secreto = (os.environ.get('AGENTE_SESSION_SECRET') or '').strip()
    if len(secreto) < 32:
        raise RuntimeError('AGENTE_SESSION_SECRET falta o es corta (minimo 32 caracteres): '
                           'genere una con `openssl rand -hex 32`.')
    clave_odoo = (os.environ.get('ODOO_PASSWORD') or os.environ.get('ODOO_ADMIN_PASSWORD') or '').strip()
    return Config(
        odoo_url=(os.environ.get('ODOO_URL') or 'http://odoo:8069').rstrip('/'),
        odoo_db=os.environ.get('ODOO_DB') or 'logistica_dev',
        odoo_user=os.environ.get('ODOO_USER') or 'admin',
        odoo_password=clave_odoo,
        grupo_admin=os.environ.get('AGENTE_GRUPO_ADMIN') or 'base.group_system',
        modelo=os.environ.get('AGENTE_MODELO') or 'claude-opus-5-5',
        esfuerzo=os.environ.get('AGENTE_ESFUERZO') or 'medium',
        max_vueltas=int(os.environ.get('AGENTE_MAX_VUELTAS') or 8),
        session_secret=secreto,
        cookie_segura=_bool('AGENTE_COOKIE_SEGURA', True),
        sesion_horas=int(os.environ.get('AGENTE_SESION_HORAS') or 8),
        zona_horaria=os.environ.get('AGENTE_ZONA_HORARIA') or 'America/Guayaquil',
    )
