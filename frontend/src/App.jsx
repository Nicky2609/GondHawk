import { useEffect, useMemo, useRef, useState } from 'react';
import { useDashboardData } from './hooks/useDashboardData';
import { resumenGlobal } from './utils/aggregate';
import { Header } from './components/layout/Header';
import { KpiStrip } from './components/kpis/KpiStrip';
import { ZoneShelfPanel } from './components/zones/ZoneShelfPanel';
import { HeatmapPanel } from './components/heatmap/HeatmapPanel';
import { VideoPanel } from './components/video/VideoPanel';
import { StoreMapPanel } from './components/storemap/StoreMapPanel';
import { ZoneFunnelTable } from './components/funnel/ZoneFunnelTable';
import { AlertsPanel } from './components/alerts/AlertsPanel';
import { ANALYSIS_DEFAULTS, DATA_SOURCES, buildAnalyzeUrl } from './config/dataConfig';
import { BarChart3, Boxes, ChartNoAxesCombined, Gauge, House, Map, MapPin, ShieldCheck, Video } from 'lucide-react';

export default function App() {
  const { data, status, error, updateFromAnalysis, resetData } = useDashboardData();
  const [selectedFile, setSelectedFile] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisMessage, setAnalysisMessage] = useState('Listo para analizar un video.');
  const [lastResult, setLastResult] = useState(null);
  const [analysisCompleted, setAnalysisCompleted] = useState(false);
  const fileInputRef = useRef(null);
  const timerRef = useRef(null);
  const [activeSection, setActiveSection] = useState('cargar');
  const [frameSkip, setFrameSkip] = useState(ANALYSIS_DEFAULTS.frameSkip);
  const [videoTime, setVideoTime] = useState(0);
  const inicializadoRef = useRef(false);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    if (inicializadoRef.current) return;
    inicializadoRef.current = true;
    let vigente = true;
    (async () => {
      try {
        const res = await fetch(`${DATA_SOURCES.historial}?limite=1`);
        if (!res.ok || !vigente) return;
        const lista = await res.json();
        const ultimo = Array.isArray(lista?.analisis) ? lista.analisis[0] : null;
        if (!ultimo?.id || !vigente) return;
        const resDet = await fetch(DATA_SOURCES.analisis(ultimo.id));
        if (!resDet.ok || !vigente) return;
        const detalle = await resDet.json();
        if (!vigente) return;
        updateFromAnalysis({ ...(detalle.detalle ?? detalle), analisis_id: ultimo.id }, Date.now());
      } catch {
        // sin historial disponible al inicio
      }
    })();
    return () => {
      vigente = false;
    };
  }, []);

  useEffect(() => {
    const sectionIds = ['cargar', 'video', 'mapa-calor', 'mapa-tienda', 'estado-gondola', 'embudo-gondola', 'recomendaciones'];
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter(Boolean);

    const observer = new IntersectionObserver(
      (entries) => {
        const visibleSections = entries
          .filter((entry) => entry.isIntersecting)
          .sort((first, second) => first.boundingClientRect.top - second.boundingClientRect.top);

        if (visibleSections[0]) setActiveSection(visibleSections[0].target.id);
      },
      { rootMargin: '-18% 0px -68% 0px', threshold: 0 },
    );

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
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
    setVideoTime(0);
    resetData();
    setLastResult(null);
    setAnalysisCompleted(false);
    setAnalysisMessage(`Analizando ${selectedFile.name}...`);

    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setProgress((prev) => {
        const next = prev + 12;
        return next >= 100 ? 100 : next;
      });
    }, 220);

    let analysisSucceeded = false;

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await fetch(buildAnalyzeUrl({ zonasAuto: false, frameSkip }), {
        method: 'POST',
        body: formData,
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (!response.ok) {
        const detail = typeof payload?.detail === 'string'
          ? payload.detail
          : typeof payload?.message === 'string'
            ? payload.message
            : 'El backend rechazó la solicitud.';
        throw new Error(detail);
      }

      analysisSucceeded = true;
      setLastResult(payload);
      updateFromAnalysis(payload, Date.now());
      setAnalysisCompleted(true);
      const realMessage = typeof payload?.mensaje === 'string'
        ? payload.mensaje
        : typeof payload?.message === 'string'
          ? payload.message
          : `Análisis completado para ${selectedFile.name}.`;
      setAnalysisMessage(realMessage);
    } catch (err) {
      const realError = err instanceof Error ? err.message : 'No se pudo completar la solicitud.';
      setLastResult({ mensaje: realError });
      setAnalysisMessage(realError);
    } finally {
      if (timerRef.current) clearInterval(timerRef.current);
      setProgress(analysisSucceeded ? 100 : 0);
      setProcessing(false);
    }
  };

  const handleClearInformation = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    setVideoTime(0);
    resetData();
    setSelectedFile(null);
    setProcessing(false);
    setProgress(0);
    setAnalysisMessage('Listo para analizar un video.');
    setLastResult(null);
    setAnalysisCompleted(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><Gauge size={16} /></span><p className="brand-name">GondHawk<span>Funcionalidades</span></p></div>
        <nav className="nav-list" aria-label="Navegación principal">
          <a className={`nav-item ${activeSection === 'cargar' ? 'active' : ''}`} href="#cargar"><House size={14} />Cargar video</a>
          <a className={`nav-item ${activeSection === 'video' ? 'active' : ''}`} href="#video"><Video size={14} />Video y personas</a>
          <a className={`nav-item ${activeSection === 'mapa-calor' ? 'active' : ''}`} href="#mapa-calor"><Map size={14} />Mapa de calor</a>
          <a className={`nav-item ${activeSection === 'mapa-tienda' ? 'active' : ''}`} href="#mapa-tienda"><MapPin size={14} />Mapa de seguimiento</a>
          <a className={`nav-item ${activeSection === 'estado-gondola' ? 'active' : ''}`} href="#estado-gondola"><ChartNoAxesCombined size={14} />Estado por góndola</a>
          <a className={`nav-item ${activeSection === 'embudo-gondola' ? 'active' : ''}`} href="#embudo-gondola"><Boxes size={14} />Embudo por góndola</a>
          <a className={`nav-item ${activeSection === 'recomendaciones' ? 'active' : ''}`} href="#recomendaciones"><BarChart3 size={14} />Recomendaciones</a>
        </nav>
        <div className="sidebar-foot"><strong><ShieldCheck size={13} /> Privacidad por diseño</strong>Procesamiento local y métricas anónimas.</div>
      </aside>

      <main className="main-content">
        <div className="dashboard-header">
          <Header />
        </div>

        <div className="content-stack">
          <section id="cargar" className="analysis-card">
            <div className="analysis-card-head">
              <div><p className="eyebrow">Análisis de video</p><h2>Carga y procesamiento del flujo</h2><p className="muted">Selecciona un archivo para generar las métricas de esta sesión.</p></div>
              <div className="upload-actions">
                {analysisCompleted ? (
                  <button type="button" onClick={handleClearInformation} className="analyze-button">Limpiar información</button>
                ) : (
                  <>
                    <label className="upload-button">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/*"
                        className="hidden"
                        onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                      />
                      {selectedFile ? 'Cambiar video' : 'Seleccionar video'}
                    </label>
                    <button type="button" onClick={handleAnalyze} disabled={processing} className="analyze-button">
                      {processing ? 'Analizando...' : 'Analizar video'}
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="analysis-options">
              <label className="analysis-option">
                <span>
                  Frames analizados
                  <small>Saltar frames acelera el análisis del video.</small>
                </span>
                <select
                  value={frameSkip}
                  disabled={processing}
                  onChange={(event) => setFrameSkip(Number(event.target.value))}
                >
                  <option value={1}>Todos (mejor precisión)</option>
                  <option value={2}>1 de cada 2 (recomendado)</option>
                  <option value={3}>1 de cada 3 (más rápido)</option>
                </select>
              </label>
            </div>

            <div className="file-status">
              <div className="min-w-0"><p className="eyebrow">Archivo seleccionado</p><p className="mt-1 truncate text-sm text-[var(--ink)]">
                {selectedFile ? selectedFile.name : 'Sin archivo seleccionado'}
              </p></div>

              <div className="progress-wrap"><div className="progress-ring"><svg viewBox="0 0 100 100">
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
              </svg><span>{progress}%</span></div><div><p>{processing ? 'Procesando video' : 'Listo para analizar'}</p><p>{analysisMessage}</p></div></div>
            </div>

            {lastResult && (
              <div className="result-message">
                {lastResult.mensaje ?? lastResult.detail ?? lastResult.message ?? 'Análisis completado.'}
              </div>
            )}
          </section>

          <KpiStrip resumen={resumen} />

          <div className="media-grid">
            <section id="video" className="panel dashboard-zone">
              <div className="panel-head">
                <h3>Video e identificación</h3>
                <span className="badge-anon">Anonimizado</span>
              </div>
              <VideoPanel
                videoUrl={currentData.videoAnotadoUrl}
                zonasUrl={currentData.zonasPropuestasUrl}
                embebido
                onTimeUpdate={setVideoTime}
              />
            </section>

            <section id="mapa-calor" className="panel dashboard-zone">
              <div className="panel-head"><h3>Mapa de calor de flujo</h3></div>
              <HeatmapPanel heatmapUrl={currentData.heatmapUrl} />
            </section>
          </div>

          <section id="mapa-tienda" className="panel dashboard-zone">
            <StoreMapPanel
              zonasData={currentData.zonasPropuestas}
              conteoZonas={currentData.conteoZonas}
              tracking={currentData.tracking}
              currentTimeSec={videoTime}
            />
          </section>

          <div id="estado-gondola" className="dashboard-zone">
            <ZoneShelfPanel zonasGondola={currentData.zonasGondola} />
          </div>

          <div id="embudo-gondola" className="dashboard-zone">
            <ZoneFunnelTable zonasGondola={currentData.zonasGondola} />
          </div>

          <div id="recomendaciones" className="dashboard-zone">
            <AlertsPanel alertas={currentData.alertas} />
          </div>
        </div>
      </main>
    </div>
  );
}

function Estado({ texto }) {
  return <p className="p-6 text-sm text-[var(--ink-muted)]">{texto}</p>;
}