import { useCallback, useEffect, useState } from 'react'
import { CircleNotchIcon } from '@phosphor-icons/react'

import { BarraLateral, type Vista } from '@/components/barra-lateral'
import { BaseDeDatos } from '@/components/basedatos'
import { Chat } from '@/components/chat/chat'
import { Login } from '@/components/login'
import { Tablero } from '@/components/tablero'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { api, type Usuario } from '@/lib/api'

const RUTAS: Record<string, Vista> = { '#/tablero': 'tablero', '#/base-de-datos': 'basedatos' }

function vistaDeUrl(): Vista {
  return RUTAS[window.location.hash] ?? 'chat'
}

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null | undefined>(undefined)
  const [vista, setVista] = useState<Vista>(vistaDeUrl)

  useEffect(() => {
    api.yo().then(setUsuario).catch(() => setUsuario(null))
    const alCambiarHash = () => setVista(vistaDeUrl())
    window.addEventListener('hashchange', alCambiarHash)
    return () => window.removeEventListener('hashchange', alCambiarHash)
  }, [])

  const cambiarVista = (v: Vista) => {
    window.location.hash = Object.entries(RUTAS).find(([, vista]) => vista === v)?.[0] ?? '#/'
  }

  const salir = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUsuario(null)
    }
  }, [])

  const sesionCaducada = useCallback(() => setUsuario(null), [])

  if (usuario === undefined) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <CircleNotchIcon size={28} className="animate-spin text-senal" />
      </div>
    )
  }

  return (
    <TooltipProvider delayDuration={300}>
      {usuario === null ? (
        <Login alEntrar={setUsuario} />
      ) : (
        <div className="flex h-dvh flex-col-reverse overflow-hidden md:flex-row">
          <BarraLateral vista={vista} alCambiar={cambiarVista} usuario={usuario} alSalir={salir} />
          <main className="relative min-h-0 min-w-0 flex-1">
            {vista === 'chat' && <Chat modelo={usuario.modelo} alSesionCaducada={sesionCaducada} />}
            {vista === 'tablero' && <Tablero />}
            {vista === 'basedatos' && <BaseDeDatos alSesionCaducada={sesionCaducada} />}
          </main>
        </div>
      )}
      <Toaster position="top-center" richColors />
    </TooltipProvider>
  )
}
