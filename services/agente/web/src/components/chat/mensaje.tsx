import { memo, useState } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CaretRightIcon, CheckCircleIcon, CircleNotchIcon, DatabaseIcon, LightbulbIcon, WarningCircleIcon } from '@phosphor-icons/react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { Bloque, Mensaje } from '@/lib/api'
import { cn } from '@/lib/utils'

// Markdown con estilo propio: tablas tipo libro de cuentas, cifras tabulares.
const componentes: Components = {
  p: ({ children }) => <p className="my-2.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  ul: ({ children }) => <ul className="my-2.5 list-none space-y-1.5 pl-0">{children}</ul>,
  ol: ({ children }) => <ol className="my-2.5 list-decimal space-y-1.5 pl-5 marker:font-mono marker:text-xs marker:text-muted-foreground">{children}</ol>,
  li: ({ children, ...props }) => {
    const enLista = (props as { node?: { parent?: { tagName?: string } } }).node?.parent?.tagName
    return enLista === 'ol'
      ? <li className="pl-1">{children}</li>
      : <li className="relative pl-4 before:absolute before:top-[0.6em] before:left-0 before:size-1.5 before:bg-senal">{children}</li>
  },
  h1: ({ children }) => <h3 className="mt-5 mb-2 font-heading text-base font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-5 mb-2 font-heading text-base font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-4 mb-1.5 font-heading text-sm font-semibold uppercase tracking-wide">{children}</h4>,
  a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer noopener" className="text-senal underline underline-offset-2">{children}</a>,
  code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>,
  pre: ({ children }) => <pre className="my-3 overflow-x-auto rounded-md border bg-muted/60 p-3 font-mono text-xs">{children}</pre>,
  blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-senal pl-3 text-muted-foreground">{children}</blockquote>,
  hr: () => <hr className="my-4 border-dashed" />,
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-md border bg-card">
      <table className="cifras w-full border-collapse text-[13px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b bg-muted/60">{children}</thead>,
  th: ({ children, style }) => (
    <th style={style} className="px-3 py-2 text-left font-mono text-[10.5px] font-medium uppercase tracking-[0.1em] whitespace-nowrap text-muted-foreground">
      {children}
    </th>
  ),
  td: ({ children, style }) => <td style={style} className="border-t border-dashed px-3 py-2 align-top first:font-medium">{children}</td>,
}

const Texto = memo(function Texto({ texto, escribiendo }: { texto: string; escribiendo: boolean }) {
  return (
    <div className={cn('text-[15px] text-foreground/90', escribiendo && '[&>*:last-child]:cursor-escritura')}>
      <Markdown remarkPlugins={[remarkGfm]} components={componentes}>{texto}</Markdown>
    </div>
  )
})

function entradaLegible(entrada: Record<string, unknown>) {
  const partes = Object.entries(entrada ?? {}).map(([k, v]) => `${k}: ${String(v)}`)
  return partes.length ? partes.join(' · ') : 'sin parámetros'
}

function Herramienta({ b }: { b: Extract<Bloque, { tipo: 'herramienta' }> }) {
  return (
    <div className="flex items-center gap-2.5 rounded-md border border-dashed bg-card/70 px-3 py-2 text-xs">
      <span className={cn('flex size-6 shrink-0 items-center justify-center rounded',
        b.estado === 'error' ? 'bg-destructive/10 text-destructive' : 'bg-senal-suave text-accent-foreground')}>
        <DatabaseIcon size={14} weight="bold" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em]">{b.etiqueta}</div>
        <div className="truncate font-mono text-[11px] text-muted-foreground">{entradaLegible(b.entrada)}</div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
        {b.estado === 'ejecutando' && <><CircleNotchIcon size={14} className="animate-spin text-senal" /> consultando</>}
        {b.estado === 'ok' && <><CheckCircleIcon size={14} weight="fill" className="text-ok" />{b.resumen ?? 'listo'}{b.ms != null && ` · ${(b.ms / 1000).toFixed(1)} s`}</>}
        {b.estado === 'error' && <><WarningCircleIcon size={14} weight="fill" className="text-destructive" />{b.resumen ?? 'error'}</>}
      </div>
    </div>
  )
}

function Pensamiento({ texto, activo }: { texto: string; activo: boolean }) {
  const [abierto, setAbierto] = useState(false)
  return (
    <Collapsible open={abierto} onOpenChange={setAbierto}>
      <CollapsibleTrigger className="group flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground">
        <CaretRightIcon size={12} className="transition-transform group-data-[state=open]:rotate-90" />
        <LightbulbIcon size={14} className={cn(activo && 'animate-pulse text-senal')} />
        {activo ? 'Analizando…' : 'Razonamiento'}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="mt-2 border-l-2 border-dashed pl-3 text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground">{texto}</p>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function MensajeVista({ mensaje, enCurso }: { mensaje: Mensaje; enCurso: boolean }) {
  if (mensaje.rol === 'usuario') {
    const texto = mensaje.bloques.map((b) => ('texto' in b ? b.texto : '')).join('')
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-primary px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-primary-foreground shadow-sm">
          {texto}
        </div>
      </div>
    )
  }
  const ultimo = mensaje.bloques.length - 1
  return (
    <div className="flex gap-3">
      <div className="mt-1 hidden size-7 shrink-0 items-center justify-center rounded bg-sidebar text-sidebar-primary ring-1 ring-border sm:flex">
        <span className="font-mono text-[11px] font-bold">B</span>
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {mensaje.bloques.length === 0 && enCurso && (
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            <CircleNotchIcon size={14} className="animate-spin text-senal" /> Preparando respuesta
          </div>
        )}
        {mensaje.bloques.map((b, i) => {
          switch (b.tipo) {
            case 'texto':
              return <Texto key={i} texto={b.texto} escribiendo={enCurso && i === ultimo} />
            case 'pensamiento':
              return <Pensamiento key={i} texto={b.texto} activo={enCurso && i === ultimo} />
            case 'herramienta':
              return <Herramienta key={b.id} b={b} />
            case 'error':
              return (
                <p key={i} role="alert" className="flex items-start gap-2 border-l-2 border-destructive bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  <WarningCircleIcon size={18} className="mt-0.5 shrink-0" /> {b.texto}
                </p>
              )
          }
        })}
      </div>
    </div>
  )
}
