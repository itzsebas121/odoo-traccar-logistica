import type { ReactNode } from 'react'
import { ArrowDownRightIcon, ArrowUpRightIcon, WarningCircleIcon } from '@phosphor-icons/react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

import { fmt } from './datos'

// ------------------------------------------------------------------ piezas
export function Kpi({ titulo, valor, detalle, variacion, nota }: {
  titulo: string
  valor: string
  detalle?: ReactNode
  variacion?: number | null
  nota?: string
}) {
  const sube = variacion != null && variacion >= 0
  return (
    <Card size="sm" className="gap-1">
      <CardHeader>
        <CardDescription className="font-mono text-[11px] uppercase tracking-[0.14em]">{titulo}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-1">
        <p className="font-heading text-2xl font-semibold tabular-nums tracking-tight">{valor}</p>
        {variacion != null && (
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            {sube ? <ArrowUpRightIcon size={14} aria-hidden /> : <ArrowDownRightIcon size={14} aria-hidden />}
            <span className="font-medium text-foreground tabular-nums">{fmt.pct(Math.abs(variacion))}</span>
            {sube ? 'más' : 'menos'} que la semana anterior
          </p>
        )}
        {detalle && <p className="text-xs text-muted-foreground">{detalle}</p>}
        {nota && <p className="text-[11px] text-muted-foreground">{nota}</p>}
      </CardContent>
    </Card>
  )
}

export function Panel({ titulo, descripcion, children, accion, className }: {
  titulo: string
  descripcion?: ReactNode
  children: ReactNode
  accion?: ReactNode
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <CardTitle className="font-heading text-sm">{titulo}</CardTitle>
          {descripcion && <CardDescription>{descripcion}</CardDescription>}
        </div>
        {accion}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function Cargando({ alto = 'h-64' }: { alto?: string }) {
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <Skeleton className={alto} />
    </div>
  )
}

export function ErrorSeccion({ mensaje }: { mensaje: string }) {
  return (
    <Card className="border-destructive/40">
      <CardContent className="flex items-start gap-3 py-2">
        <WarningCircleIcon size={20} className="mt-0.5 shrink-0 text-destructive" aria-hidden />
        <div className="space-y-1 text-sm">
          <p className="font-medium">No se pudieron cargar los datos.</p>
          <p className="text-muted-foreground">{mensaje}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export function SinDatos({ children }: { children: ReactNode }) {
  return <p className="py-10 text-center text-sm text-muted-foreground">{children}</p>
}

/** Vista de tabla de un gráfico (accesibilidad: los valores sin depender del color ni del cursor). */
export function VerDatos({ columnas, filas }: { columnas: { clave: string; titulo: string; formato?: (v: never) => string }[]; filas: Record<string, unknown>[] }) {
  return (
    <Collapsible className="mt-3">
      <CollapsibleTrigger className="text-xs text-muted-foreground underline-offset-4 hover:underline">
        Ver datos en tabla
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 max-h-72 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>{columnas.map((c) => <TableHead key={c.clave}>{c.titulo}</TableHead>)}</TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((f, i) => (
              <TableRow key={i}>
                {columnas.map((c) => (
                  <TableCell key={c.clave} className="tabular-nums">
                    {c.formato ? c.formato(f[c.clave] as never) : String(f[c.clave] ?? '—')}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CollapsibleContent>
    </Collapsible>
  )
}
