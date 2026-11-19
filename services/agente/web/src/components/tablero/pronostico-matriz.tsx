import { useMemo, useState } from 'react'
import { ArrowDownRightIcon, ArrowRightIcon, ArrowUpRightIcon } from '@phosphor-icons/react'

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { CeldaPronostico, PronosticoTablero } from '@/lib/api'

import { fmt } from './datos'
import { cambioTexto, fiabilidad, porZona, tendencia, type Fiabilidad, type Foco } from './pronostico-calculos'

const unidades = (v: number) => (v < 0.05 ? '–' : v < 10 ? fmt.decimal(v) : fmt.entero(v))

export function IconoTendencia({ unidades: u, vendido }: { unidades: number; vendido: number }) {
  const t = tendencia(u, vendido)
  if (t === 'sube') return <ArrowUpRightIcon size={13} aria-label="sube" />
  if (t === 'baja') return <ArrowDownRightIcon size={13} aria-label="baja" />
  return <ArrowRightIcon size={13} aria-label={t === 'igual' ? 'se mantiene' : 'sin dato'} className="opacity-60" />
}

const NIVEL: Record<Fiabilidad['nivel'], string> = { alta: 'Alta', media: 'Media', baja: 'Baja', 'sin-dato': '—' }

/** Qué tan bien acertó el modelo con el producto la semana pasada. Siempre con texto, no solo con color. */
export function Confiabilidad({ vendido, pronosticado }: { vendido: number; pronosticado: number }) {
  const f = fiabilidad(vendido, pronosticado)
  const titulo = f.error == null
    ? 'Se vendió muy poco la semana pasada para medir el acierto.'
    : `La semana pasada se pronosticó ${fmt.entero(pronosticado)} u. y se vendieron ${fmt.entero(vendido)} u. (${fmt.decimal(f.error)} % de diferencia).`
  const estilo = f.nivel === 'alta' ? 'border-foreground/30 bg-foreground/[0.06] font-medium'
    : f.nivel === 'media' ? 'border-foreground/20' : f.nivel === 'baja' ? 'border-dashed border-foreground/40' : 'border-transparent text-muted-foreground'
  return <span title={titulo} className={`inline-block min-w-14 rounded-sm border px-1.5 py-0.5 text-center text-xs ${estilo}`}>{NIVEL[f.nivel]}</span>
}

/**
 * Hoja de reposición: una fila por producto y una columna por zona. «Esperado» es lo que se pronostica para los próximos
 * 7 días; «Con margen» es la cantidad que cubre la demanda en la mayoría de los casos (para no quedarse corto). El color
 * de cada celda es la parte del total del producto que se pide en esa zona: más intenso, más concentrada.
 * Un clic en un producto o en una zona la enfoca en toda la pestaña.
 */
