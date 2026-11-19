"""Conversaciones en memoria, por usuario. Se pierden al reiniciar el servicio (versión inicial).

Para un solo proceso de uvicorn. Si se escala a varios procesos, mover a PostgreSQL.
"""
import asyncio
import secrets
import time
from dataclasses import dataclass, field

MAX_POR_USUARIO = 50
TTL_S = 24 * 3600


@dataclass
class Conversacion:
    id: str
    uid: int
    titulo: str
    creada: float = field(default_factory=time.time)
    actualizada: float = field(default_factory=time.time)
    historial: list = field(default_factory=list)   # mensajes en formato de la API (append-only)
    vista: list = field(default_factory=list)       # lo que muestra la interfaz al recargar
    candado: asyncio.Lock = field(default_factory=asyncio.Lock)

    def tocar(self):
        self.actualizada = time.time()

    def resumen(self):
        return {'id': self.id, 'titulo': self.titulo, 'actualizada': self.actualizada}


class Almacen:
    def __init__(self):
        self._datos = {}

    def _purgar(self):
        corte = time.time() - TTL_S
        for cid in [c.id for c in self._datos.values() if c.actualizada < corte and not c.candado.locked()]:
            del self._datos[cid]

    def crear(self, uid, primer_mensaje):
        self._purgar()
        propias = sorted((c for c in self._datos.values() if c.uid == uid), key=lambda c: c.actualizada)
        for vieja in propias[:max(0, len(propias) - MAX_POR_USUARIO + 1)]:
            if not vieja.candado.locked():
                del self._datos[vieja.id]
        titulo = ' '.join(primer_mensaje.split())[:60] or 'Conversación'
        conversacion = Conversacion(id=secrets.token_urlsafe(12), uid=uid, titulo=titulo)
        self._datos[conversacion.id] = conversacion
        return conversacion

    def obtener(self, uid, cid):
        conversacion = self._datos.get(cid)
        # Una conversación ajena se trata igual que una inexistente.
        return conversacion if conversacion and conversacion.uid == uid else None

    def listar(self, uid):
        self._purgar()
        propias = [c for c in self._datos.values() if c.uid == uid]
        return [c.resumen() for c in sorted(propias, key=lambda c: c.actualizada, reverse=True)]

    def borrar(self, uid, cid):
        conversacion = self.obtener(uid, cid)
        if conversacion and not conversacion.candado.locked():
            del self._datos[cid]
            return True
        return False
