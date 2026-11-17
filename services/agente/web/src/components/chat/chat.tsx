import { useCallback, useEffect, useRef, useState } from 'react'
import { ListIcon, PlusIcon, TrashIcon, XIcon } from '@phosphor-icons/react'
import { toast } from 'sonner'

import { Compositor } from '@/components/chat/compositor'
import { MensajeVista } from '@/components/chat/mensaje'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, enviarMensaje, ErrorApi, type Bloque, type EventoChat, type Mensaje, type ResumenConversacion } from '@/lib/api'
import { cn } from '@/lib/utils'

const SUGERENCIAS = [
  { titulo: '¿Quién es nuestro mejor cliente?', detalle: 'Ranking por monto, frecuencia y última compra' },
  { titulo: '¿Cuánto consumió cada cliente este mes?', detalle: 'Ventas confirmadas del mes en curso' },
  { titulo: '¿Qué productos se venden más?', detalle: 'Cantidad y monto por producto' },
  { titulo: '¿Cómo va la operación ahora?', detalle: 'Entregas, rutas activas y GPS de la flota' },
]

function aplicarEvento(bloques: Bloque[], e: EventoChat): Bloque[] {
  const copia = [...bloques]
  const ultimo = copia[copia.length - 1]
  switch (e.evento) {
    case 'texto':
    case 'pensamiento': {
      const tipo = e.evento === 'texto' ? 'texto' : 'pensamiento'
      if (ultimo && ultimo.tipo === tipo) copia[copia.length - 1] = { ...ultimo, texto: ultimo.texto + e.datos.texto }
      else copia.push({ tipo, texto: e.datos.texto })
      return copia
    }
    case 'herramienta':
      copia.push({ tipo: 'herramienta', ...e.datos, estado: 'ejecutando' })
      return copia
    case 'herramienta_resultado':
      return copia.map((b) => (b.tipo === 'herramienta' && b.id === e.datos.id
        ? { ...b, estado: e.datos.ok ? 'ok' : 'error', ms: e.datos.ms, resumen: e.datos.resumen } : b))
    case 'error':
      copia.push({ tipo: 'error', texto: e.datos.mensaje })
      return copia
    default:
      return copia
  }
}

