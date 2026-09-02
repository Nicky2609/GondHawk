import { zoneLabel } from '../../utils/color';

export function AlertsPanel({ alertas }) {
  if (alertas.length === 0) {
    return <p className="text-sm text-[var(--ink-muted)]">Sin alertas activas.</p>;
  }
  return (
    <ul className="divide-y divide-[var(--panel-border)] rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4">
      {alertas.map((a, i) => (
        <li key={i} className="py-2 text-sm">
          <span className="font-medium">{zoneLabel(a.zone_id)}</span> — {a.mensaje}
        </li>
      ))}
    </ul>
  );
}