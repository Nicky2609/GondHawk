/**
 * Cabecera del tablero.
 *
 * El chip de "procesamiento local" no es decorativo: es el criterio de
 * viabilidad edge del reto, y conviene que esté visible en pantalla y no solo
 * en la presentación.
 */
export function Header({ frames, tiempo }) {
  const fps = frames && tiempo ? Math.round(frames / tiempo) : null;

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] px-5 py-4">
      <div>
        <h1 className="text-2xl">Góndola Inteligente</h1>
        <p className="text-xs text-[var(--ink-muted)]">
          Convierte video en decisiones de space management
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="status-chip">
          <span className="status-dot" />
          <span>
            Procesamiento local
            <small>Sin conexión a la nube</small>
          </span>
        </span>
        {fps !== null && (
          <span className="status-chip">
            <span>
              {fps} fps
              <small>{frames.toLocaleString('es-CO')} frames analizados</small>
            </span>
          </span>
        )}
      </div>
    </header>
  );
}
