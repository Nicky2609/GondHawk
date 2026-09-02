export function KpiStrip({ resumen }) {
  const items = [
    { label: 'Personas detectadas', valor: resumen.totalPersonasAprox },
    { label: 'Permanencia media', valor: `${resumen.dwellPromedioGlobal.toFixed(0)}s` },
    { label: 'Tasa de interacción', valor: `${Math.round(resumen.tasaInteraccionGlobal * 100)}%` },
    { label: 'Tasa de rechazo', valor: `${Math.round(resumen.tasaRechazoGlobal * 100)}%` },
  ];
  return (
    <div className="grid grid-cols-2 rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] sm:grid-cols-4">
      {items.map((item, i) => (
        <div key={item.label} className={`px-5 py-4 text-center ${i > 0 ? 'border-l border-[var(--panel-border)]' : ''}`}>
          <p className="text-xs text-[var(--ink-muted)]">{item.label}</p>
          <p className="mt-1 text-3xl">{item.valor}</p>
        </div>
      ))}
    </div>
  );
}