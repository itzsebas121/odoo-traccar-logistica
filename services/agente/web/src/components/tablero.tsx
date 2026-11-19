import { lazy, Suspense } from 'react'
import { CircleNotchIcon } from '@phosphor-icons/react'

// Gráficos (recharts) y mapa (leaflet) en un bloque aparte: el chat no los descarga.
const PanelTablero = lazy(() => import('./tablero/panel'))

/** Tablero de indicadores del DWH: ventas, demanda, pronóstico, operación y calidad del ETL. */
export function Tablero({ alSesionCaducada }: { alSesionCaducada: () => void }) {
  return (
    <Suspense fallback={
      <div className="flex h-full items-center justify-center">
        <CircleNotchIcon size={28} className="animate-spin text-senal" />
      </div>
    }>
      <PanelTablero alSesionCaducada={alSesionCaducada} />
    </Suspense>
  )
}
