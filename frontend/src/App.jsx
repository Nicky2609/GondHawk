import { useEffect, useMemo, useRef, useState } from 'react';
import { useDashboardData } from './hooks/useDashboardData';
import { resumenGlobal } from './utils/aggregate';
import { Header } from './components/layout/Header';
import { KpiStrip } from './components/kpis/KpiStrip';
import { ZoneShelfPanel } from './components/zones/ZoneShelfPanel';
import { HeatmapPanel } from './components/heatmap/HeatmapPanel';
import { ZoneFunnelTable } from './components/funnel/ZoneFunnelTable';
import { AlertsPanel } from './components/alerts/AlertsPanel';

const SAFE_ENDPOINTS = {
  analyze: '/api/videos/analyze',
  latest: '/api/videos/latest',
  heatmap: '/api/videos/heatmap',
};

export default function App() {
  const { data, status, error } = useDashboardData();
  const [selectedFile, setSelectedFile] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisMessage, setAnalysisMessage] = useState('Listo para analizar un video.');
  const [lastResult, setLastResult] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const currentData = useMemo(() => {
    if (!data) return null;
    return {
      ...data,
      totalGlobal: data.totalGlobal ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
      zonasGondola: data.zonasGondola ?? [],
      alertas: data.alertas ?? [],
    };
  }, [data]);

  if (status === 'loading') return <Estado texto="Cargando métricas…" />;
  if (status === 'error') return <Estado texto={`No se pudo cargar: ${error.message}`} />;

  const resumen = resumenGlobal(currentData.totalGlobal, currentData.zonasGondola);

  const handleAnalyze = async () => {
    if (!selectedFile) {
      setAnalysisMessage('Selecciona un video antes de analizar.');
      return;
    }

    setProcessing(true);
    setProgress(0);
    setAnalysisMessage(`Analizando ${selectedFile.name}...`);

    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setProgress((prev) => {
        const next = prev + 12;
        return next >= 100 ? 100 : next;
      });
    }, 220);

    try {
      const formData = new FormData();
      formData.append('video', selectedFile);

      const response = await fetch(SAFE_ENDPOINTS.analyze, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Endpoint no disponible aún');
      }

      const payload = await response.json();
      setLastResult(payload);
      setAnalysisMessage('Análisis completado correctamente.');
    } catch {
      setLastResult((prev) => prev ?? {
        mensaje: 'Modo de prueba: el endpoint backend aún no está conectado, pero la UI de análisis queda preparada para el flujo real.',
      });
      setAnalysisMessage('Uso de prueba: endpoint aún no implementado en backend.');
    } finally {
      if (timerRef.current) clearInterval(timerRef.current);
      setProgress(100);
      setTimeout(() => setProcessing(false), 500);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <Header />

      <section className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-[var(--ink-muted)]">Análisis de video</p>
            <h2 className="mt-2 text-2xl font-semibold">Carga y procesamiento del flujo</h2>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="inline-flex cursor-pointer items-center justify-center rounded-xl border border-[var(--panel-border)] bg-[#12231d] px-4 py-2 text-sm font-medium text-[var(--ink)] transition hover:border-[var(--accent)]">
              <input
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              />
              {selectedFile ? 'Cambiar video' : 'Seleccionar video'}
            </label>

            <button
              type="button"
              onClick={handleAnalyze}
              disabled={processing}
              className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-[#07150f] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {processing ? 'Analizando...' : 'Analizar video'}
            </button>
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-4 rounded-xl border border-[var(--panel-border)] bg-[#0d1a16] p-4 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.18em] text-[var(--ink-muted)]">Archivo</p>
            <p className="mt-1 truncate text-sm text-[var(--ink)]">
              {selectedFile ? selectedFile.name : 'Sin archivo seleccionado'}
            </p>
          </div>

          <div className="flex items-center gap-4">
            <div className="relative h-12 w-12">
              <svg viewBox="0 0 100 100" className="h-12 w-12 -rotate-90">
                <circle cx="50" cy="50" r="42" stroke="rgba(255,255,255,0.15)" strokeWidth="10" fill="none" />
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  stroke="var(--accent)"
                  strokeWidth="10"
                  strokeLinecap="round"
                  fill="none"
                  strokeDasharray={264}
                  strokeDashoffset={264 - (264 * progress) / 100}
                  style={{ transition: 'stroke-dashoffset 0.25s ease' }}
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-[var(--ink)]">
                {progress}%
              </span>
            </div>

            <div className="text-sm text-[var(--ink-muted)]">
              <p>{processing ? 'Procesando video' : 'Pendiente'}</p>
              <p className="text-xs">{analysisMessage}</p>
            </div>
          </div>
        </div>

        {lastResult && (
          <div className="mt-4 rounded-xl border border-[var(--panel-border)] bg-[#0f2018] p-3 text-sm text-[var(--ink-muted)]">
            {lastResult.mensaje ?? 'Última ejecución preparada para el backend real.'}
          </div>
        )}
      </section>

      <KpiStrip resumen={resumen} />

      <div className="grid gap-4 lg:grid-cols-2">
        <ZoneShelfPanel zonasGondola={currentData.zonasGondola} />
        <HeatmapPanel heatmapUrl={currentData.heatmapUrl} />
      </div>

      <ZoneFunnelTable zonasGondola={currentData.zonasGondola} />
      <AlertsPanel alertas={currentData.alertas} />
    </div>
  );
}

function Estado({ texto }) {
  return <p className="p-6 text-sm text-[var(--ink-muted)]">{texto}</p>;
}