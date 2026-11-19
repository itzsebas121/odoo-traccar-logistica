import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from 'react'
import {
  ArrowCounterClockwiseIcon, CheckCircleIcon, CircleNotchIcon, CloudArrowUpIcon, DatabaseIcon, DownloadSimpleIcon,
  FileIcon, FileZipIcon, HardDrivesIcon, ShieldWarningIcon, TrashIcon, WarningCircleIcon,
} from '@phosphor-icons/react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import {
  apiBD, ErrorApi, restaurarBD, type BaseId, type EstadoBD, type Respaldo, type ResultadoRestauracion,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const NOMBRES: Record<BaseId, string> = { odoo: 'Odoo', traccar: 'Traccar' }
const EXTENSIONES: Record<BaseId, string> = { odoo: '.zip,.dump', traccar: '.dump' }
const CONFIRMAR = 'RESTAURAR'

function bytes(n?: number) {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1)
  return `${(n / 1024 ** i).toLocaleString('es-EC', { maximumFractionDigits: i ? 1 : 0 })} ${u[i]}`
}

function fecha(segundos: number) {
  return new Date(segundos * 1000).toLocaleString('es-EC', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function Etiqueta({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn('font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground', className)}>{children}</p>
}

// ------------------------------------------------------------------ diálogo con contraseña maestra
function DialogoClave({ abierto, titulo, descripcion, accion, peligro, alConfirmar, alCerrar }: {
  abierto: boolean
  titulo: string
  descripcion: ReactNode
  accion: string
  peligro?: boolean
  alConfirmar: (clave: string) => Promise<void>
  alCerrar: () => void
}) {
  const [clave, setClave] = useState('')
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setCargando(true)
    setError(null)
    try {
      await alConfirmar(clave)
      alCerrar()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error inesperado')
    } finally {
      setCargando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(v) => !v && !cargando && alCerrar()}>
      <DialogContent className="rounded-lg p-6 sm:max-w-md">
        <form onSubmit={enviar} className="space-y-5">
          <DialogHeader>
            <DialogTitle className="font-heading text-base">{titulo}</DialogTitle>
            <DialogDescription className="text-sm">{descripcion}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="clave-maestra">Contraseña maestra de Odoo</Label>
            <Input id="clave-maestra" type="password" autoFocus required value={clave} onChange={(e) => setClave(e.target.value)}
              autoComplete="off" className="h-10" />
          </div>
          {error && <p role="alert" className="border-l-2 border-destructive bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={alCerrar} disabled={cargando} className="h-9">Cancelar</Button>
            <Button type="submit" disabled={cargando || !clave} variant={peligro ? 'destructive' : 'default'} className="h-9">
              {cargando && <CircleNotchIcon className="animate-spin" />}{accion}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------ diálogo de restauración
type Origen = { base: BaseId; archivo?: File; respaldo?: Respaldo }

function DialogoRestaurar({ origen, alCerrar, alTerminar }: {
  origen: Origen | null
  alCerrar: () => void
  alTerminar: (r: ResultadoRestauracion) => void
}) {
  const [clave, setClave] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [fase, setFase] = useState<'formulario' | 'subiendo' | 'restaurando'>('formulario')
  const [avance, setAvance] = useState(0)
  const [error, setError] = useState<string | null>(null)

  if (!origen) return null
  const nombreArchivo = origen.archivo?.name ?? origen.respaldo?.nombre ?? ''
  const ocupado = fase !== 'formulario'

  async function enviar(e: FormEvent) {
    e.preventDefault()
    if (!origen) return
    setError(null)
    setFase(origen.archivo ? 'subiendo' : 'restaurando')
    try {
      const resultado = await restaurarBD(
        { base: origen.base, clave_maestra: clave, confirmacion, archivo: origen.archivo, nombre: origen.respaldo?.nombre },
        (p) => { setAvance(p); if (p >= 100) setFase('restaurando') },
      )
      alTerminar(resultado)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error inesperado')
      setFase('formulario')
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && !ocupado && alCerrar()}>
      <DialogContent showCloseButton={!ocupado} className="rounded-lg p-6 sm:max-w-lg">
        <form onSubmit={enviar} className="space-y-5">
          <DialogHeader>
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-destructive">Operación irreversible</p>
            <DialogTitle className="font-heading text-lg">Restaurar la base de {NOMBRES[origen.base]}</DialogTitle>
            <DialogDescription className="text-sm">
              Los datos actuales de {NOMBRES[origen.base]} se reemplazarán por los del respaldo.
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-3 rounded-md border bg-muted/50 px-3 py-2.5">
            {nombreArchivo.endsWith('.zip') ? <FileZipIcon size={22} className="shrink-0 text-senal" /> : <FileIcon size={22} className="shrink-0 text-senal" />}
            <div className="min-w-0">
              <p className="truncate font-mono text-xs">{nombreArchivo}</p>
              <p className="text-xs text-muted-foreground">
                {origen.archivo ? `${bytes(origen.archivo.size)} · se subirá al servidor` : `${bytes(origen.respaldo?.tamano_bytes)} · guardado en el servidor`}
              </p>
            </div>
          </div>

          <ul className="space-y-1.5 text-[13px] text-muted-foreground">
            <li className="flex gap-2"><CheckCircleIcon size={16} className="mt-0.5 shrink-0 text-ok" />Antes de restaurar se guarda un respaldo automático de lo que hay ahora.</li>
            <li className="flex gap-2"><CheckCircleIcon size={16} className="mt-0.5 shrink-0 text-ok" />Si el archivo falla al cargarse, la base actual no se toca.</li>
            <li className="flex gap-2"><WarningCircleIcon size={16} className="mt-0.5 shrink-0 text-senal" />Al terminar hay que reiniciar el servicio <b className="font-mono text-foreground">{origen.base}</b>.</li>
          </ul>

          {fase === 'formulario' ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="r-clave">Contraseña maestra de Odoo</Label>
                <Input id="r-clave" type="password" required autoFocus value={clave} onChange={(e) => setClave(e.target.value)} autoComplete="off" className="h-10" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="r-confirmar">Escribe <span className="font-mono font-semibold text-destructive">{CONFIRMAR}</span> para confirmar</Label>
                <Input id="r-confirmar" required value={confirmacion} onChange={(e) => setConfirmacion(e.target.value)} autoComplete="off"
                  className="h-10 font-mono uppercase" />
              </div>
            </>
          ) : (
            <div className="space-y-2 rounded-md border border-dashed p-4">
              <p className="flex items-center gap-2 text-sm font-medium">
                <CircleNotchIcon className="animate-spin text-senal" />
                {fase === 'subiendo' ? `Subiendo archivo… ${avance} %` : 'Restaurando… puede tardar varios minutos. No cierres esta ventana.'}
              </p>
              {fase === 'subiendo' && <Progress value={avance} />}
            </div>
          )}

          {error && <p role="alert" className="border-l-2 border-destructive bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={alCerrar} disabled={ocupado} className="h-9">Cancelar</Button>
            <Button type="submit" variant="destructive" className="h-9"
              disabled={ocupado || !clave || confirmacion.trim().toUpperCase() !== CONFIRMAR}>
              <ArrowCounterClockwiseIcon /> Restaurar
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------ vista
export function BaseDeDatos({ alSesionCaducada }: { alSesionCaducada: () => void }) {
  const [estado, setEstado] = useState<EstadoBD | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [baseCarga, setBaseCarga] = useState<BaseId>('odoo')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [arrastrando, setArrastrando] = useState(false)
  const [restaurar, setRestaurar] = useState<Origen | null>(null)
  const [respaldar, setRespaldar] = useState<BaseId | null>(null)
  const [borrar, setBorrar] = useState<Respaldo | null>(null)
  const [resultado, setResultado] = useState<ResultadoRestauracion | null>(null)
  const entrada = useRef<HTMLInputElement>(null)

  const cargar = useCallback(() => {
    apiBD.estado().then((e) => { setEstado(e); setError(null) }).catch((err) => {
      if (err instanceof ErrorApi && err.estado === 401) return alSesionCaducada()
      setError(err instanceof Error ? err.message : 'Error inesperado')
    })
  }, [alSesionCaducada])

  useEffect(cargar, [cargar])

  function elegir(f: File | undefined | null) {
    if (!f) return
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
    const base: BaseId = ext === '.zip' ? 'odoo' : baseCarga
    if (!EXTENSIONES[base].split(',').includes(ext)) {
      toast.error(`Para ${NOMBRES[base]} se admite ${EXTENSIONES[base].replace(',', ' o ')}.`)
      return
    }
    if (estado && f.size > estado.max_subida_mb * 1024 * 1024) {
      toast.error(`El archivo supera ${estado.max_subida_mb} MB.`)
      return
    }
    setBaseCarga(base)
    setArchivo(f)
  }

  function soltar(e: DragEvent) {
    e.preventDefault()
    setArrastrando(false)
    elegir(e.dataTransfer.files?.[0])
  }

  return (
    <section className="fondo-plano h-full overflow-y-auto">
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b bg-background/85 px-4 py-4 backdrop-blur md:px-8">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-senal">Mantenimiento</p>
          <h1 className="font-heading text-xl font-semibold tracking-tight">Base de datos</h1>
        </div>
        <Badge variant="outline" className="hidden gap-1.5 font-mono text-[10px] sm:inline-flex">
          <ShieldWarningIcon size={14} /> Cada operación pide la contraseña maestra
        </Badge>
      </header>

      <div className="mx-auto max-w-5xl space-y-8 px-4 py-8 md:px-8">
        {error && <p role="alert" className="border-l-2 border-destructive bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</p>}
        {estado && !estado.disponible && (
          <p role="alert" className="border-l-2 border-destructive bg-destructive/5 px-4 py-3 text-sm text-destructive">
            No se pudo leer PostgreSQL: {estado.error}
          </p>
        )}

        {resultado && (
          <div className="rounded-lg border border-ok/40 bg-card p-5">
            <p className="flex items-center gap-2 font-heading font-semibold"><CheckCircleIcon size={20} weight="fill" className="text-ok" />
              Base de {NOMBRES[resultado.base]} restaurada en {resultado.segundos} s</p>
            <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-muted-foreground marker:font-mono">
              <li><b className="text-foreground">Reinicia el servicio <span className="font-mono">{resultado.reiniciar}</span>:</b> en Dokploy, Compose → servicio {resultado.reiniciar} → Restart; en local, <span className="font-mono">docker compose restart {resultado.reiniciar}</span>.</li>
              {resultado.respaldo_previo && <li>Lo que había antes quedó en el respaldo <span className="font-mono text-foreground">{resultado.respaldo_previo}</span>.</li>}
              <li>La base reemplazada se conserva como <span className="font-mono text-foreground">{resultado.base_anterior}</span> hasta la próxima restauración.</li>
            </ol>
            <Button variant="outline" className="mt-4 h-8" onClick={() => setResultado(null)}>Entendido</Button>
          </div>
        )}

        {/* Bases */}
        <div className="grid gap-4 md:grid-cols-2">
          {(estado?.bases ?? [{ base: 'odoo' }, { base: 'traccar' }] as { base: BaseId }[]).map((b) => {
            const info = estado?.bases.find((x) => x.base === b.base)
            return (
              <article key={b.base} className="rounded-lg border bg-card p-5">
                <div className="flex items-start gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-sidebar text-sidebar-primary">
                    {b.base === 'odoo' ? <DatabaseIcon size={20} weight="duotone" /> : <HardDrivesIcon size={20} weight="duotone" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <Etiqueta>{b.base === 'odoo' ? 'ERP · ventas, facturas, entregas' : 'GPS · posiciones y eventos'}</Etiqueta>
                    <h2 className="mt-1 font-heading text-lg font-semibold">{NOMBRES[b.base]}</h2>
                    <p className="font-mono text-xs text-muted-foreground">{info?.nombre ?? '…'}</p>
                  </div>
                </div>
                <dl className="cifras mt-5 grid grid-cols-2 gap-3 border-t border-dashed pt-4 text-sm">
                  <div><dt className="text-xs text-muted-foreground">Tamaño de la base</dt><dd className="font-mono">{info ? bytes(info.tamano_bytes) : '…'}</dd></div>
                  {b.base === 'odoo' && <div><dt className="text-xs text-muted-foreground">Adjuntos (filestore)</dt><dd className="font-mono">{info ? bytes(info.filestore_bytes) : '…'}</dd></div>}
                </dl>
                <Button className="mt-5 h-9 w-full gap-2" variant="outline" disabled={!info?.existe || estado?.en_curso}
                  onClick={() => setRespaldar(b.base)}>
                  <DownloadSimpleIcon /> Crear respaldo de {NOMBRES[b.base]}
                </Button>
              </article>
            )
          })}
        </div>

        {/* Cargar */}
        <article className="rounded-lg border bg-card p-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <Etiqueta>Cargar respaldo</Etiqueta>
              <h2 className="mt-1 font-heading text-lg font-semibold">Restaurar desde un archivo</h2>
              <p className="mt-1 max-w-xl text-sm text-muted-foreground">
                Odoo: ZIP del gestor de bases de Odoo (incluye adjuntos) o .dump de PostgreSQL. Traccar: .dump de PostgreSQL.
              </p>
            </div>
            <div role="radiogroup" aria-label="Base a restaurar" className="inline-flex rounded-md border p-0.5">
              {(['odoo', 'traccar'] as BaseId[]).map((b) => (
                <button key={b} type="button" role="radio" aria-checked={baseCarga === b}
                  onClick={() => { setBaseCarga(b); setArchivo(null) }}
                  className={cn('rounded px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition-colors',
                    baseCarga === b ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
                  {NOMBRES[b]}
                </button>
              ))}
            </div>
          </div>

          <div
            onDragOver={(e) => { e.preventDefault(); setArrastrando(true) }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={soltar}
            className={cn('mt-5 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors',
              arrastrando ? 'border-senal bg-senal-suave' : 'border-border')}
          >
            <CloudArrowUpIcon size={32} className="text-senal" />
            {archivo ? (
              <>
                <p className="font-mono text-sm">{archivo.name}</p>
                <p className="text-xs text-muted-foreground">{bytes(archivo.size)} · {NOMBRES[baseCarga]}</p>
                <div className="mt-2 flex gap-2">
                  <Button variant="outline" className="h-8" onClick={() => setArchivo(null)}>Quitar</Button>
                  <Button variant="destructive" className="h-8 gap-1.5" onClick={() => setRestaurar({ base: baseCarga, archivo })}
                    disabled={estado?.en_curso}>
                    <ArrowCounterClockwiseIcon /> Restaurar {NOMBRES[baseCarga]}…
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm">Arrastra aquí el archivo o{' '}
                  <button type="button" className="font-medium text-senal underline underline-offset-2" onClick={() => entrada.current?.click()}>elígelo</button>
                </p>
                <p className="text-xs text-muted-foreground">{EXTENSIONES[baseCarga].replace(',', ' · ')} · máximo {estado?.max_subida_mb ?? 2048} MB</p>
              </>
            )}
            <input ref={entrada} type="file" accept={EXTENSIONES[baseCarga]} className="hidden"
              onChange={(e) => { elegir(e.target.files?.[0]); e.target.value = '' }} />
          </div>
        </article>

        {/* Respaldos guardados */}
        <article className="rounded-lg border bg-card">
          <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
            <div>
              <Etiqueta>En el servidor</Etiqueta>
              <h2 className="mt-1 font-heading text-lg font-semibold">Respaldos guardados</h2>
            </div>
            <span className="font-mono text-xs text-muted-foreground">{estado?.respaldos.length ?? 0} archivo(s)</span>
          </div>
          {!estado ? (
            <p className="flex items-center gap-2 px-5 py-6 text-sm text-muted-foreground"><CircleNotchIcon className="animate-spin" /> Cargando…</p>
          ) : estado.respaldos.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-muted-foreground">Todavía no hay respaldos. Crea el primero arriba.</p>
          ) : (
            <ul className="divide-y divide-dashed">
              {estado.respaldos.map((r) => (
                <li key={r.nombre} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  {r.nombre.endsWith('.zip') ? <FileZipIcon size={22} className="shrink-0 text-muted-foreground" /> : <FileIcon size={22} className="shrink-0 text-muted-foreground" />}
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[13px]">{r.nombre}</p>
                    <p className="cifras mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      <Badge variant="secondary" className="font-mono text-[10px] uppercase">{NOMBRES[r.base]}</Badge>
                      {r.automatico && <Badge variant="outline" className="text-[10px]">automático</Badge>}
                      <span>{bytes(r.tamano_bytes)}</span><span>·</span><span>{fecha(r.creado)}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button asChild variant="ghost" className="h-8 gap-1.5">
                      <a href={apiBD.urlDescarga(r.nombre)} download><DownloadSimpleIcon /> <span className="hidden sm:inline">Descargar</span></a>
                    </Button>
                    <Button variant="ghost" className="h-8 gap-1.5" disabled={estado.en_curso} onClick={() => setRestaurar({ base: r.base, respaldo: r })}>
                      <ArrowCounterClockwiseIcon /> <span className="hidden sm:inline">Restaurar</span>
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label={`Borrar ${r.nombre}`} className="text-muted-foreground hover:text-destructive"
                      onClick={() => setBorrar(r)}>
                      <TrashIcon />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </article>
      </div>

      <DialogoClave
        key={`respaldar-${respaldar}`}
        abierto={respaldar !== null}
        titulo={`Crear respaldo de ${respaldar ? NOMBRES[respaldar] : ''}`}
        descripcion={respaldar === 'odoo'
          ? 'Se genera un ZIP compatible con el gestor de bases de Odoo (base + adjuntos). Puede tardar unos minutos.'
          : 'Se genera un .dump de PostgreSQL de la base de Traccar.'}
        accion="Crear respaldo"
        alCerrar={() => setRespaldar(null)}
        alConfirmar={async (clave) => {
          if (!respaldar) return
          const r = await apiBD.respaldar(respaldar, clave)
          toast.success(`Respaldo creado: ${r.nombre} (${bytes(r.tamano_bytes)})`)
          cargar()
        }}
      />
      <DialogoClave
        key={`borrar-${borrar?.nombre}`}
        abierto={borrar !== null}
        titulo="Borrar respaldo"
        descripcion={<>Se eliminará <span className="font-mono">{borrar?.nombre}</span> del servidor. Esta acción no se puede deshacer.</>}
        accion="Borrar"
        peligro
        alCerrar={() => setBorrar(null)}
        alConfirmar={async (clave) => {
          if (!borrar) return
          await apiBD.borrar(borrar.nombre, clave)
          toast.success('Respaldo borrado')
          cargar()
        }}
      />
      <DialogoRestaurar
        key={restaurar ? `${restaurar.base}-${restaurar.archivo?.name ?? restaurar.respaldo?.nombre}` : 'cerrado'}
        origen={restaurar}
        alCerrar={() => setRestaurar(null)}
        alTerminar={(r) => { setRestaurar(null); setArchivo(null); setResultado(r); cargar(); toast.success('Restauración completada') }}
      />
    </section>
  )
}
