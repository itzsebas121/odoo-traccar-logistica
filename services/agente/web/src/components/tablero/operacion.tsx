import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from 'recharts'

import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { OperacionTablero } from '@/lib/api'

import { Kpi, Panel, SinDatos, VerDatos } from './comun'
import { fmt } from './datos'
import { Fila } from './resumen'

// Resultado de una entrega: colores de estado, siempre con su nombre en la leyenda y el tooltip.
const RESULTADO: ChartConfig = {
  entregado: { label: 'Entregadas', color: 'var(--estado-ok)' },
  no_entregado: { label: 'No entregadas', color: 'var(--estado-critico)' },
  pendiente: { label: 'Pendientes', color: 'var(--estado-aviso)' },
}
const KM: ChartConfig = {
  km_plan: { label: 'Planificado', color: 'var(--serie-1)' },
  km_real: { label: 'Recorrido', color: 'var(--serie-2)' },
}

export function Operacion({ datos }: { datos: OperacionTablero }) {
  const k = datos.kpi
  const dias = useMemo(() => {
    const m = new Map<string, Record<string, number | string>>()
    for (const r of datos.por_dia) {
      const d = m.get(r.fecha) ?? { fecha: r.fecha, entregado: 0, no_entregado: 0, pendiente: 0 }
      d[r.resultado] = Number(d[r.resultado] ?? 0) + r.entregas
      m.set(r.fecha, d)
    }
    return [...m.values()].sort((a, b) => String(a.fecha).localeCompare(String(b.fecha)))
  }, [datos.por_dia])
  const resultados = (['entregado', 'no_entregado', 'pendiente'] as const).filter((r) => dias.some((d) => Number(d[r]) > 0))
  const desvio = k.km_planificado ? (100 * (k.km_real - k.km_planificado)) / k.km_planificado : null

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <Kpi titulo="Entregas" valor={fmt.entero(k.entregas)}
             detalle={`${fmt.entero(k.entregadas)} entregadas · ${fmt.entero(k.no_entregadas)} no entregadas · ${fmt.entero(k.pendientes)} pendientes`} />
        <Kpi titulo="A tiempo" valor={fmt.pct(k.pct_a_tiempo)} />
        <Kpi titulo="Entregas con GPS" valor={fmt.pct(k.pct_vinculadas_gps)} />
        <Kpi titulo="Km planificados / reales" valor={`${fmt.entero(k.km_planificado)} / ${fmt.entero(k.km_real)}`}
             detalle={`${fmt.entero(k.rutas)} rutas${desvio == null ? '' : ` · desvío ${desvio >= 0 ? '+' : ''}${fmt.decimal(desvio)} %`}`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel titulo="Entregas por día" className="xl:col-span-2">
          {dias.length === 0 ? <SinDatos>Sin entregas en el periodo.</SinDatos> : (
            <>
              <ChartContainer config={RESULTADO} className="aspect-auto h-72 w-full">
                <BarChart data={dias} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="fecha" tickLine={false} axisLine={false} tickMargin={8} minTickGap={24} tickFormatter={fmt.dia} />
                  <YAxis tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                  <ChartTooltip cursor={false} content={<ChartTooltipContent labelFormatter={(v) => fmt.diaLargo(String(v))}
                    formatter={(v, n) => <Fila nombre={RESULTADO[String(n)]?.label} valor={fmt.entero(Number(v))} color={`var(--color-${n})`} />} />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  {resultados.map((r, i) => (
                    <Bar key={r} dataKey={r} stackId="e" fill={`var(--color-${r})`} stroke="var(--card)" strokeWidth={1}
                         radius={i === resultados.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={28} />
                  ))}
                </BarChart>
              </ChartContainer>
              <VerDatos filas={dias} columnas={[
                { clave: 'fecha', titulo: 'Día', formato: (v: string) => fmt.diaLargo(v) },
                { clave: 'entregado', titulo: 'Entregadas' },
                { clave: 'no_entregado', titulo: 'No entregadas' },
                { clave: 'pendiente', titulo: 'Pendientes' },
              ]} />
            </>
          )}
        </Panel>

        <Panel titulo="Km por conductor">
          {datos.conductores.length === 0 ? <SinDatos>Sin rutas medidas en el periodo.</SinDatos> : (
            <>
              <ChartContainer config={KM} className="aspect-auto w-full"
                              style={{ height: Math.max(180, datos.conductores.length * 64 + 56) }}>
                <BarChart data={datos.conductores} layout="vertical" margin={{ left: 4, right: 48 }} barGap={2}>
                  <CartesianGrid horizontal={false} />
                  <YAxis dataKey="conductor" type="category" tickLine={false} axisLine={false} width={80} />
                  <XAxis type="number" hide />
                  <ChartTooltip cursor={false} content={<ChartTooltipContent
                    formatter={(v, n) => <Fila nombre={KM[String(n)]?.label} valor={`${fmt.decimal(Number(v))} km`} color={`var(--color-${n})`} />} />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Bar dataKey="km_plan" fill="var(--color-km_plan)" radius={[0, 4, 4, 0]} maxBarSize={16} />
                  <Bar dataKey="km_real" fill="var(--color-km_real)" radius={[0, 4, 4, 0]} maxBarSize={16}>
                    <LabelList dataKey="km_real" position="right" className="fill-foreground font-mono text-[11px]"
                               formatter={(v) => fmt.entero(Number(v))} />
                  </Bar>
                </BarChart>
              </ChartContainer>
              <VerDatos filas={datos.conductores} columnas={[
                { clave: 'conductor', titulo: 'Conductor' },
                { clave: 'rutas', titulo: 'Rutas', formato: (v: number) => fmt.entero(v) },
                { clave: 'km_plan', titulo: 'Km planificados', formato: (v: number | null) => fmt.decimal(v) },
                { clave: 'km_real', titulo: 'Km recorridos', formato: (v: number | null) => fmt.decimal(v) },
              ]} />
            </>
          )}
        </Panel>
      </div>

      <Panel titulo="Rutas: plan y real">
        {datos.rutas.length === 0 ? <SinDatos>Sin rutas planificadas en el periodo.</SinDatos> : (
          <div className="max-h-96 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ruta</TableHead>
                  <TableHead>Día</TableHead>
                  <TableHead>Conductor</TableHead>
                  <TableHead className="text-right">Km plan</TableHead>
                  <TableHead className="text-right">Km real</TableHead>
                  <TableHead className="text-right">Desvío km</TableHead>
                  <TableHead className="text-right">Min plan</TableHead>
                  <TableHead className="text-right">Min real</TableHead>
                  <TableHead className="text-right">Entregado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {datos.rutas.map((r) => (
                  <TableRow key={r.codigo}>
                    <TableCell className="font-mono">{r.codigo}</TableCell>
                    <TableCell>{fmt.dia(r.fecha)}</TableCell>
                    <TableCell>{r.conductor ?? '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt.decimal(r.km_planificado)}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.km_real == null ? <span className="text-muted-foreground">sin medir</span> : fmt.decimal(r.km_real)}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.desviacion_km_pct == null ? '—' : `${r.desviacion_km_pct > 0 ? '+' : ''}${fmt.decimal(r.desviacion_km_pct)} %`}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt.entero(r.min_planificado)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt.entero(r.min_real)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt.pct(r.pct_entregado)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Panel>
    </div>
  )
}
