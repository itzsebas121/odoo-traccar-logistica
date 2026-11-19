import type { CeldaPronostico } from '@/lib/api'

/** Lo que el usuario tiene enfocado: una zona, un producto, o ambos. Sin nada, se ve todo el negocio. */
export type Foco = { zona?: string; producto?: number }

/** Cambio de 5 % o menos se considera «se mantiene». */
export const UMBRAL_CAMBIO = 5
/** Para ordenar quién sube o baja y medir el acierto, el producto tiene que haber vendido al menos esto la semana pasada. */
export const MIN_VENDIDO = 10
/** Error de la semana pasada por debajo del cual se considera fiable (alta) o aceptable (media). */
export const ERROR_ALTA = 15
export const ERROR_MEDIA = 30

export type Total = {
  unidades: number
  /** Lo que cubre la demanda en la mayoría de los casos. */
  margen: number
  vendido: number
  /** Lo que el modelo había pronosticado para la semana pasada. */
  pronosticoSemana: number
}
export type FilaProducto = Total & { producto_sk: number; producto: string; categoria: string }
export type FilaZona = Total & { zona: string }

const vacio = (): Total => ({ unidades: 0, margen: 0, vendido: 0, pronosticoSemana: 0 })
function sumar(t: Total, c: CeldaPronostico) {
  t.unidades += c.unidades
  t.margen += c.unidades_con_margen
  t.vendido += c.vendido_semana
  t.pronosticoSemana += c.pronostico_semana
}

export const cambioPct = (unidades: number, vendido: number): number | null =>
  vendido > 0 ? (100 * (unidades - vendido)) / vendido : null

export type Tendencia = 'sube' | 'baja' | 'igual' | 'sin-dato'
/** Con menos de MIN_VENDIDO unidades vendidas el porcentaje engaña (7 → 24 es «+244 %»): no se declara tendencia. */
export function tendencia(unidades: number, vendido: number): Tendencia {
  const c = cambioPct(unidades, vendido)
  if (c == null || vendido < MIN_VENDIDO) return 'sin-dato'
  return c > UMBRAL_CAMBIO ? 'sube' : c < -UMBRAL_CAMBIO ? 'baja' : 'igual'
}

/** Cambio frente a la semana pasada: en % si hay volumen suficiente; si no, en unidades. */
export function cambioTexto(unidades: number, vendido: number): string {
  const c = cambioPct(unidades, vendido)
  if (c != null && vendido >= MIN_VENDIDO) return signo(c)
  const d = Math.round(unidades - vendido)
  return `${d >= 0 ? '+' : '−'}${Math.abs(d)} u.`
}

export function total(celdas: CeldaPronostico[]): Total {
  const t = vacio()
  for (const c of celdas) sumar(t, c)
  return t
}

/** Suma por zona; con `producto`, solo ese producto. */
export function porZona(celdas: CeldaPronostico[], producto?: number): FilaZona[] {
  const m = new Map<string, FilaZona>()
  for (const c of celdas) {
    if (producto !== undefined && c.producto_sk !== producto) continue
    const f = m.get(c.zona) ?? { zona: c.zona, ...vacio() }
    sumar(f, c)
    m.set(c.zona, f)
  }
  return [...m.values()].sort((a, b) => b.unidades - a.unidades)
}

/** Suma por producto; con `zona`, solo esa zona. De mayor a menor demanda. */
export function porProducto(celdas: CeldaPronostico[], zona?: string): FilaProducto[] {
  const m = new Map<number, FilaProducto>()
  for (const c of celdas) {
    if (zona !== undefined && c.zona !== zona) continue
    const f = m.get(c.producto_sk) ?? { producto_sk: c.producto_sk, producto: c.producto, categoria: c.categoria, ...vacio() }
    sumar(f, c)
    m.set(c.producto_sk, f)
  }
  return [...m.values()].sort((a, b) => b.unidades - a.unidades)
}

/**
 * Productos que más suben y que más bajan, ordenados por cuántas unidades cambian (el impacto), no por porcentaje:
 * un 40 % sobre 12 unidades pesa menos que un 10 % sobre 200.
 */
export function cambios(filas: FilaProducto[]) {
  const con = filas
    .filter((f) => f.vendido >= MIN_VENDIDO)
    .map((f) => ({ ...f, cambio: cambioPct(f.unidades, f.vendido) as number, diferencia: f.unidades - f.vendido }))
  return {
    suben: con.filter((f) => f.cambio > UMBRAL_CAMBIO).sort((a, b) => b.diferencia - a.diferencia),
    bajan: con.filter((f) => f.cambio < -UMBRAL_CAMBIO).sort((a, b) => a.diferencia - b.diferencia),
  }
}

export type Fiabilidad = { nivel: 'alta' | 'media' | 'baja' | 'sin-dato'; error: number | null }

/** Qué tan bien acertó el modelo con este producto la semana pasada: pronosticado frente a vendido. */
export function fiabilidad(vendido: number, pronosticado: number): Fiabilidad {
  if (vendido < MIN_VENDIDO) return { nivel: 'sin-dato', error: null }
  const error = (100 * Math.abs(pronosticado - vendido)) / vendido
  return { nivel: error <= ERROR_ALTA ? 'alta' : error <= ERROR_MEDIA ? 'media' : 'baja', error }
}

export type Calidad = {
  pronosticado: number
  vendido: number
  /** Error por producto: suma de las diferencias absolutas ÷ lo vendido. No se compensa entre productos. */
  errorProducto: number
  /** Sesgo: (pronosticado − vendido) ÷ vendido. Negativo = se quedó corto (riesgo de faltante). */
  sesgo: number
}

/** Acierto de la semana pasada sobre todos los productos de la selección; null si no hubo ventas. */
export function calidad(productos: FilaProducto[]): Calidad | null {
  const vendido = productos.reduce((s, p) => s + p.vendido, 0)
  if (vendido <= 0) return null
  const pronosticado = productos.reduce((s, p) => s + p.pronosticoSemana, 0)
  const absoluto = productos.reduce((s, p) => s + Math.abs(p.pronosticoSemana - p.vendido), 0)
  return { pronosticado, vendido, errorProducto: (100 * absoluto) / vendido, sesgo: (100 * (pronosticado - vendido)) / vendido }
}

export const signo = (c: number) => `${c >= 0 ? '+' : '−'}${Math.abs(c).toFixed(c >= 10 || c <= -10 ? 0 : 1).replace('.', ',')} %`
