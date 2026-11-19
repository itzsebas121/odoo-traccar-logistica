import { useMemo } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

import type { DemandaTablero } from '@/lib/api'

import { fmt } from './datos'

// Ambato (centro de la operación) por si no hay puntos.
const CENTRO: [number, number] = [-1.2417, -78.6197]
// Teselas de calles de Esri: sin clave de API y sin exigir la cabecera Referer (OpenStreetMap bloquea a quien no la
// envía y CARTO pide clave). En modo oscuro el mapa se oscurece con un filtro CSS (index.css).
const TESELAS = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'
const ATRIBUCION = 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, OpenStreetMap contributors'

/** Puntos de demanda (ubicación aproximada del pedido): el área del círculo es proporcional al importe. */
export function MapaDemanda({ puntos }: { puntos: DemandaTablero['puntos'] }) {
  const { centro, maximo } = useMemo(() => {
    if (!puntos.length) return { centro: CENTRO, maximo: 1 }
    const lat = puntos.reduce((s, p) => s + p.latitud, 0) / puntos.length
    const lon = puntos.reduce((s, p) => s + p.longitud, 0) / puntos.length
    return { centro: [lat, lon] as [number, number], maximo: Math.max(...puntos.map((p) => p.importe), 1) }
  }, [puntos])

  return (
    <MapContainer center={centro} zoom={13} scrollWheelZoom={false} className="h-96 w-full rounded-sm"
                  aria-label="Mapa de la demanda por ubicación">
      <TileLayer url={TESELAS} attribution={ATRIBUCION} maxZoom={18} />
      {puntos.map((p) => (
        <CircleMarker key={`${p.latitud},${p.longitud}`} center={[p.latitud, p.longitud]}
                      radius={4 + 14 * Math.sqrt(p.importe / maximo)}
                      pathOptions={{ color: '#fff', weight: 1, fillColor: '#e0541a', fillOpacity: 0.6 }}>
          <Tooltip>
            <span className="font-mono text-xs">
              {fmt.dineroExacto(p.importe)} · {fmt.entero(p.pedidos)} pedidos · {fmt.entero(p.unidades)} u.
            </span>
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
