import { useMemo, useRef, useState } from 'react'
import { XIcon } from '@phosphor-icons/react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, XAxis, YAxis } from 'recharts'

import { Button } from '@/components/ui/button'
import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { apiTablero, urlTablero, type FiltrosTablero, type PronosticoDetalle, type PronosticoTablero } from '@/lib/api'

import { Panel, SinDatos } from './comun'
import { fmt, useSeccion } from './datos'
import { PronosticoMapa } from './pronostico-mapa'
import { IconoTendencia, PronosticoMatriz } from './pronostico-matriz'
import {
  cambioPct, cambioTexto, cambios, calidad, porProducto, porZona, signo, total, type Foco, type FilaProducto,
} from './pronostico-calculos'
import { Fila } from './resumen'

const CONFIG: ChartConfig = {
  real: { label: 'Vendido', color: 'var(--serie-1)' },
  pronostico: { label: 'Pronóstico', color: 'var(--serie-2)' },
  banda: { label: 'Rango probable (8 de 10)', color: 'var(--serie-2)' },
}
const MAX_LISTA = 8

type Props = {
  datos: PronosticoTablero
  filtros: FiltrosTablero
  vuelta: number
  alSesionCaducada: () => void
}

/**
 * Pronóstico de los próximos 7 días pensado para decidir qué llevar a cada zona: una frase de resumen, el mapa de zonas,
 * lo que más sube y baja, y la hoja de reposición (producto × zona). Mapa, listas y hoja comparten el mismo enfoque:
 * tocar una zona o un producto lo enfoca en todo. Sin enfoque se ve todo el negocio.
 */