function horaRelativa(segundos: number) {
  const diff = Date.now() / 1000 - segundos
  if (diff < 60) return 'ahora'
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`
  return new Date(segundos * 1000).toLocaleDateString('es-EC', { day: '2-digit', month: 'short' })
}

export function Chat({ modelo, alSesionCaducada }: { modelo?: string; alSesionCaducada: () => void }) {
  const [conversaciones, setConversaciones] = useState<ResumenConversacion[]>([])
  const [actual, setActual] = useState<string | null>(null)
  const [mensajes, setMensajes] = useState<Mensaje[]>([])
  const [borrador, setBorrador] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [panelAbierto, setPanelAbierto] = useState(false)
  const abortar = useRef<AbortController | null>(null)
  const fondo = useRef<HTMLDivElement>(null)
  const contenedor = useRef<HTMLDivElement>(null)
  const pegadoAlFinal = useRef(true)

  const manejarError = useCallback((err: unknown) => {
    if (err instanceof ErrorApi && err.estado === 401) return alSesionCaducada()
    toast.error(err instanceof Error ? err.message : 'Error inesperado')
  }, [alSesionCaducada])

  const recargarLista = useCallback(() => {
    api.conversaciones().then(setConversaciones).catch(manejarError)
  }, [manejarError])

  useEffect(recargarLista, [recargarLista])

  // Desplazamiento automático solo si el usuario está al final (no interrumpe si sube a leer).
  useEffect(() => {
    if (pegadoAlFinal.current) fondo.current?.scrollIntoView({ block: 'end' })
  }, [mensajes])

  function alDesplazar() {
    const el = contenedor.current
    if (el) pegadoAlFinal.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  async function abrir(id: string) {
    if (ocupado) return
    setPanelAbierto(false)
    try {
      const c = await api.conversacion(id)
      setActual(c.id)
      setMensajes(c.mensajes)
      pegadoAlFinal.current = true
    } catch (err) {
      manejarError(err)
      recargarLista()
    }
  }

  function nueva() {
    if (ocupado) return
    setActual(null)
    setMensajes([])
    setPanelAbierto(false)
  }

  async function borrar(id: string) {
    try {
      await api.borrar(id)
      if (id === actual) nueva()
      recargarLista()
    } catch (err) {
      manejarError(err)
    }
  }

  async function enviar(texto = borrador) {
    const mensaje = texto.trim()
    if (!mensaje || ocupado) return
    setBorrador('')
    setOcupado(true)
    pegadoAlFinal.current = true
    setMensajes((m) => [...m, { rol: 'usuario', bloques: [{ tipo: 'texto', texto: mensaje }] }, { rol: 'asistente', bloques: [] }])
    const control = new AbortController()
    abortar.current = control
    try {
      await enviarMensaje(mensaje, actual, (e) => {
        if (e.evento === 'conversacion') {
          setActual(e.datos.id)
          return
        }
        setMensajes((m) => {
          const copia = [...m]
          const ultimo = copia[copia.length - 1]
          copia[copia.length - 1] = { ...ultimo, bloques: aplicarEvento(ultimo.bloques, e) }
          return copia
        })
      }, control.signal)
    } catch (err) {
      if (control.signal.aborted) {
        setMensajes((m) => {
          const copia = [...m]
          const ultimo = copia[copia.length - 1]
          copia[copia.length - 1] = { ...ultimo, bloques: [...ultimo.bloques, { tipo: 'error', texto: 'Respuesta detenida.' }] }
          return copia
        })
      } else {
        // Si el servidor rechazó el mensaje, se quita el turno vacío y se devuelve el texto al cuadro.
        setMensajes((m) => m.slice(0, -2))
        setBorrador(mensaje)
        manejarError(err)
      }
    } finally {
      abortar.current = null
      setOcupado(false)
      recargarLista()
    }
  }

  const titulo = conversaciones.find((c) => c.id === actual)?.titulo ?? 'Nueva conversación'

  return (
    <div className="flex h-full min-h-0">
      {/* Historial */}
      <aside className={cn(
        'absolute inset-y-0 left-0 z-30 flex w-72 flex-col border-r bg-card transition-transform md:static md:z-auto md:w-64 md:translate-x-0 lg:w-72',
        panelAbierto ? 'translate-x-0 shadow-xl' : '-translate-x-full',
      )}>
        <div className="flex items-center justify-between border-b px-4 py-3">
          <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Conversaciones</span>
          <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={() => setPanelAbierto(false)} aria-label="Cerrar">
            <XIcon />
          </Button>
        </div>
        <div className="p-3">
          <Button variant="outline" className="h-9 w-full justify-start gap-2" onClick={nueva} disabled={ocupado}>
            <PlusIcon weight="bold" /> Nueva conversación
          </Button>
        </div>
        <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {conversaciones.length === 0 && (
            <li className="px-3 py-6 text-center text-xs text-muted-foreground">Aún no hay conversaciones.</li>
          )}
          {conversaciones.map((c) => (
            <li key={c.id} className="group relative">
              <button type="button" onClick={() => abrir(c.id)}
                className={cn('w-full rounded-md px-3 py-2 text-left transition-colors hover:bg-muted',
                  c.id === actual && 'bg-senal-suave hover:bg-senal-suave')}>
                <span className="block truncate pr-6 text-sm">{c.titulo}</span>
                <span className="font-mono text-[10px] text-muted-foreground">{horaRelativa(c.actualizada)}</span>
              </button>
              <button type="button" onClick={() => borrar(c.id)} aria-label={`Borrar «${c.titulo}»`}
                className="absolute top-2 right-2 rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive focus-visible:opacity-100">
                <TrashIcon size={14} />
              </button>
            </li>
          ))}
        </ul>
        <p className="border-t px-4 py-3 text-[11px] leading-snug text-muted-foreground">
          Las conversaciones se guardan 24 h en el servidor.
        </p>
      </aside>
      {panelAbierto && <button type="button" aria-label="Cerrar historial" className="absolute inset-0 z-20 bg-foreground/20 md:hidden" onClick={() => setPanelAbierto(false)} />}

      {/* Conversación */}
      <section className="fondo-plano flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b bg-background/85 px-4 py-3 backdrop-blur md:px-6">
          <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={() => setPanelAbierto(true)} aria-label="Ver conversaciones">
            <ListIcon />
          </Button>
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-senal">Asistente</p>
            <h1 className="truncate font-heading text-[15px] font-semibold tracking-tight">{titulo}</h1>
          </div>
          {modelo && <Badge variant="outline" className="hidden font-mono text-[10px] sm:inline-flex">{modelo}</Badge>}
        </header>

        <div ref={contenedor} onScroll={alDesplazar} className="min-h-0 flex-1 overflow-y-auto">
          {mensajes.length === 0 ? (
            <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-4 py-10 md:px-6">
              <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-senal">Bitácora · Administración</p>
              <h2 className="mt-3 font-heading text-3xl font-semibold tracking-tight text-balance md:text-4xl">
                ¿Qué quieres saber de tu negocio hoy?
              </h2>
              <p className="mt-3 max-w-xl text-muted-foreground">
                Consulto ventas, facturas, clientes y la operación logística directamente en Odoo. Te digo de dónde sale cada cifra.
              </p>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {SUGERENCIAS.map((s, i) => (
                  <button key={s.titulo} type="button" onClick={() => enviar(s.titulo)}
                    className="group rounded-lg border bg-card p-4 text-left transition-all hover:-translate-y-0.5 hover:border-senal/50 hover:shadow-md">
                    <span className="font-mono text-[10px] text-muted-foreground">{String(i + 1).padStart(2, '0')}</span>
                    <span className="mt-1 block font-medium group-hover:text-foreground">{s.titulo}</span>
                    <span className="mt-1 block text-xs text-muted-foreground">{s.detalle}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-7 px-4 py-8 md:px-6">
              {mensajes.map((m, i) => (
                <MensajeVista key={i} mensaje={m} enCurso={ocupado && i === mensajes.length - 1} />
              ))}
              <div ref={fondo} />
            </div>
          )}
        </div>

        <Compositor valor={borrador} alCambiar={setBorrador} alEnviar={() => enviar()}
          alDetener={() => abortar.current?.abort()} ocupado={ocupado} />
      </section>
    </div>
  )
}
