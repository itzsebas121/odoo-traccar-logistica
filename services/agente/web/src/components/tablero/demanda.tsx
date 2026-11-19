import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from 'recharts'

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { DemandaTablero } from '@/lib/api'

import { Panel, SinDatos, VerDatos } from './comun'
import { fmt } from './datos'
import { MapaDemanda } from './mapa'
import { Fila } from './resumen'

const CATEGORIA: ChartConfig = { importe: { label: 'Ventas', color: 'var(--serie-1)' } }
const MAX_CATEGORIAS = 10

export function Demanda({ datos }: { datos: DemandaTablero }) {
  // más de MAX_CATEGORIAS: el resto se agrupa en «Otras» (nunca un color nuevo por categoría)
  const ordenadas = [...datos.categorias].sort((a, b) => b.importe - a.importe)
  const categorias = ordenadas.length > MAX_CATEGORIAS
    ? [...ordenadas.slice(0, MAX_CATEGORIAS - 1), ordenadas.slice(MAX_CATEGORIAS - 1).reduce(
        (o, c) => ({ ...o, unidades: o.unidades + c.unidades, importe: o.importe + c.importe, pedidos: o.pedidos + c.pedidos }),
        { categoria: 'Otras', unidades: 0, importe: 0, pedidos: 0 })]
    : ordenadas

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel titulo="Ventas por categoría">
          {categorias.length === 0 ? <SinDatos>Sin ventas en el periodo.</SinDatos> : (
            <>
              <ChartContainer config={CATEGORIA} className="aspect-auto w-full"
                              style={{ height: Math.max(160, categorias.length * 34 + 24) }}>
                <BarChart data={categorias} layout="vertical" margin={{ left: 4, right: 64 }}>
                  <CartesianGrid horizontal={false} />
                  <YAxis dataKey="categoria" type="category" tickLine={false} axisLine={false} width={120} />
                  <XAxis type="number" hide />
                  <ChartTooltip cursor={false} content={<ChartTooltipContent hideIndicator
                    formatter={(v, _n, item) => (
                      <div className="grid gap-1">
                        <Fila nombre="Ventas" valor={fmt.dineroExacto(Number(v))} color="var(--serie-1)" />
                        <span className="text-muted-foreground">{fmt.entero(item.payload.unidades)} unidades · {fmt.entero(item.payload.pedidos)} pedidos</span>
                      </div>
                    )} />} />
                  <Bar dataKey="importe" fill="var(--color-importe)" radius={[0, 4, 4, 0]} maxBarSize={22}>
                    <LabelList dataKey="importe" position="right" className="fill-foreground font-mono text-[11px]"
                               formatter={(v) => fmt.dinero(Number(v))} />
                  </Bar>
                </BarChart>
              </ChartContainer>
              <VerDatos filas={categorias} columnas={[
                { clave: 'categoria', titulo: 'Categoría' },
                { clave: 'importe', titulo: 'Ventas', formato: (v: number) => fmt.dineroExacto(v) },
                { clave: 'unidades', titulo: 'Unidades', formato: (v: number) => fmt.entero(v) },
                { clave: 'pedidos', titulo: 'Pedidos', formato: (v: number) => fmt.entero(v) },
              ]} />
            </>
          )}
        </Panel>

        <Panel titulo="Ventas por zona">
          {datos.zonas.length === 0 ? <SinDatos>Sin ventas en el periodo.</SinDatos> : (
            <>
              <ChartContainer config={CATEGORIA} className="aspect-auto w-full"
                              style={{ height: Math.max(160, datos.zonas.length * 34 + 24) }}>
                <BarChart data={datos.zonas} layout="vertical" margin={{ left: 4, right: 64 }}>
                  <CartesianGrid horizontal={false} />
                  <YAxis dataKey="nombre" type="category" tickLine={false} axisLine={false} width={120} />
                  <XAxis type="number" hide />
                  <ChartTooltip cursor={false} content={<ChartTooltipContent hideIndicator
                    formatter={(v, _n, item) => (
                      <div className="grid gap-1">
                        <Fila nombre="Ventas" valor={fmt.dineroExacto(Number(v))} color="var(--serie-1)" />
                        <span className="text-muted-foreground">{fmt.entero(item.payload.unidades)} unidades · {fmt.entero(item.payload.pedidos)} pedidos</span>
                      </div>
                    )} />} />
                  <Bar dataKey="importe" fill="var(--color-importe)" radius={[0, 4, 4, 0]} maxBarSize={22}>
                    <LabelList dataKey="importe" position="right" className="fill-foreground font-mono text-[11px]"
                               formatter={(v) => fmt.dinero(Number(v))} />
                  </Bar>
                </BarChart>
              </ChartContainer>
              <VerDatos filas={datos.zonas} columnas={[
                { clave: 'nombre', titulo: 'Zona' },
                { clave: 'importe', titulo: 'Ventas', formato: (v: number) => fmt.dineroExacto(v) },
                { clave: 'unidades', titulo: 'Unidades', formato: (v: number) => fmt.entero(v) },
                { clave: 'pedidos', titulo: 'Pedidos', formato: (v: number) => fmt.entero(v) },
              ]} />
            </>
          )}
        </Panel>
      </div>

      <Panel titulo="Dónde se vende">
        <MapaDemanda puntos={datos.puntos} />
      </Panel>

      <Panel titulo="Los 5 más vendidos por zona">
        {datos.top_por_zona.length === 0 ? <SinDatos>Sin ventas en el periodo.</SinDatos> : (
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {datos.top_por_zona.map((z) => {
              const max = Math.max(...z.productos.map((p) => p.unidades), 1)
              return (
                <div key={z.zona} className="rounded-sm ring-1 ring-foreground/10">
                  <p className="border-b px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                    {z.nombre}
                  </p>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-6">#</TableHead>
                        <TableHead>Producto</TableHead>
                        <TableHead className="text-right">Unidades</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {z.productos.map((p) => (
                        <TableRow key={p.producto_sk}>
                          <TableCell className="text-muted-foreground tabular-nums">{p.puesto}</TableCell>
                          <TableCell className="max-w-48">
                            <p className="truncate" title={p.producto}>{p.producto}</p>
                            <div className="mt-1 h-1 rounded-full bg-muted">
                              <div className="h-1 rounded-full bg-[var(--serie-1)]" style={{ width: `${(100 * p.unidades) / max}%` }} />
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{fmt.entero(p.unidades)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}
