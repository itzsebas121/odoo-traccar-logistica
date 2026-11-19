import { useMemo } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

import type { PronosticoTablero } from '@/lib/api'

import { fmt } from './datos'
import { cambioTexto, tendencia, type FilaZona, type Tendencia } from './pronostico-calculos'

const TESELAS = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'
const ATRIBUCION = 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, OpenStreetMap contributors'
/** Con más etiquetas fijas se montan unas sobre otras (las zonas del centro están muy juntas): el resto, al pasar el cursor. */
const ETIQUETAS_FIJAS = 4

// Color = hacia dónde va la demanda frente a la semana pasada. Cada burbuja además dice su cambio con texto.
const COLOR_TENDENCIA: Record<Tendencia, string> = {
  sube: '#e0541a',
  baja: '#2a78d6',
  igual: '#7b8190',
  'sin-dato': '#7b8190',
}

type Lado = 'top' | 'bottom' | 'left' | 'right'

/** Mapa de las zonas: el tamaño de cada burbuja es la demanda esperada y el color, si sube o baja. Un clic enfoca la zona. */
export function PronosticoMapa({ zonas, valores, elegida, alElegir }: {
  zonas: PronosticoTablero['zonas']
  valores: FilaZona[]
  elegida?: string
  alElegir: (zona?: string) => void
}) {
  const porCodigo = useMemo(() => new Map(valores.map((v) => [v.zona, v])), [valores])
  const maximo = Math.max(...valores.map((v) => v.unidades), 1)
  const limites = useMemo(() => zonas.map((z) => [z.latitud, z.longitud] as [number, number]), [zonas])

  // Las zonas grandes se dibujan primero para que las pequeñas queden encima y se puedan tocar.
  const dibujo = useMemo(() => {
    const unidades = (c: string) => porCodigo.get(c)?.unidades ?? 0
    const ranking = [...zonas].sort((a, b) => unidades(b.codigo) - unidades(a.codigo))
    const puesto = new Map(ranking.map((z, i) => [z.codigo, i]))
    const lat = zonas.reduce((s, z) => s + z.latitud, 0) / zonas.length
    const lon = zonas.reduce((s, z) => s + z.longitud, 0) / zonas.length
    // la etiqueta sale hacia fuera del grupo de zonas, para que no tape a las vecinas
    const lado = (z: PronosticoTablero['zonas'][number]): Lado => {
      const dy = z.latitud - lat
      const dx = z.longitud - lon
      return Math.abs(dx) > Math.abs(dy) * 1.6 ? (dx > 0 ? 'right' : 'left') : dy > 0 ? 'top' : 'bottom'
    }
    return ranking.map((z) => ({ z, puesto: puesto.get(z.codigo) ?? 0, lado: lado(z) }))
  }, [zonas, porCodigo])

  return (
    <div>
      <MapContainer bounds={limites} boundsOptions={{ padding: [56, 56] }} scrollWheelZoom={false}
                    className="h-[26rem] w-full rounded-sm xl:h-[34rem]" aria-label="Mapa de la demanda esperada por zona">
        <TileLayer url={TESELAS} attribution={ATRIBUCION} maxZoom={18} />
        {dibujo.map(({ z, puesto, lado }) => {
          const v = porCodigo.get(z.codigo)
          const sel = elegida === z.codigo
          const t: Tendencia = v ? tendencia(v.unidades, v.vendido) : 'sin-dato'
          const radio = v ? 12 + 30 * Math.sqrt(v.unidades / maximo) : 6
          const fija = sel || (v !== undefined && puesto < ETIQUETAS_FIJAS)
          const desplazamiento: [number, number] = lado === 'top' ? [0, -radio] : lado === 'bottom' ? [0, radio]
            : lado === 'left' ? [-radio, 0] : [radio, 0]
          return (
            <CircleMarker key={z.codigo} center={[z.latitud, z.longitud]} radius={radio}
                          eventHandlers={{ click: () => alElegir(sel ? undefined : z.codigo) }}
                          pathOptions={{
                            color: sel ? '#0f1a2b' : '#ffffff', weight: sel ? 3 : 1.5,
                            fillColor: COLOR_TENDENCIA[t], fillOpacity: v ? 0.62 : 0.2,
                          }}>
              <Tooltip key={fija ? 'fija' : 'cursor'} permanent={fija} direction={lado} offset={desplazamiento}
                       className="etiqueta-zona">
                <span className="font-medium">{z.nombre}</span>
                {v && <> <span className="font-mono tabular-nums">{fmt.entero(v.unidades)} u.</span>
                  <span className="font-mono tabular-nums text-muted-foreground"> {cambioTexto(v.unidades, v.vendido)}</span></>}
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <ul className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground" aria-label="Leyenda del mapa">
        <li className="flex items-center gap-1.5"><Punto color={COLOR_TENDENCIA.sube} />Sube</li>
        <li className="flex items-center gap-1.5"><Punto color={COLOR_TENDENCIA.igual} />Se mantiene</li>
        <li className="flex items-center gap-1.5"><Punto color={COLOR_TENDENCIA.baja} />Baja</li>
        <li>Tamaño: unidades</li>
      </ul>
    </div>
  )
}

function Punto({ color }: { color: string }) {
  return <span className="size-2.5 rounded-full ring-1 ring-white/70" style={{ background: color }} aria-hidden />
}
