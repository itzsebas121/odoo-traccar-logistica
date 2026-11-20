// Cliente de la API del asistente. Todo va al mismo origen (sin CORS) con la cookie de sesión.
// La cabecera X-Agente protege los POST frente a CSRF: otro sitio no puede enviarla sin CORS.

export type Usuario = { nombre: string; login: string; modelo?: string }

export type Bloque =
  | { tipo: 'texto'; texto: string }
  | { tipo: 'pensamiento'; texto: string }
  | { tipo: 'error'; texto: string }
  | {
      tipo: 'herramienta'
      id: string
      nombre: string
      etiqueta: string
      entrada: Record<string, unknown>
      estado: 'ejecutando' | 'ok' | 'error'
      ms?: number
      resumen?: string
    }

export type Mensaje = { rol: 'usuario' | 'asistente'; bloques: Bloque[] }
export type ResumenConversacion = { id: string; titulo: string; actualizada: number }

export class ErrorApi extends Error {
  estado: number
  constructor(estado: number, mensaje: string) {
    super(mensaje)
    this.estado = estado
  }
}

async function pedir<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  const respuesta = await fetch(ruta, {
    credentials: 'same-origin',
    ...opciones,
    headers: { 'Content-Type': 'application/json', 'X-Agente': '1', ...(opciones.headers ?? {}) },
  })
  if (!respuesta.ok) {
    let detalle = `Error ${respuesta.status}`
    try {
      detalle = (await respuesta.json()).detalle ?? detalle
    } catch {
      /* respuesta sin JSON */
    }
    throw new ErrorApi(respuesta.status, detalle)
  }
  return respuesta.json() as Promise<T>
}

