// Tablero dentro de Odoo (módulo logistica_tablero): el MISMO panel del asistente, servido por Odoo en una página
// propia (/logistica/tablero/app) que Odoo muestra en su menú. Pide los datos a la API de Odoo
// (/logistica/tablero/api/<sección>, con la sesión de Odoo), que devuelve el mismo JSON que la del asistente.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { Tablero } from './components/tablero'
import { configurarApiTablero } from './lib/api'
import './index.css'

configurarApiTablero('/logistica/tablero/api')

// Tema según el sistema operativo (claro / oscuro), igual que en el asistente.
const oscuro = window.matchMedia('(prefers-color-scheme: dark)')
const aplicarTema = () => document.documentElement.classList.toggle('dark', oscuro.matches)
aplicarTema()
oscuro.addEventListener('change', aplicarTema)

// Sesión de Odoo vencida: se recarga la ventana de Odoo, que lleva al inicio de sesión.
const alSesionCaducada = () => (window.top ?? window).location.reload()

// Mismo componente que usa el asistente (carga el panel aparte, con React.lazy).
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Tablero alSesionCaducada={alSesionCaducada} />
  </StrictMode>,
)
