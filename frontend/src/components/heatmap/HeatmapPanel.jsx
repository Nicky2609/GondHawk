export function HeatmapPanel({ heatmapUrl }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]">
      <img src={heatmapUrl} alt="Mapa de calor de flujo en la tienda" className="h-full w-full object-cover" />
    </div>
  );
}