export function PronosticoMatriz({ celdas, zonas, foco, alEnfocar }: {
  celdas: CeldaPronostico[]
  zonas: PronosticoTablero['zonas']
  foco: Foco
  alEnfocar: (f: Foco) => void
}) {
  const [modo, setModo] = useState<'esperado' | 'margen'>('esperado')
  const nombre = useMemo(() => new Map(zonas.map((z) => [z.codigo, z.nombre])), [zonas])
  const columnas = useMemo(() => porZona(celdas).map((z) => z.zona), [celdas])
  const filas = useMemo(() => {
    const m = new Map<number, {
      sk: number; producto: string; zonas: Record<string, { esperado: number; margen: number }>
      esperado: number; margen: number; vendido: number; pronosticoSemana: number
    }>()
    for (const c of celdas) {
      const f = m.get(c.producto_sk) ?? { sk: c.producto_sk, producto: c.producto, zonas: {}, esperado: 0, margen: 0, vendido: 0, pronosticoSemana: 0 }
      const z = f.zonas[c.zona] ?? { esperado: 0, margen: 0 }
      z.esperado += c.unidades
      z.margen += c.unidades_con_margen
      f.zonas[c.zona] = z
      f.esperado += c.unidades
      f.margen += c.unidades_con_margen
      f.vendido += c.vendido_semana
      f.pronosticoSemana += c.pronostico_semana
      m.set(c.producto_sk, f)
    }
    return [...m.values()].sort((a, b) => b.esperado - a.esperado)
  }, [celdas])

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <ToggleGroup type="single" variant="outline" size="sm" value={modo} aria-label="Cantidad a mostrar"
                     onValueChange={(v) => v && setModo(v as 'esperado' | 'margen')}>
          <ToggleGroupItem value="esperado" title="Lo que se espera vender en los próximos 7 días">Esperado</ToggleGroupItem>
          <ToggleGroupItem value="margen" title="Cantidad que cubre la demanda en la mayoría de los casos (alrededor de 9 de cada 10)">Con margen</ToggleGroupItem>
        </ToggleGroup>
      </div>

      <div className="max-h-[34rem] overflow-auto rounded-sm ring-1 ring-foreground/10">
        <table className="w-full border-separate border-spacing-0 text-sm">
          <caption className="sr-only">Unidades por producto y zona para los próximos 7 días</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 top-0 z-20 min-w-52 border-b bg-card px-3 py-2 text-left font-medium">Producto</th>
              {columnas.map((z) => (
                <th key={z} scope="col" className="sticky top-0 z-10 border-b bg-card p-0 text-right font-medium">
                  <button type="button" aria-pressed={foco.zona === z} onClick={() => alEnfocar({ ...foco, zona: foco.zona === z ? undefined : z })}
                          className={`w-full px-3 py-2 text-right hover:bg-muted ${foco.zona === z ? 'bg-muted underline underline-offset-4' : ''}`}>
                    {nombre.get(z) ?? z}
                  </button>
                </th>
              ))}
              <th scope="col" className="sticky top-0 z-10 border-b bg-card px-3 py-2 text-right font-medium">Total</th>
              <th scope="col" title="Qué tan cerca estuvo el pronóstico de lo vendido la semana pasada: alta hasta 15 % de diferencia, media hasta 30 %" className="sticky top-0 z-10 border-b bg-card px-3 py-2 text-center font-medium">Fiabilidad</th>
              <th scope="col" className="sticky top-0 z-10 border-b bg-card px-3 py-2 text-right font-medium">Frente a la semana pasada</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => {
              const valores = columnas.map((z) => f.zonas[z]?.[modo] ?? 0)
              const max = Math.max(...valores, 0.0001)
              const elegido = foco.producto === f.sk
              return (
                <tr key={f.sk} className={elegido ? 'bg-muted/60' : ''}>
                  <th scope="row" className={`sticky left-0 z-10 border-b p-0 text-left font-normal ${elegido ? 'bg-muted' : 'bg-card'}`}>
                    <button type="button" aria-pressed={elegido} onClick={() => alEnfocar({ ...foco, producto: elegido ? undefined : f.sk })}
                            className="block w-full max-w-64 truncate px-3 py-2 text-left hover:underline" title={f.producto}>
                      {f.producto}
                    </button>
                  </th>
                  {columnas.map((z, i) => {
                    const v = valores[i]
                    const intensidad = v > 0 ? 8 + 52 * (v / max) : 0
                    return (
                      <td key={z} className={`border-b px-3 py-2 text-right font-mono tabular-nums ${foco.zona === z ? 'outline outline-1 -outline-offset-1 outline-foreground/30' : ''}`}
                          style={intensidad ? { background: `color-mix(in oklch, var(--serie-2) ${intensidad}%, transparent)` } : undefined}>
                        {unidades(v)}
                      </td>
                    )
                  })}
                  <td className="border-b px-3 py-2 text-right font-mono font-semibold tabular-nums">{unidades(f[modo])}</td>
                  <td className="border-b px-3 py-2 text-center"><Confiabilidad vendido={f.vendido} pronosticado={f.pronosticoSemana} /></td>
                  <td className="border-b px-3 py-2 text-right font-mono tabular-nums">
                    <span className="inline-flex items-center justify-end gap-1">
                      <IconoTendencia unidades={f.esperado} vendido={f.vendido} />
                      {cambioTexto(f.esperado, f.vendido)}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
