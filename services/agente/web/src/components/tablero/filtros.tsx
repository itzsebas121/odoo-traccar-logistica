import { useState, type ReactNode } from 'react'
import { ArrowClockwiseIcon, CalendarBlankIcon, XIcon } from '@phosphor-icons/react'
import type { DateRange } from 'react-day-picker'
import { es } from 'react-day-picker/locale'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { FiltrosTablero, OpcionesTablero, Procedencia } from '@/lib/api'

import { deIso, FILTROS_DE, fmt, iso, PERIODOS, rangoDePeriodo, type Pestana, type Periodo } from './datos'

const TODOS = '__todos__'

function Campo({ etiqueta, children }: { etiqueta: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{etiqueta}</span>
      {children}
    </div>
  )
}

/** Lista desplegable de un filtro: «todas» o una opción. */
function Selector({ etiqueta, textoTodos, valor, opciones, alElegir }: {
  etiqueta: string
  textoTodos: string
  valor: string | undefined
  opciones: { valor: string; texto: string }[]
  alElegir: (v: string | undefined) => void
}) {
  return (
    <Campo etiqueta={etiqueta}>
      <Select value={valor ?? TODOS} onValueChange={(v) => alElegir(v === TODOS ? undefined : v)} disabled={!opciones.length}>
        <SelectTrigger className="w-48" aria-label={etiqueta}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="max-h-80">
          <SelectItem value={TODOS}>{textoTodos}</SelectItem>
          {opciones.map((o) => <SelectItem key={o.valor} value={o.valor}>{o.texto}</SelectItem>)}
        </SelectContent>
      </Select>
    </Campo>
  )
}

/** Barra de filtros: periodo, fechas, zona, categoría o conductor (según la pestaña) y, si hay datos de demostración, tipo de datos. */
export function Filtros({ pestana, filtros, periodo, ultimoDia, hayDemo, opciones, hayFiltros, alCambiar, alLimpiar, alRecargar, cargando }: {
  pestana: Pestana
  filtros: FiltrosTablero
  periodo: Periodo
  ultimoDia: string | null
  hayDemo: boolean
  opciones: OpcionesTablero | null
  hayFiltros: boolean
  alCambiar: (f: FiltrosTablero, periodo: Periodo) => void
  alLimpiar: () => void
  alRecargar: () => void
  cargando: boolean
}) {
  const [abierto, setAbierto] = useState(false)
  const [borrador, setBorrador] = useState<DateRange | undefined>()
  const visibles = FILTROS_DE[pestana]
  const cambiar = (parcial: FiltrosTablero) => alCambiar({ ...filtros, ...parcial }, periodo)

  function elegirPeriodo(p: string) {
    if (p === 'personalizado') {
      setBorrador(undefined)
      setAbierto(true)
      return
    }
    if (ultimoDia) alCambiar({ ...filtros, ...rangoDePeriodo(p as keyof typeof PERIODOS, ultimoDia) }, p as Periodo)
  }

  function aplicar() {
    if (!borrador?.from) return
    alCambiar({ ...filtros, desde: iso(borrador.from), hasta: iso(borrador.to ?? borrador.from) }, 'personalizado')
    setAbierto(false)
  }

  // el calendario abre en los dos meses más recientes con datos, no en el inicio del rango elegido
  const mesInicial = ultimoDia ? new Date(deIso(ultimoDia).getFullYear(), deIso(ultimoDia).getMonth() - 1, 1) : undefined

  const etiquetaRango = filtros.desde && filtros.hasta
    ? `${fmt.dia(filtros.desde)} – ${fmt.dia(filtros.hasta)}`
    : 'Elegir fechas'
  const elegido = borrador?.from
    ? `${fmt.dia(iso(borrador.from))} – ${fmt.dia(iso(borrador.to ?? borrador.from))}`
    : 'Elige el primer y el último día'

  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-3" role="group" aria-label="Filtros del tablero">
      <Campo etiqueta="Periodo">
        <Select value={periodo} onValueChange={elegirPeriodo} disabled={!ultimoDia}>
          <SelectTrigger className="w-44" aria-label="Periodo">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(PERIODOS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
            <SelectItem value="personalizado">Fechas a elegir…</SelectItem>
          </SelectContent>
        </Select>
      </Campo>

      <Campo etiqueta="Fechas">
        <Popover open={abierto} onOpenChange={(o) => { setAbierto(o); if (o) setBorrador(undefined) }}>
          <PopoverTrigger asChild>
            <Button variant="outline" className="gap-2 font-normal tabular-nums" disabled={!ultimoDia}>
              <CalendarBlankIcon size={16} aria-hidden />
              {etiquetaRango}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="range"
              locale={es}
              numberOfMonths={2}
              defaultMonth={mesInicial}
              selected={borrador}
              onSelect={setBorrador}
              disabled={ultimoDia ? { after: deIso(ultimoDia) } : undefined}
            />
            <div className="flex items-center justify-between gap-3 border-t px-3 py-2">
              <p className="text-xs text-muted-foreground tabular-nums">{elegido}</p>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => setAbierto(false)}>Cancelar</Button>
                <Button size="sm" disabled={!borrador?.from} onClick={aplicar}>Aplicar</Button>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </Campo>

      {visibles.includes('zona') && (
        <Selector etiqueta="Zona" textoTodos="Todas las zonas" valor={filtros.zona}
                  opciones={(opciones?.zonas ?? []).map((z) => ({ valor: z.codigo, texto: z.nombre }))}
                  alElegir={(v) => cambiar({ zona: v })} />
      )}
      {visibles.includes('categoria') && (
        <Selector etiqueta="Categoría" textoTodos="Todas las categorías" valor={filtros.categoria}
                  opciones={(opciones?.categorias ?? []).map((c) => ({ valor: c, texto: c }))}
                  alElegir={(v) => cambiar({ categoria: v })} />
      )}
      {visibles.includes('conductor') && (
        <Selector etiqueta="Conductor" textoTodos="Todos los conductores" valor={filtros.conductor}
                  opciones={(opciones?.conductores ?? []).map((c) => ({ valor: c, texto: c }))}
                  alElegir={(v) => cambiar({ conductor: v })} />
      )}

      {hayDemo && (
        <Campo etiqueta="Datos">
          <ToggleGroup
            type="single"
            variant="outline"
            value={filtros.procedencia ?? 'TODAS'}
            onValueChange={(v) => v && cambiar({ procedencia: v === 'TODAS' ? undefined : (v as Procedencia) })}
            aria-label="Tipo de datos"
          >
            <ToggleGroupItem value="TODAS">Todos</ToggleGroupItem>
            <ToggleGroupItem value="REAL">Reales</ToggleGroupItem>
            <ToggleGroupItem value="SIMULADO">Demostración</ToggleGroupItem>
          </ToggleGroup>
        </Campo>
      )}

      <div className="flex gap-1 sm:ml-auto">
        {hayFiltros && (
          <Button variant="ghost" onClick={alLimpiar} className="gap-2">
            <XIcon size={16} aria-hidden />
            Limpiar filtros
          </Button>
        )}
        <Button variant="ghost" onClick={alRecargar} disabled={cargando} className="gap-2">
          <ArrowClockwiseIcon size={16} className={cargando ? 'animate-spin' : ''} aria-hidden />
          Actualizar
        </Button>
      </div>
    </div>
  )
}
