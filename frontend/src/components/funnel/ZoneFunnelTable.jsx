import { zoneLabel } from '../../utils/color';

export function ZoneFunnelTable({ zonasGondola }) {
  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4">
      <p className="mb-3 text-sm text-[var(--ink-muted)]">Embudo por góndola</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--panel-border)] text-left text-[var(--ink-muted)]">
            <th className="py-2 font-normal">Góndola</th>
            <th className="py-2 font-normal">Aproximación</th>
            <th className="py-2 font-normal">Toma</th>
            <th className="py-2 font-normal">Devolución</th>
          </tr>
        </thead>
        <tbody>
          {zonasGondola.map((zona) => (
            <tr key={zona.zone_id} className="border-b border-[var(--panel-border)] last:border-0">
              <td className="py-2">{zoneLabel(zona.zone_id)}</td>
              <td className="py-2">{zona.embudo.se_detiene}</td>
              <td className="py-2">{zona.embudo.toma_producto}</td>
              <td className="py-2">{zona.embudo.devuelve}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}