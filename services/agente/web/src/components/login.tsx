import { useState, type FormEvent } from 'react'
import { CircleNotchIcon } from '@phosphor-icons/react'

import { Logotipo } from '@/components/marca'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, ErrorApi, type Usuario } from '@/lib/api'

/** Mapa ilustrativo: la sede (FISEI) y el reparto hacia los sectores de Ambato. */
function MapaDecorativo() {
  const paradas: [number, number, string][] = [
    [78, 92, 'Ficoa'], [212, 70, 'Ingahurco'], [258, 186, 'Atocha'], [120, 248, 'Huachi'], [300, 300, 'Píllaro'],
  ]
  return (
    <svg viewBox="0 0 360 380" className="h-full w-full" aria-hidden="true">
      <defs>
        <pattern id="malla" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M24 0H0V24" fill="none" stroke="currentColor" strokeOpacity="0.07" />
        </pattern>
      </defs>
      <rect width="360" height="380" fill="url(#malla)" />
      <path d="M20 330 C 90 290, 60 210, 140 190 S 260 140, 340 40" fill="none" stroke="currentColor" strokeOpacity="0.12" strokeWidth="14" />
      <path
        className="trazo-ruta text-sidebar-primary"
        d="M150 300 L120 248 L78 92 L212 70 L258 186 L300 300"
        fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round"
      />
      <rect x="140" y="290" width="20" height="20" rx="2" className="fill-sidebar-primary" />
      <text x="166" y="305" className="fill-current font-mono text-[10px]" opacity="0.85">SEDE · FISEI</text>
      {paradas.map(([x, y, nombre], i) => (
        <g key={nombre}>
          <circle cx={x} cy={y} r="6" className="fill-sidebar" stroke="currentColor" strokeWidth="2" />
          <text x={x + 11} y={y + 4} className="fill-current font-mono text-[10px]" opacity="0.6">
            {String(i + 1).padStart(2, '0')} {nombre}
          </text>
        </g>
      ))}
    </svg>
  )
}

export function Login({ alEntrar }: { alEntrar: (u: Usuario) => void }) {
  const [login, setLogin] = useState('')
  const [clave, setClave] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setCargando(true)
    try {
      alEntrar(await api.login(login, clave))
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : 'No se pudo conectar con el servidor.')
    } finally {
      setCargando(false)
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-sidebar p-10 text-sidebar-foreground lg:flex">
        <Logotipo />
        <div className="absolute inset-x-6 top-24 bottom-40 opacity-90">
          <MapaDecorativo />
        </div>
        <div className="relative max-w-md">
          <p className="font-heading text-2xl leading-snug font-semibold tracking-tight text-balance">
            Pregunta por ventas, facturas y entregas. La respuesta sale de tus datos en Odoo.
          </p>
          <p className="mt-3 font-mono text-xs uppercase tracking-[0.16em] opacity-50">Asistente del administrador</p>
        </div>
      </aside>

      <main className="fondo-plano flex items-center justify-center px-4 py-12">
        <form onSubmit={enviar} className="w-full max-w-sm">
          <Logotipo className="mb-10 lg:hidden" />
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-senal">Acceso restringido</p>
          <h1 className="mt-2 font-heading text-2xl font-semibold tracking-tight">Inicia sesión</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Usa tu usuario de Odoo. Solo pueden entrar los administradores.
          </p>

          <div className="mt-8 space-y-5 rounded-lg border bg-card p-6 shadow-[0_1px_0_var(--border),0_12px_32px_-18px_oklch(0.23_0.025_258/35%)]">
            <div className="space-y-2">
              <Label htmlFor="login">Usuario</Label>
              <Input id="login" autoComplete="username" autoFocus required value={login}
                onChange={(e) => setLogin(e.target.value)} placeholder="correo@empresa.com" className="h-10" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="clave">Contraseña</Label>
              <Input id="clave" type="password" autoComplete="current-password" required value={clave}
                onChange={(e) => setClave(e.target.value)} className="h-10" />
            </div>
            {error && (
              <p role="alert" className="border-l-2 border-destructive bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" disabled={cargando} className="h-10 w-full text-sm">
              {cargando && <CircleNotchIcon className="animate-spin" />}
              Entrar
            </Button>
          </div>
        </form>
      </main>
    </div>
  )
}
