import { useState } from 'react'
import { FlaskIcon } from '@phosphor-icons/react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  apiTablero, urlTablero, type DemandaTablero, type FiltrosTablero, type OperacionTablero, type PronosticoTablero,
  type ResumenTablero,
} from '@/lib/api'

import { Cargando, ErrorSeccion } from './comun'
import { FILTROS_DE, fmt, useSeccion, type Pestana, type Periodo } from './datos'
import { Demanda } from './demanda'
import { Filtros } from './filtros'
import { Operacion } from './operacion'
import { Pronostico } from './pronostico'
import { Resumen } from './resumen'

const PESTANAS: Record<Pestana, string> = {
  resumen: 'Resumen', demanda: 'Demanda', pronostico: 'Pronóstico', operacion: 'Operación',
}

export default function PanelTablero({ alSesionCaducada }: { alSesionCaducada: () => void }) {
  const [filtros, setFiltros] = useState<FiltrosTablero>({})
  const [periodo, setPeriodo] = useState<Periodo>('30')
  const [pestana, setPestana] = useState<Pestana>('resumen')
  const [vuelta, setVuelta] = useState(0)

  // El resumen se pide siempre: da el rango efectivo, el último día con ventas y si hay datos de demostración.
  const urlResumen = urlTablero('resumen', filtros)
  const resumen = useSeccion(() => apiTablero.obtener<ResumenTablero>(urlResumen), [urlResumen, vuelta], alSesionCaducada)
  const opciones = useSeccion(() => apiTablero.opciones(), [vuelta], alSesionCaducada)
  const rango = resumen.datos?.rango
  const ultimoDia = resumen.datos?.ultimo_dia ?? null
  const hayDemo = resumen.datos?.hay_demo ?? false
  const vista = { ...filtros, desde: filtros.desde ?? rango?.desde, hasta: filtros.hasta ?? rango?.hasta }

  const activos = FILTROS_DE[pestana].filter((k) => filtros[k])
  const nombreZona = (c: string) => opciones.datos?.zonas.find((z) => z.codigo === c)?.nombre ?? c
  const etiquetas = [
    filtros.procedencia === 'REAL' ? 'solo datos reales' : filtros.procedencia === 'SIMULADO' ? 'solo demostración' : null,
    activos.includes('zona') ? `zona ${nombreZona(filtros.zona!)}` : null,
    activos.includes('categoria') ? filtros.categoria! : null,
    activos.includes('conductor') ? `conductor ${filtros.conductor}` : null,
  ].filter(Boolean)

  const demo = resumen.datos?.simulado
  const verDemo = hayDemo && !!demo?.pedidos && filtros.procedencia !== 'REAL'

  return (
    <section className="tablero-viz fondo-plano h-full overflow-y-auto">
      <header className="px-4 pb-4 pt-6 md:px-8">
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-senal">Analítica</p>
        <h1 className="mt-1 font-heading text-xl font-semibold tracking-tight">Tablero</h1>
        {rango && (
          <p className="mt-1 text-sm text-muted-foreground tabular-nums">
            {[`${fmt.diaAnio(rango.desde)} – ${fmt.diaAnio(rango.hasta)}`, ...etiquetas].join(' · ')}
          </p>
        )}
      </header>

      <div className="sticky top-0 z-20 border-y bg-background/90 px-4 py-3 backdrop-blur md:px-8">
        <Filtros pestana={pestana} filtros={vista} periodo={periodo} ultimoDia={ultimoDia} hayDemo={hayDemo}
                 opciones={opciones.datos} hayFiltros={activos.length > 0} cargando={resumen.cargando}
                 alRecargar={() => setVuelta((v) => v + 1)}
                 alLimpiar={() => setFiltros((f) => ({ ...f, zona: undefined, categoria: undefined, conductor: undefined }))}
                 alCambiar={(f, p) => { setFiltros(f); setPeriodo(p) }} />
      </div>

      <div className="grid gap-4 px-4 py-6 md:px-8">
        {verDemo && (
          <div role="status" className="flex items-start gap-3 rounded-sm border border-[var(--estado-aviso)]/50 bg-[var(--estado-aviso)]/10 px-4 py-3 text-sm">
            <FlaskIcon size={18} className="mt-0.5 shrink-0" aria-hidden />
            <p>
              <span className="font-medium">Incluye datos de demostración.</span>{' '}
              {fmt.entero(demo!.pedidos)} de {fmt.entero(demo!.total)} pedidos del periodo son de prueba.
              Elige «Reales» en el filtro <span className="font-medium">Datos</span> para ver solo la operación real.
            </p>
          </div>
        )}

        <Tabs value={pestana} onValueChange={(v) => setPestana(v as Pestana)}>
          <TabsList className="flex-wrap">
            {Object.entries(PESTANAS).map(([k, v]) => <TabsTrigger key={k} value={k}>{v}</TabsTrigger>)}
          </TabsList>
          <TabsContent value="resumen" className="mt-4">
            {resumen.error ? <ErrorSeccion mensaje={resumen.error} />
              : resumen.datos ? <Resumen datos={resumen.datos} alVerPronostico={() => setPestana('pronostico')} />
              : <Cargando />}
          </TabsContent>
          <TabsContent value="demanda" className="mt-4">
            {pestana === 'demanda' && <SeccionDemanda filtros={filtros} vuelta={vuelta} alSesionCaducada={alSesionCaducada} />}
          </TabsContent>
          <TabsContent value="pronostico" className="mt-4">
            {pestana === 'pronostico' && (
              <SeccionPronostico filtros={filtros} vuelta={vuelta} alSesionCaducada={alSesionCaducada} />
            )}
          </TabsContent>
          <TabsContent value="operacion" className="mt-4">
            {pestana === 'operacion' && <SeccionOperacion filtros={filtros} vuelta={vuelta} alSesionCaducada={alSesionCaducada} />}
          </TabsContent>
        </Tabs>
      </div>
    </section>
  )
}

type Props = { filtros: FiltrosTablero; vuelta: number; alSesionCaducada: () => void }

function SeccionDemanda({ filtros, vuelta, alSesionCaducada }: Props) {
  const url = urlTablero('demanda', filtros)
  const s = useSeccion(() => apiTablero.obtener<DemandaTablero>(url), [url, vuelta], alSesionCaducada)
  return s.error ? <ErrorSeccion mensaje={s.error} /> : s.datos ? <Demanda datos={s.datos} /> : <Cargando alto="h-96" />
}

function SeccionPronostico({ filtros, vuelta, alSesionCaducada }: Props) {
  const url = urlTablero('pronostico', filtros)
  const s = useSeccion(() => apiTablero.obtener<PronosticoTablero>(url), [url, vuelta], alSesionCaducada)
  // `key`: al cambiar un filtro se empieza sin enfoque (la zona o el producto enfocados pueden ya no estar)
  return s.error ? <ErrorSeccion mensaje={s.error} />
    : s.datos ? <Pronostico key={url} datos={s.datos} filtros={filtros} vuelta={vuelta} alSesionCaducada={alSesionCaducada} />
    : <Cargando alto="h-96" />
}

function SeccionOperacion({ filtros, vuelta, alSesionCaducada }: Props) {
  const url = urlTablero('operacion', filtros)
  const s = useSeccion(() => apiTablero.obtener<OperacionTablero>(url), [url, vuelta], alSesionCaducada)
  return s.error ? <ErrorSeccion mensaje={s.error} /> : s.datos ? <Operacion datos={s.datos} /> : <Cargando />
}