export const api = {
  yo: () => pedir<Usuario>('/api/yo'),
  login: (login: string, clave: string) =>
    pedir<Usuario>('/api/login', { method: 'POST', body: JSON.stringify({ login, clave }) }),
  logout: () => pedir<{ ok: boolean }>('/api/logout', { method: 'POST' }),
  conversaciones: () => pedir<ResumenConversacion[]>('/api/conversaciones'),
  conversacion: (id: string) =>
    pedir<ResumenConversacion & { mensajes: Mensaje[] }>(`/api/conversaciones/${encodeURIComponent(id)}`),
  borrar: (id: string) =>
    pedir<{ ok: boolean }>(`/api/conversaciones/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

export type EventoChat =
  | { evento: 'conversacion'; datos: ResumenConversacion }
  | { evento: 'texto'; datos: { texto: string } }
  | { evento: 'pensamiento'; datos: { texto: string } }
  | { evento: 'herramienta'; datos: { id: string; nombre: string; etiqueta: string; entrada: Record<string, unknown> } }
  | { evento: 'herramienta_resultado'; datos: { id: string; ok: boolean; ms: number; resumen: string } }
  | { evento: 'fin'; datos: { uso: Record<string, number> } }
  | { evento: 'error'; datos: { mensaje: string } }

/** Envía un mensaje y entrega cada evento del flujo SSE (POST, por eso no se usa EventSource). */
export async function enviarMensaje(
  mensaje: string,
  conversacionId: string | null,
  alEvento: (e: EventoChat) => void,
  senal: AbortSignal,
) {
  const respuesta = await fetch('/api/chat', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Agente': '1', Accept: 'text/event-stream' },
    body: JSON.stringify({ mensaje, conversacion_id: conversacionId }),
    signal: senal,
  })
  if (!respuesta.ok || !respuesta.body) {
    let detalle = `Error ${respuesta.status}`
    try {
      detalle = (await respuesta.json()).detalle ?? detalle
    } catch {
      /* sin JSON */
    }
    throw new ErrorApi(respuesta.status, detalle)
  }
  const lector = respuesta.body.pipeThrough(new TextDecoderStream()).getReader()
  let pendiente = ''
  for (;;) {
    const { value, done } = await lector.read()
    if (done) break
    pendiente += value
    let corte: number
    while ((corte = pendiente.indexOf('\n\n')) !== -1) {
      const crudo = pendiente.slice(0, corte)
      pendiente = pendiente.slice(corte + 2)
      let evento = 'message'
      const datos: string[] = []
      for (const linea of crudo.split('\n')) {
        if (linea.startsWith('event:')) evento = linea.slice(6).trim()
        else if (linea.startsWith('data:')) datos.push(linea.slice(5).trimStart())
      }
      if (datos.length) {
        try {
          alEvento({ evento, datos: JSON.parse(datos.join('\n')) } as EventoChat)
        } catch {
          /* evento mal formado: se ignora */
        }
      }
    }
  }
}

// ------------------------------------------------------------------ base de datos
export type BaseId = 'odoo' | 'traccar'
export type EstadoBase = {
  base: BaseId
  nombre: string
  existe: boolean
  tamano_bytes: number
  filestore_bytes?: number
  anterior: boolean
}
export type Respaldo = { nombre: string; base: BaseId; tamano_bytes: number; creado: number; automatico: boolean }
export type EstadoBD = {
  disponible: boolean
  error?: string
  bases: EstadoBase[]
  respaldos: Respaldo[]
  en_curso: boolean
  max_subida_mb: number
}
export type ResultadoRestauracion = {
  base: BaseId
  nombre: string
  archivo: string
  segundos: number
  respaldo_previo: string | null
  base_anterior: string
  reiniciar: string
}

export const apiBD = {
  estado: () => pedir<EstadoBD>('/api/bd'),
  respaldar: (base: BaseId, clave_maestra: string) =>
    pedir<{ nombre: string; tamano_bytes: number }>('/api/bd/respaldos', {
      method: 'POST',
      body: JSON.stringify({ base, clave_maestra }),
    }),
  borrar: (nombre: string, clave_maestra: string) =>
    pedir<{ ok: boolean }>(`/api/bd/respaldos/${encodeURIComponent(nombre)}/borrar`, {
      method: 'POST',
      body: JSON.stringify({ clave_maestra }),
    }),
  urlDescarga: (nombre: string) => `/api/bd/respaldos/${encodeURIComponent(nombre)}`,
}

/** Restaura desde un archivo subido o un respaldo guardado. XHR para mostrar el avance de la subida. */
export function restaurarBD(
  datos: { base: BaseId; clave_maestra: string; confirmacion: string; nombre?: string; archivo?: File },
  alAvanzar: (porcentaje: number) => void,
): Promise<ResultadoRestauracion> {
  return new Promise((resolver, rechazar) => {
    const formulario = new FormData()
    formulario.append('base', datos.base)
    formulario.append('clave_maestra', datos.clave_maestra)
    formulario.append('confirmacion', datos.confirmacion)
    if (datos.nombre) formulario.append('nombre', datos.nombre)
    if (datos.archivo) formulario.append('archivo', datos.archivo)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/bd/restaurar')
    xhr.withCredentials = true
    xhr.setRequestHeader('X-Agente', '1')
    xhr.upload.onprogress = (e) => e.lengthComputable && alAvanzar(Math.round((e.loaded / e.total) * 100))
    xhr.onload = () => {
      let cuerpo: { detalle?: string } & Partial<ResultadoRestauracion> = {}
      try {
        cuerpo = JSON.parse(xhr.responseText)
      } catch {
        /* sin JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolver(cuerpo as ResultadoRestauracion)
      else rechazar(new ErrorApi(xhr.status, cuerpo.detalle ?? `Error ${xhr.status}`))
    }
    xhr.onerror = () => rechazar(new ErrorApi(0, 'Se perdió la conexión con el servidor.'))
    xhr.send(formulario)
  })
}

// ------------------------------------------------------------------ tablero (DWH, solo lectura)
export type Procedencia = 'REAL' | 'SIMULADO'
export type FiltrosTablero = {
  desde?: string
  hasta?: string
  procedencia?: Procedencia
  zona?: string
  categoria?: string
  conductor?: string
}
export type Rango = {
  desde: string
  hasta: string
  procedencia: Procedencia | null
  zona: string | null
  categoria: string | null
  conductor: string | null
}

export type PuntoPronosticoNegocio = {
  fecha: string
  tipo: 'backtest' | 'pronostico'
  pronostico: number
  real: number | null
}

export type ResumenTablero = {
  rango: Rango
  ultimo_dia: string | null
  hay_demo: boolean
  kpi: {
    importe: number
    pedidos: number
    unidades: number
    ticket: number | null
    variacion_importe_7d: number | null
    variacion_pedidos_7d: number | null
  }
  serie: { fecha: string; procedencia: Procedencia; pedidos: number; importe: number; unidades: number }[]
  simulado: { pedidos: number; total: number }
  pronostico_total: PuntoPronosticoNegocio[]
}

export type DemandaTablero = {
  rango: Rango
  categorias: { categoria: string; unidades: number; importe: number; pedidos: number }[]
  zonas: { zona: string; nombre: string; unidades: number; importe: number; pedidos: number }[]
  top_por_zona: {
    zona: string
    nombre: string
    productos: { producto_sk: number; producto: string; unidades: number; importe: number; puesto: number }[]
  }[]
  puntos: { latitud: number; longitud: number; pedidos: number; unidades: number; importe: number }[]
}

export type PuntoPronostico = {
  fecha: string
  real: number | null
  pronostico: number | null
  p10: number | null
  p90: number | null
  tipo: 'historia' | 'backtest' | 'pronostico'
}

/** Lo esperado los próximos 7 días y lo vendido la última semana de un producto en una zona. */
export type CeldaPronostico = {
  producto_sk: number
  producto: string
  categoria: string
  zona: string
  unidades: number
  /** Cantidad que cubre la demanda en la mayoría de los casos (el extremo alto del rango probable). */
  unidades_con_margen: number
  vendido_semana: number
  /** Lo que el modelo había pronosticado para la semana pasada (para medir su acierto). */
  pronostico_semana: number
}

export type PronosticoTablero = {
  rango: Rango
  zonas: { codigo: string; nombre: string; latitud: number; longitud: number }[]
  celdas: CeldaPronostico[]
  actualizado_utc: string | null
  aviso?: string
}

export type PronosticoDetalle = {
  rango: Rango
  serie: PuntoPronostico[]
}

export type OperacionTablero = {
  rango: Rango
  kpi: {
    entregas: number
    entregadas: number
    no_entregadas: number
    pendientes: number
    pct_a_tiempo: number | null
    pct_vinculadas_gps: number | null
    rutas: number
    rutas_con_gps: number
    km_planificado: number
    km_real: number
  }
  por_dia: { fecha: string; resultado: 'entregado' | 'no_entregado' | 'pendiente'; entregas: number }[]
  rutas: {
    codigo: string
    fecha: string
    conductor: string | null
    placa: string | null
    km_planificado: number | null
    km_real: number | null
    desviacion_km_pct: number | null
    min_planificado: number | null
    min_real: number | null
    desviacion_min_pct: number | null
    paradas_total: number
    pct_entregado: number | null
  }[]
  conductores: { conductor: string; rutas: number; km_plan: number | null; km_real: number | null }[]
}

export type OpcionesTablero = {
  zonas: { codigo: string; nombre: string }[]
  categorias: string[]
  conductores: string[]
}

/** Filtros que usa cada sección: zona y categoría para ventas y pronóstico; zona y conductor para la operación. */
const CLAVES = {
  resumen: ['desde', 'hasta', 'procedencia', 'zona', 'categoria'],
  demanda: ['desde', 'hasta', 'procedencia', 'zona', 'categoria'],
  pronostico: ['desde', 'hasta', 'procedencia', 'zona', 'categoria'],
  pronostico_detalle: ['desde', 'hasta', 'procedencia', 'zona', 'categoria'],
  operacion: ['desde', 'hasta', 'procedencia', 'zona', 'conductor'],
} as const
export type SeccionTablero = keyof typeof CLAVES

/** Raíz de la API del tablero: la del asistente por defecto; dentro de Odoo, la del módulo logistica_tablero
 * (mismas secciones y mismo JSON, ver odoo/addons/logistica_tablero). */
let baseTablero = '/api/tablero'
export function configurarApiTablero(base: string) {
  baseTablero = base.replace(/\/+$/, '')
}

/** URL de una sección con solo los filtros que le sirven (así cambiar uno que no usa no la vuelve a pedir). */
export function urlTablero(seccion: SeccionTablero, f: FiltrosTablero, extra: { producto_sk?: number } = {}) {
  const p = new URLSearchParams()
  for (const k of CLAVES[seccion]) if (f[k]) p.set(k, String(f[k]))
  if (extra.producto_sk !== undefined) p.set('producto_sk', String(extra.producto_sk))
  const s = p.toString()
  return `${baseTablero}/${seccion}${s ? `?${s}` : ''}`
}

export const apiTablero = {
  obtener: <T,>(url: string) => pedir<T>(url),
  opciones: () => pedir<OpcionesTablero>(`${baseTablero}/opciones`),
}
