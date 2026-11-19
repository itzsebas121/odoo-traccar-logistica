import { useEffect, useRef, useState } from 'react'

import { ErrorApi } from '@/lib/api'

// ------------------------------------------------------------------ formato
const moneda = new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const monedaCentavos = new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD' })
const entero = new Intl.NumberFormat('es-EC', { maximumFractionDigits: 0 })
const decimal = new Intl.NumberFormat('es-EC', { maximumFractionDigits: 1 })

export const fmt = {
  dinero: (v: number | null | undefined) => (v == null ? '—' : moneda.format(v)),
  dineroExacto: (v: number | null | undefined) => (v == null ? '—' : monedaCentavos.format(v)),
  entero: (v: number | null | undefined) => (v == null ? '—' : entero.format(v)),
  decimal: (v: number | null | undefined) => (v == null ? '—' : decimal.format(v)),
  pct: (v: number | null | undefined) => (v == null ? '—' : `${decimal.format(v)} %`),
  /** 2026-11-05 -> «5 nov» */
  dia: (iso: string) => {
    const [a, m, d] = iso.slice(0, 10).split('-').map(Number)
    return new Date(a, m - 1, d).toLocaleDateString('es-EC', { day: 'numeric', month: 'short' })
  },
  diaLargo: (iso: string) => {
    const [a, m, d] = iso.slice(0, 10).split('-').map(Number)
    return new Date(a, m - 1, d).toLocaleDateString('es-EC', { weekday: 'short', day: 'numeric', month: 'short' })
  },
  diaAnio: (iso: string) => {
    const [a, m, d] = iso.slice(0, 10).split('-').map(Number)
    return new Date(a, m - 1, d).toLocaleDateString('es-EC', { day: 'numeric', month: 'short', year: 'numeric' })
  },
  fechaHora: (iso: string | null) => (iso ? new Date(iso).toLocaleString('es-EC', { dateStyle: 'medium', timeStyle: 'short' }) : '—'),
}

// ------------------------------------------------------------------ datos
export type Estado<T> = { datos: T | null; error: string | null; cargando: boolean }

/** Pide una sección del tablero cuando cambian sus dependencias. 401 cierra la sesión. */
export function useSeccion<T>(pedir: () => Promise<T>, deps: unknown[], alSesionCaducada: () => void): Estado<T> {
  const clave = JSON.stringify(deps)
  const [res, setRes] = useState<{ clave: string | null; datos: T | null; error: string | null }>(
    { clave: null, datos: null, error: null })
  // las funciones cambian en cada render; lo que dispara la consulta es `clave` (los filtros)
  const fn = useRef({ pedir, alSesionCaducada })
  useEffect(() => {
    fn.current = { pedir, alSesionCaducada }
  })
  useEffect(() => {
    let vivo = true
    fn.current.pedir()
      .then((datos) => vivo && setRes({ clave, datos, error: null }))
      .catch((err) => {
        if (!vivo) return
        if (err instanceof ErrorApi && err.estado === 401) return fn.current.alSesionCaducada()
        setRes({ clave, datos: null, error: err instanceof Error ? err.message : 'Error inesperado' })
      })
    return () => {
      vivo = false
    }
  }, [clave])
  // mientras llega la consulta nueva se siguen mostrando los datos anteriores
  return { datos: res.datos, error: res.error, cargando: res.clave !== clave }
}

// ------------------------------------------------------------------ periodos
export const PERIODOS = { '7': 'Últimos 7 días', '30': 'Últimos 30 días', '90': 'Últimos 90 días', '365': 'Último año' } as const
export type Periodo = keyof typeof PERIODOS | 'personalizado'

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export const deIso = (s: string) => {
  const [a, m, d] = s.split('-').map(Number)
  return new Date(a, m - 1, d)
}

/** Fechas de un periodo que termina en `ultimoDia` (el último día con ventas que informa el servidor). */
export function rangoDePeriodo(periodo: keyof typeof PERIODOS, ultimoDia: string): { desde: string; hasta: string } {
  const hasta = deIso(ultimoDia)
  const desde = new Date(hasta)
  desde.setDate(desde.getDate() - Number(periodo) + 1)
  return { desde: iso(desde), hasta: ultimoDia }
}


// ------------------------------------------------------------------ pestañas y filtros
export type Pestana = 'resumen' | 'demanda' | 'pronostico' | 'operacion'

/** Qué filtros de dimensión sirven en cada pestaña: ventas y pronóstico, zona y categoría; operación, zona y conductor. */
export const FILTROS_DE: Record<Pestana, ('zona' | 'categoria' | 'conductor')[]> = {
  resumen: ['zona', 'categoria'],
  demanda: ['zona', 'categoria'],
  pronostico: ['zona', 'categoria'],
  operacion: ['zona', 'conductor'],
}
