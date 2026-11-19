/** Tablero: reservado para los indicadores. Por ahora solo la estructura vacía. */
export function Tablero() {
  const tarjetas = ['Ventas del mes', 'Por cobrar', 'Entregas hoy', 'Flota en ruta']
  return (
    <section className="fondo-plano flex h-full flex-col overflow-y-auto">
      <header className="border-b bg-background/80 px-6 py-5 backdrop-blur">
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-senal">Próximamente</p>
        <h1 className="mt-1 font-heading text-xl font-semibold tracking-tight">Tablero</h1>
      </header>
      <div className="grid gap-4 p-6 sm:grid-cols-2 xl:grid-cols-4">
        {tarjetas.map((t) => (
          <div key={t} className="rounded-lg border border-dashed bg-card/60 p-5">
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{t}</p>
            <div className="mt-4 h-8 w-24 rounded bg-muted" />
            <div className="mt-3 h-2 w-full rounded bg-muted/70" />
          </div>
        ))}
        <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed bg-card/60 p-6 text-center sm:col-span-2 xl:col-span-4">
          <p className="max-w-sm text-sm text-muted-foreground">
            Aquí irán los indicadores de ventas, facturación y operación. Mientras tanto, pregúntale al asistente.
          </p>
        </div>
      </div>
    </section>
  )
}
