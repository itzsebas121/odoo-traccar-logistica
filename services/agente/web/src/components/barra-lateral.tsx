import { ChatCircleTextIcon, DatabaseIcon, SignOutIcon, SquaresFourIcon } from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'

import { Marca } from '@/components/marca'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { Usuario } from '@/lib/api'
import { cn } from '@/lib/utils'

export type Vista = 'chat' | 'tablero' | 'basedatos'

const ENTRADAS: { id: Vista; etiqueta: string; icono: Icon }[] = [
  { id: 'chat', etiqueta: 'Asistente', icono: ChatCircleTextIcon },
  { id: 'tablero', etiqueta: 'Tablero', icono: SquaresFourIcon },
  { id: 'basedatos', etiqueta: 'Base', icono: DatabaseIcon },
]

function iniciales(nombre: string) {
  return nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('') || '?'
}

/** Riel de navegación: en escritorio vertical a la izquierda; en móvil, barra inferior. */
export function BarraLateral({ vista, alCambiar, usuario, alSalir }: {
  vista: Vista
  alCambiar: (v: Vista) => void
  usuario: Usuario
  alSalir: () => void
}) {
  return (
    <nav
      aria-label="Secciones"
      className="z-20 flex shrink-0 items-center justify-around border-t border-sidebar-border bg-sidebar text-sidebar-foreground
                 md:h-dvh md:w-[84px] md:flex-col md:justify-start md:gap-2 md:border-t-0 md:border-r md:py-4"
    >
      <div className="hidden md:mb-6 md:block">
        <Marca />
      </div>
      {ENTRADAS.map(({ id, etiqueta, icono: Icono }) => (
        <Tooltip key={id}>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => alCambiar(id)}
              aria-current={vista === id ? 'page' : undefined}
              className={cn(
                'group relative flex flex-col items-center gap-1 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.06em] transition-colors md:w-full md:px-0',
                vista === id ? 'text-sidebar-primary' : 'text-sidebar-foreground/60 hover:text-sidebar-foreground',
              )}
            >
              <span
                className={cn(
                  'absolute top-0 left-1/2 h-0.5 w-8 -translate-x-1/2 bg-sidebar-primary transition-opacity md:top-1/2 md:left-0 md:h-8 md:w-0.5 md:translate-x-0 md:-translate-y-1/2',
                  vista === id ? 'opacity-100' : 'opacity-0',
                )}
              />
              <Icono size={22} weight={vista === id ? 'fill' : 'regular'} />
              {etiqueta}
            </button>
          </TooltipTrigger>
          <TooltipContent side="right" className="hidden md:block">{etiqueta}</TooltipContent>
        </Tooltip>
      ))}

      <div className="md:mt-auto md:flex md:flex-col md:items-center md:gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="hidden size-9 items-center justify-center rounded-full bg-sidebar-accent font-mono text-xs font-semibold md:flex">
              {iniciales(usuario.nombre)}
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">{usuario.nombre} · {usuario.login}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" onClick={alSalir} aria-label="Cerrar sesión"
              className="flex flex-col items-center gap-1 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.12em] text-sidebar-foreground/60 hover:text-sidebar-foreground md:px-0">
              <SignOutIcon size={20} />
              <span className="md:hidden">Salir</span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Cerrar sesión</TooltipContent>
        </Tooltip>
      </div>
    </nav>
  )
}
