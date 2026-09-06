import { useCallback, useEffect, useState } from 'react';
import { DATA_SOURCES } from '../../config/dataConfig';

function fecha(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' });
}

function porcentaje(valor) {
  return typeof valor === 'number' ? `${Math.round(valor * 100)}%` : '—';
}

/**
 * Historial de análisis. Lista las corridas guardadas y permite reabrir una.
 *
 * El resumen que muestra viene ya aplanado del backend, así que la lista no
 * tiene que descargar el detalle completo de cada corrida para pintarse.
 */
export function HistoryPanel({ onAbrir, recargar }) {
  const [analisis, setAnalisis] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(true);

  const cargar = useCallback(async (sigueVigente = () => true) => {
    try {
      const res = await fetch(DATA_SOURCES.historial);
      if (!sigueVigente()) return;
      if (!res.ok) throw new Error('No se pudo cargar el historial.');
      const payload = await res.json();
      if (!sigueVigente()) return;
      setAnalisis(Array.isArray(payload.analisis) ? payload.analisis : []);
      setEstadisticas(payload.estadisticas ?? null);
      setError(null);
    } catch (err) {
      if (!sigueVigente()) return;
      setError(err instanceof Error ? err.message : 'Error al cargar el historial.');
    } finally {
      if (sigueVigente()) setCargando(false);
    }
  }, []);

  useEffect(() => {
    // Carga inicial y recarga tras cada análisis nuevo. El estado solo se
    // actualiza dentro del callback asíncrono y se descarta si el componente
    // se desmontó antes de que responda el backend.
    let vigente = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar(() => vigente);
    return () => {
      vigente = false;
    };
  }, [cargar, recargar]);

  const abrir = async (id) => {
    try {
      const res = await fetch(DATA_SOURCES.analisis(id));
      if (!res.ok) throw new Error('No se pudo abrir el análisis.');
      const detalle = await res.json();
      onAbrir?.(detalle.detalle ?? detalle, id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al abrir el análisis.');
    }
  };

  const eliminar = async (id, event) => {
    event.stopPropagation();
    try {
      await fetch(DATA_SOURCES.analisis(id), { method: 'DELETE' });
      cargar();
    } catch {
      setError('No se pudo eliminar el análisis.');
    }
  };

  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4" data-tour="history">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-xs text-[var(--ink-muted)]">Historial de análisis</p>
          {estadisticas?.total_analisis > 0 && (
            <p className="text-[11px] text-[var(--ink-muted)]">
              {estadisticas.total_analisis} análisis · interacción media{' '}
              {porcentaje(estadisticas.promedio_tasa_interaccion)}
            </p>
          )}
        </div>
        <button type="button" onClick={() => cargar()} className="text-xs text-[var(--ink-muted)] hover:text-[var(--ink)]">
          {cargando ? 'Cargando...' : 'Actualizar'}
        </button>
      </div>

      {error && <p className="mb-2 text-xs text-red-400">{error}</p>}

      {analisis.length === 0 && !cargando ? (
        <p className="text-sm text-[var(--ink-muted)]">Todavía no hay análisis guardados.</p>
      ) : (
        <ul className="divide-y divide-[var(--panel-border)]">
          {analisis.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => abrir(item.id)}
                className="flex w-full items-center justify-between gap-3 py-3 text-left hover:opacity-80"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm">{item.video}</p>
                  <p className="text-[11px] text-[var(--ink-muted)]">{fecha(item.fecha)}</p>
                </div>
                <div className="flex shrink-0 items-center gap-4 text-xs text-[var(--ink-muted)]">
                  <span>{item.resumen?.visitas ?? 0} visitas</span>
                  <span>{porcentaje(item.resumen?.tasa_interaccion)}</span>
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => eliminar(item.id, e)}
                    onKeyDown={(e) => e.key === 'Enter' && eliminar(item.id, e)}
                    className="text-[var(--ink-muted)] hover:text-red-400"
                  >
                    Eliminar
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