export function Pronostico({ datos, filtros, vuelta, alSesionCaducada }: Props) {
  const [foco, setFoco] = useState<Foco>({})
  const detalle = useRef<HTMLDivElement>(null)
  const { celdas, zonas } = datos

  const nombreZona = (c: string) => zonas.find((z) => z.codigo === c)?.nombre ?? c
  const todo = useMemo(() => total(celdas), [celdas])
  const productos = useMemo(() => porProducto(celdas), [celdas])
  const zonasTotales = useMemo(() => porZona(celdas), [celdas])
  const { suben, bajan } = useMemo(() => cambios(productos), [productos])

  if (!celdas.length) {
    return <Panel titulo="Pronóstico de demanda"><SinDatos>{datos.aviso ?? 'Sin pronóstico.'}</SinDatos></Panel>
  }

  const cambioTotal = cambioPct(todo.unidades, todo.vendido)
  const q = calidad(productos)
  const lider = zonasTotales[0]
  const parteLider = todo.unidades > 0 ? Math.round((100 * lider.unidades) / todo.unidades) : 0

  /** Enfoca desde la hoja o las listas y lleva la vista al detalle, que queda arriba. */
  function enfocar(f: Foco) {
    setFoco(f)
    detalle.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  return (
    <div className="grid gap-5">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-y py-4 md:grid-cols-4">
        <Cifra titulo="Próximos 7 días" valor={`${fmt.entero(todo.unidades)} u.`}
               extra={cambioTotal == null ? undefined : signo(cambioTotal)}
               ayuda={datos.actualizado_utc ? `Pronóstico actualizado el ${fmt.fechaHora(datos.actualizado_utc)}` : undefined} />
        {zonasTotales.length > 1 && <Cifra titulo="Zona principal" valor={nombreZona(lider.zona)} extra={`${parteLider} %`} />}
        <Cifra titulo="Suben / bajan" valor={`${suben.length} / ${bajan.length}`}
               ayuda="Productos que cambian más de 5 % frente a lo vendido la semana pasada" />
        {q && <Cifra titulo="Error semana pasada" valor={fmt.pct(q.errorProducto)}
                     ayuda={`Pronosticado ${fmt.entero(q.pronosticado)} u., vendido ${fmt.entero(q.vendido)} u. Error por producto: suma de las diferencias de cada producto entre lo pronosticado y lo vendido, dividida entre lo vendido. Lo que sobra en un producto no compensa lo que falta en otro.`} />}
      </dl>

      <div ref={detalle} className="grid scroll-mt-28 gap-4 xl:grid-cols-5">
        <Panel titulo="Dónde se necesitará" className="xl:col-span-3">
          <PronosticoMapa zonas={zonas} valores={porZona(celdas, foco.producto)} elegida={foco.zona}
                          alElegir={(zona) => setFoco({ ...foco, zona })} />
        </Panel>

        <Detalle className="xl:col-span-2" foco={foco} celdas={celdas} nombreZona={nombreZona} filtros={filtros}
                 vuelta={vuelta} alSesionCaducada={alSesionCaducada} alEnfocar={setFoco} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Cambios titulo="Suben más" vacio="Ningún producto sube más de 5 %." filas={suben.slice(0, 5)} alElegir={(sk) => enfocar({ ...foco, producto: sk })} />
        <Cambios titulo="Bajan más" vacio="Ningún producto baja más de 5 %." filas={bajan.slice(0, 5)} alElegir={(sk) => enfocar({ ...foco, producto: sk })} />
      </div>

      <Panel titulo="Hoja de reposición">
        <PronosticoMatriz celdas={celdas} zonas={zonas} foco={foco} alEnfocar={enfocar} />
      </Panel>
    </div>
  )
}

/** Una cifra con su nombre corto. Lo que hay que aclarar va en `ayuda` (texto al pasar el cursor), no en pantalla. */
function Cifra({ titulo, valor, extra, ayuda }: { titulo: string; valor: string; extra?: string; ayuda?: string }) {
  return (
    <div title={ayuda}>
      <dt className="text-sm text-muted-foreground">{titulo}</dt>
      <dd className="mt-0.5 flex items-baseline gap-2">
        <span className="font-heading text-2xl font-semibold tabular-nums tracking-tight">{valor}</span>
        {extra && <span className="font-mono text-sm tabular-nums text-muted-foreground">{extra}</span>}
      </dd>
    </div>
  )
}

// ------------------------------------------------------------------ detalle del enfoque
function Detalle({ foco, celdas, nombreZona, filtros, vuelta, alSesionCaducada, alEnfocar, className }: {
  foco: Foco
  celdas: PronosticoTablero['celdas']
  nombreZona: (c: string) => string
  filtros: FiltrosTablero
  vuelta: number
  alSesionCaducada: () => void
  alEnfocar: (f: Foco) => void
  className?: string
}) {
  const producto = foco.producto !== undefined ? celdas.find((c) => c.producto_sk === foco.producto)?.producto : undefined
  const url = urlTablero('pronostico_detalle', { ...filtros, zona: foco.zona ?? filtros.zona }, { producto_sk: foco.producto })
  const serie = useSeccion(() => apiTablero.obtener<PronosticoDetalle>(url), [url, vuelta], alSesionCaducada)

  const etiqueta = producto && foco.zona ? `${producto} en ${nombreZona(foco.zona)}`
    : producto ?? (foco.zona ? nombreZona(foco.zona) : 'Todo el negocio')

  // Con un producto enfocado la lista dice en qué zonas se necesita; si no, qué productos se piden más.
  const lista = foco.producto !== undefined
    ? porZona(celdas, foco.producto).map((z) => ({
        clave: z.zona, nombre: nombreZona(z.zona), unidades: z.unidades, vendido: z.vendido,
        activo: foco.zona === z.zona, alElegir: () => alEnfocar({ ...foco, zona: foco.zona === z.zona ? undefined : z.zona }),
      }))
    : porProducto(celdas, foco.zona).slice(0, MAX_LISTA).map((p) => ({
        clave: String(p.producto_sk), nombre: p.producto, unidades: p.unidades, vendido: p.vendido, activo: false,
        alElegir: () => alEnfocar({ ...foco, producto: p.producto_sk }),
      }))
  const maximo = Math.max(...lista.map((f) => f.unidades), 1)
  const tituloLista = foco.producto !== undefined ? 'Dónde se necesita'
    : foco.zona ? `Qué necesita ${nombreZona(foco.zona)}` : 'Lo más demandado'

  return (
    <Panel titulo={etiqueta} className={className}
           accion={(foco.zona !== undefined || foco.producto !== undefined) ? (
             <Button variant="outline" size="sm" className="gap-1.5" onClick={() => alEnfocar({})}>
               <XIcon size={14} aria-hidden />Ver todo el negocio
             </Button>
           ) : undefined}>
      {serie.error ? <SinDatos>No se pudo cargar el detalle.</SinDatos> : !serie.datos ? <Skeleton className="h-52" /> : (
        <GraficoDia serie={serie.datos.serie} />
      )}

      <h3 className="mb-1 mt-5 text-sm font-medium">{tituloLista}</h3>
      <ul className="space-y-0.5">
        {lista.map((f) => (
          <li key={f.clave}>
            <button type="button" onClick={f.alElegir} aria-pressed={f.activo}
                    className={`grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 rounded-sm px-2 py-1.5 text-left hover:bg-muted ${f.activo ? 'bg-muted' : ''}`}>
              <span className="truncate text-sm" title={f.nombre}>{f.nombre}</span>
              <span className="inline-flex items-center gap-2 font-mono text-sm tabular-nums">
                {fmt.entero(f.unidades)} u.
                <span className="inline-flex w-20 items-center justify-end gap-0.5 text-xs text-muted-foreground">
                  <IconoTendencia unidades={f.unidades} vendido={f.vendido} />
                  {cambioTexto(f.unidades, f.vendido)}
                </span>
              </span>
              <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span className="block h-full rounded-full bg-[var(--serie-2)]" style={{ width: `${(100 * f.unidades) / maximo}%` }} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

/** Etiqueta el final de una línea con su nombre (mejor que obligar a mirar la leyenda). */
function etiquetaFinal(indice: number, texto: string, color: string) {
  return function EtiquetaFinal(props: { x?: number | string; y?: number | string; index?: number }) {
    if (props.index !== indice || props.x == null || props.y == null) return null
    return <text x={Number(props.x) + 6} y={Number(props.y)} dy={4} fill={color} fontSize={11} fontWeight={600}>{texto}</text>
  }
}

function GraficoDia({ serie }: { serie: PronosticoDetalle['serie'] }) {
  const datos = serie.map((p) => ({ ...p, banda: p.p10 != null && p.p90 != null ? [p.p10, p.p90] : null }))
  const inicioFuturo = serie.find((p) => p.tipo === 'pronostico')?.fecha
  const conBanda = datos.some((d) => d.banda)
  const ultimoReal = datos.reduce((u, d, i) => (d.real != null ? i : u), -1)
  const ultimoPronostico = datos.reduce((u, d, i) => (d.pronostico != null ? i : u), -1)
  return (
    <>
      <ChartContainer config={CONFIG} className="aspect-auto h-52 w-full">
        <ComposedChart data={datos} margin={{ left: 0, right: 64, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="fecha" tickLine={false} axisLine={false} tickMargin={8} minTickGap={28} tickFormatter={fmt.dia} />
          <YAxis tickLine={false} axisLine={false} width={40} allowDecimals={false} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(v) => fmt.diaLargo(String(v))}
            formatter={(v, n) => {
              if (n === 'banda' && Array.isArray(v)) {
                return <Fila nombre="Rango probable" valor={`${fmt.decimal(v[0])} – ${fmt.decimal(v[1])}`} color="var(--serie-2)" />
              }
              return <Fila nombre={CONFIG[String(n)]?.label} valor={`${fmt.decimal(Number(v))} u.`} color={`var(--color-${n})`} />
            }} />} />
          <ChartLegend content={<ChartLegendContent />} />
          {inicioFuturo && datos.length > 0 && (
            <ReferenceArea x1={inicioFuturo} x2={datos[datos.length - 1].fecha} fill="var(--muted)" fillOpacity={0.55} ifOverflow="visible" />
          )}
          {conBanda && <Area dataKey="banda" type="monotone" fill="var(--color-banda)" fillOpacity={0.15} stroke="none"
                             connectNulls={false} isAnimationActive={false} />}
          <Line dataKey="real" type="monotone" stroke="var(--color-real)" strokeWidth={2} dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} connectNulls={false}
                label={etiquetaFinal(ultimoReal, 'Vendido', 'var(--color-real)') as never} />
          <Line dataKey="pronostico" type="monotone" stroke="var(--color-pronostico)" strokeWidth={2}
                strokeDasharray="6 3" dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }}
                label={etiquetaFinal(ultimoPronostico, 'Pronóstico', 'var(--color-pronostico)') as never} />
        </ComposedChart>
      </ChartContainer>
    </>
  )
}

// ------------------------------------------------------------------ lo que más sube y baja
function Cambios({ titulo, vacio, filas, alElegir }: {
  titulo: string
  vacio: string
  filas: (FilaProducto & { cambio: number; diferencia: number })[]
  alElegir: (sk: number) => void
}) {
  return (
    <Panel titulo={titulo}>
      {filas.length === 0 ? <SinDatos>{vacio}</SinDatos> : (
        <ul className="divide-y">
          {filas.map((f) => (
            <li key={f.producto_sk}>
              <button type="button" onClick={() => alElegir(f.producto_sk)}
                      className="flex w-full items-center justify-between gap-3 px-1 py-2 text-left hover:bg-muted">
                <span className="min-w-0">
                  <span className="block truncate text-sm" title={f.producto}>{f.producto}</span>
                  <span className="block font-mono text-xs tabular-nums text-muted-foreground">
                    de {fmt.entero(f.vendido)} a {fmt.entero(f.unidades)} u.
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end font-mono tabular-nums">
                  <span className="inline-flex items-center gap-1 text-sm font-medium">
                    <IconoTendencia unidades={f.unidades} vendido={f.vendido} />
                    {f.diferencia >= 0 ? '+' : '−'}{fmt.entero(Math.abs(f.diferencia))} u.
                  </span>
                  <span className="text-xs text-muted-foreground">{signo(f.cambio)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
