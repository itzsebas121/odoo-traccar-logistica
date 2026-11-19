import { useEffect, useRef, type KeyboardEvent } from 'react'
import { ArrowUpIcon, StopIcon } from '@phosphor-icons/react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function Compositor({ valor, alCambiar, alEnviar, alDetener, ocupado }: {
  valor: string
  alCambiar: (v: string) => void
  alEnviar: () => void
  alDetener: () => void
  ocupado: boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // Crece con el contenido hasta ~8 líneas.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [valor])

  useEffect(() => {
    if (!ocupado) ref.current?.focus()
  }, [ocupado])

  function teclas(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (!ocupado && valor.trim()) alEnviar()
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-3 sm:px-4 md:pb-6">
      <div className={cn(
        'flex items-end gap-2 rounded-xl border bg-card p-2 pl-4 shadow-[0_10px_30px_-18px_oklch(0.23_0.025_258/40%)] transition-colors',
        'focus-within:border-senal/60',
      )}>
        <textarea
          ref={ref}
          rows={1}
          value={valor}
          onChange={(e) => alCambiar(e.target.value)}
          onKeyDown={teclas}
          maxLength={4000}
          placeholder="Pregunta por clientes, ventas, facturas o la flota…"
          aria-label="Mensaje para el asistente"
          className="max-h-[220px] min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground/70"
        />
        {ocupado ? (
          <Button type="button" size="icon-lg" variant="outline" onClick={alDetener} aria-label="Detener respuesta" className="rounded-lg">
            <StopIcon weight="fill" />
          </Button>
        ) : (
          <Button type="button" size="icon-lg" onClick={alEnviar} disabled={!valor.trim()} aria-label="Enviar"
            className="rounded-lg bg-senal text-white hover:bg-senal/85">
            <ArrowUpIcon weight="bold" />
          </Button>
        )}
      </div>
      <p className="mt-2 hidden text-center font-mono sm:block text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70">
        Solo lectura · Las cifras salen de Odoo · Enter envía, Shift+Enter salta de línea
      </p>
    </div>
  )
}
