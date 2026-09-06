const ESTADO = {
  caliente: { label: 'Excelente', clase: 'badge-ok' },
  templada: { label: 'Mejorable', clase: 'badge-warn' },
  fria: { label: 'Crítica', clase: 'badge-bad' },
  sin_datos: { label: 'Sin datos', clase: 'badge-muted' },
};

function pct(v) {
  return `${Math.round((v ?? 0) * 100)} %`;
}

/** Rendimiento por góndola. Las columnas salen del embudo real, sin puntajes compuestos. */
export function PerformanceTable({ zonas, onSeleccionar, zonaSeleccionada }) {
  if (!zonas.length) {
    return (
      <section className="panel" data-tour="performance">
        <div className="panel-head"><h3>Rendimiento por góndola</h3></div>
        <p className="panel-empty">Analiza un video para ver el rendimiento por zona.</p>
      </section>
    );
  }

  return (
    <section className="panel" data-tour="performance">
      <div className="panel-head"><h3>Rendimiento por góndola</h3></div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Góndola</th><th>Flujo</th><th>Dwell</th>
              <th>Interacción</th><th>Rechazo</th><th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {zonas.map((z) => {
              const estado = ESTADO[z.temperatura] ?? ESTADO.sin_datos;
              return (
                <tr
                  key={z.zone_id}
                  onClick={() => onSeleccionar(z.zone_id === zonaSeleccionada ? null : z.zone_id)}
                  className={z.zone_id === zonaSeleccionada ? 'row-active' : ''}
                >
                  <td>{z.zone_id}</td>
                  <td>{(z.embudo?.visitas ?? 0).toLocaleString('es-CO')}</td>
                  <td>{(z.dwell_promedio_s ?? 0).toFixed(1)} s</td>
                  <td>{pct(z.tasa_interaccion)}</td>
                  <td>{pct(z.tasa_rechazo)}</td>
                  <td><span className={`badge ${estado.clase}`}>{estado.label}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
