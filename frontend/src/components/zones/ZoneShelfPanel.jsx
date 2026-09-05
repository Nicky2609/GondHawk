import { zoneLabel } from '../../utils/color';

const ESTADO = {
  caliente: 'badge-ok',
  templada: 'badge-warn',
  fria: 'badge-bad',
  sin_datos: 'badge-muted',
};

/**
 * Tarjetas de estado por góndola.
 *
 * Rejilla fluida con auto-fit en vez de columnas fijas: los nombres
 * autogenerados (gondola_auto_1) son largos y no tienen espacios donde
 * cortar, así que con anchos fijos se salían de su tarjeta.
 */
export function ZoneShelfPanel({ zonasGondola }) {
  if (!zonasGondola?.length) {
    return <p className="text-sm text-[var(--ink-muted)]">Analiza un video para ver el estado por góndola.</p>;
  }

  return (
    <ul className="shelf-grid">
      {zonasGondola.map((zona) => (
        <li key={zona.zone_id} className="shelf-card">
          <p className="shelf-name" title={zona.zone_id}>{zoneLabel(zona.zone_id)}</p>

          <div className="shelf-metrics">
            <div>
              <span className="shelf-metric-value">{zona.embudo?.visitas ?? 0}</span>
              <span className="shelf-metric-label">visitas</span>
            </div>
            <div>
              <span className="shelf-metric-value">{zona.embudo?.toma_producto ?? 0}</span>
              <span className="shelf-metric-label">tomas</span>
            </div>
          </div>

          <div className="shelf-foot">
            <span className={`badge ${ESTADO[zona.temperatura] ?? 'badge-muted'}`}>
              {zona.temperatura ?? 'sin datos'}
            </span>
            <span className="shelf-dwell">{(zona.dwell_promedio_s ?? 0).toFixed(1)} s</span>
          </div>
        </li>
      ))}
    </ul>
  );
}