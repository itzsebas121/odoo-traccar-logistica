import { useMemo, type ReactNode } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, XAxis, YAxis,
} from 'recharts'

import { Button } from '@/components/ui/button'
import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from '@/components/ui/chart'
import type { ResumenTablero } from '@/lib/api'

import { Kpi, Panel, SinDatos, VerDatos } from './comun'
import { fmt } from './datos'

const PROCEDENCIA: ChartConfig = {
  REAL: { label: 'Reales', color: 'var(--serie-1)' },
  SIMULADO: { label: 'Simulados', color: 'var(--serie-2)' },
}
const PEDIDOS: ChartConfig = { pedidos: { label: 'Pedidos', color: 'var(--serie-1)' } }
const MAX_BARRAS = 45

type Dia = { fecha: string; REAL: number; SIMULADO: number; pedidos: number; unidades: number }

export function Resumen({ datos, alVerPronostico }: { datos: ResumenTablero; alVerPronostico: () => void }) {
  const { kpi } = datos
  const dias = useMemo(() => {
    const porDia = new Map<string, Dia>()
    for (const r of datos.serie) {
      const d = porDia.get(r.fecha) ?? { fecha: r.fecha, REAL: 0, SIMULADO: 0, pedidos: 0, unidades: 0 }
      d[r.procedencia] += r.importe
      d.pedidos += r.pedidos
      d.unidades += r.unidades
      porDia.set(r.fecha, d)
    }
    return [...porDia.values()].sort((a, b) => a.fecha.localeCompare(b.fecha))
  }, [datos.serie])
  const series = (['REAL', 'SIMULADO'] as const).filter((p) => dias.some((d) => d[p] > 0))
  const barras = dias.length <= MAX_BARRAS

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <Kpi titulo="Ventas" valor={fmt.dinero(kpi.importe)} variacion={kpi.variacion_importe_7d} />
        <Kpi titulo="Pedidos" valor={fmt.entero(kpi.pedidos)} variacion={kpi.variacion_pedidos_7d} />
        <Kpi titulo="Ticket promedio" valor={fmt.dineroExacto(kpi.ticket)} />
        <Kpi titulo="Unidades vendidas" valor={fmt.entero(kpi.unidades)} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel titulo="Ventas por día" className="xl:col-span-2">
          {dias.length === 0 ? <SinDatos>Sin ventas en el periodo.</SinDatos> : (
            <>
              <ChartContainer config={PROCEDENCIA} className="aspect-auto h-72 w-full">
                {barras ? (
                  <BarChart data={dias} margin={{ left: 4, right: 8 }}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="fecha" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24}
                           tickFormatter={fmt.dia} />
                    <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={(v) => fmt.dinero(v)} />
                    <ChartTooltip cursor={false} content={<ChartTooltipContent labelFormatter={(v) => fmt.diaLargo(String(v))}
                      formatter={(v, n) => <Fila nombre={PROCEDENCIA[String(n)]?.label} valor={fmt.dineroExacto(Number(v))} color={`var(--color-${n})`} />} />} />
                    {series.length > 1 && <ChartLegend content={<ChartLegendContent />} />}
                    {series.map((s, i) => (
                      <Bar key={s} dataKey={s} stackId="v" fill={`var(--color-${s})`} stroke="var(--card)" strokeWidth={1}
                           radius={i === series.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={28} />
                    ))}
                  </BarChart>
                ) : (
                  <AreaChart data={dias} margin={{ left: 4, right: 8 }}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="fecha" tickLine={false} axisLine={false} tickMargin={8} minTickGap={32}
                           tickFormatter={fmt.dia} />
                    <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={(v) => fmt.dinero(v)} />
                    <ChartTooltip content={<ChartTooltipContent labelFormatter={(v) => fmt.diaLargo(String(v))}
                      formatter={(v, n) => <Fila nombre={PROCEDENCIA[String(n)]?.label} valor={fmt.dineroExacto(Number(v))} color={`var(--color-${n})`} />} />} />
                    {series.length > 1 && <ChartLegend content={<ChartLegendContent />} />}
                    {series.map((s) => (
                      <Area key={s} dataKey={s} stackId="v" type="monotone" fill={`var(--color-${s})`} fillOpacity={0.25}
                            stroke={`var(--color-${s})`} strokeWidth={2} />
                    ))}
                  </AreaChart>
                )}
              </ChartContainer>
              <VerDatos filas={dias} columnas={[
                { clave: 'fecha', titulo: 'Día', formato: (v: string) => fmt.diaLargo(v) },
                { clave: 'REAL', titulo: 'Reales', formato: (v: number) => fmt.dineroExacto(v) },
                { clave: 'SIMULADO', titulo: 'Simulados', formato: (v: number) => fmt.dineroExacto(v) },
                { clave: 'pedidos', titulo: 'Pedidos', formato: (v: number) => fmt.entero(v) },
              ]} />
            </>
          )}
        </Panel>

        <Panel titulo="Pedidos por día">
          {dias.length === 0 ? <SinDatos>Sin pedidos.</SinDatos> : (
            <ChartContainer config={PEDIDOS} className="aspect-auto h-72 w-full">
              <LineChart data={dias} margin={{ left: 0, right: 8 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="fecha" tickLine={false} axisLine={false} tickMargin={8} minTickGap={32}
                       tickFormatter={fmt.dia} />
                <YAxis tickLine={false} axisLine={false} width={36} allowDecimals={false} />
                <ChartTooltip content={<ChartTooltipContent labelFormatter={(v) => fmt.diaLargo(String(v))} />} />
                <Line dataKey="pedidos" type="monotone" stroke="var(--color-pedidos)" strokeWidth={2} dot={false}
                      activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} />
              </LineChart>
            </ChartContainer>
          )}
        </Panel>
      </div>

      <PronosticoNegocio filas={datos.pronostico_total} alVer={alVerPronostico} />
    </div>
  )
}

