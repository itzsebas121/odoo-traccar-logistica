import { cn } from '@/lib/utils'

/** Marca «Bitácora»: una ruta que sale de la sede (cuadrado) y pasa por dos paradas. */
export function Marca({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn('size-7', className)}>
      <rect x="3" y="21" width="8" height="8" rx="1" className="fill-sidebar-primary" />
      <path
        d="M7 21 C 7 13, 15 15, 16 10 S 24 5, 27 6"
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        className="stroke-current opacity-70"
        strokeDasharray="3 3.2"
      />
      <circle cx="16" cy="10.5" r="2.4" className="fill-current" />
      <circle cx="27" cy="6" r="2.4" className="fill-current" />
    </svg>
  )
}

export function Logotipo({ className, sub = true }: { className?: string; sub?: boolean }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <Marca />
      <div className="leading-none">
        <div className="font-heading text-sm font-semibold tracking-tight">Bitácora</div>
        {sub && <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] opacity-60">Administración</div>}
      </div>
    </div>
  )
}
