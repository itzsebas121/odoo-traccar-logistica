import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'
import './index.css'

// Tema según el sistema operativo (claro / oscuro).
const oscuro = window.matchMedia('(prefers-color-scheme: dark)')
const aplicarTema = () => document.documentElement.classList.toggle('dark', oscuro.matches)
aplicarTema()
oscuro.addEventListener('change', aplicarTema)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