const PRONOSTICO: ChartConfig = {
  real: { label: 'Vendido', color: 'var(--serie-1)' },
  pronostico: { label: 'Pronóstico', color: 'var(--serie-2)' },
}

/** Pronóstico de todo el negocio (suma de productos) con la zona y la categoría elegidas. */
function PronosticoNegocio({ filas, alVer }: { filas: ResumenTablero['pronostico_total']; alVer: () => void }) {
  const proximos = filas.filter((f) => f.tipo === 'pronostico')
  const total = proximos.reduce((s, f) => s + f.pronostico, 0)
  const vendido = filas.filter((f) => f.tipo === 'backtest').reduce((s, f) => s + (f.real ?? 0), 0)
  const cambio = vendido > 0 ? (100 * (total - vendido)) / vendido : null
  const datos = filas.map((f) => ({ fecha: f.fecha, pronostico: f.pronostico, real: f.tipo === 'backtest' ? f.real : null }))
  const inicioFuturo = proximos[0]?.fecha

  return (
    <Panel titulo="Pronóstico de ventas"
           accion={<Button variant="outline" size="sm" onClick={alVer}>Ver por producto y zona</Button>}>
      {filas.length === 0 ? (
        <SinDatos>Todavía no hay pronóstico para esta selección.</SinDatos>
      ) : (
        <div className="grid gap-4 lg:grid-cols-4">
          <dl className="grid grid-cols-3 gap-3 lg:grid-cols-1 lg:content-start lg:gap-4">
            <div>
              <dt className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Próximos 7 días</dt>
              <dd className="font-heading text-2xl font-semibold tabular-nums">{fmt.entero(total)} u.</dd>
            </div>
            <div>
              <dt className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Última semana</dt>
              <dd className="font-heading text-2xl font-semibold tabular-nums">{fmt.entero(vendido)} u.</dd>
            </div>
            <div>
              <dt className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Cambio esperado</dt>
              <dd className="font-heading text-2xl font-semibold tabular-nums">
                {cambio == null ? '—' : `${cambio >= 0 ? '+' : '−'}${fmt.pct(Math.abs(cambio))}`}
              </dd>
            </div>
          </dl>
          <ChartContainer config={PRONOSTICO} className="aspect-auto h-60 w-full lg:col-span-3">
            <ComposedChart data={datos} margin={{ left: 0, right: 12, top: 12 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="fecha" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} tickFormatter={fmt.dia} />
              <YAxis tickLine={false} axisLine={false} width={44} allowDecimals={false} />
              <ChartTooltip content={<ChartTooltipContent labelFormatter={(v) => fmt.diaLargo(String(v))}
                formatter={(v, n) => <Fila nombre={PRONOSTICO[String(n)]?.label} valor={`${fmt.decimal(Number(v))} u.`} color={`var(--color-${n})`} />} />} />
              <ChartLegend content={<ChartLegendContent />} />
              {inicioFuturo && (
                <ReferenceLine x={inicioFuturo} stroke="var(--muted-foreground)" strokeDasharray="4 4"
                               label={{ value: 'Pronóstico →', position: 'insideTopLeft', fill: 'var(--muted-foreground)', fontSize: 11 }} />
              )}
              <Line dataKey="real" type="monotone" stroke="var(--color-real)" strokeWidth={2} dot={false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} connectNulls={false} />
              <Line dataKey="pronostico" type="monotone" stroke="var(--color-pronostico)" strokeWidth={2}
                    strokeDasharray="6 3" dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} />
            </ComposedChart>
          </ChartContainer>
        </div>
      )}
    </Panel>
  )
}

/** Fila del tooltip: marca de color + nombre en tinta normal + valor. */
export function Fila({ nombre, valor, color }: { nombre?: ReactNode; valor: string; color: string }) {
  return (
    <div className="flex w-full items-center gap-2">
      <span className="size-2.5 shrink-0 rounded-[2px]" style={{ background: color }} aria-hidden />
      <span className="text-muted-foreground">{nombre}</span>
      <span className="ml-auto font-mono font-medium tabular-nums text-foreground">{valor}</span>
    </div>
  )
}
