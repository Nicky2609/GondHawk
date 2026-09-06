import { useEffect, useMemo, useRef, useState } from 'react';
import { useDashboardData } from './hooks/useDashboardData';
import { resumenGlobal } from './utils/aggregate';
import { Header } from './components/layout/Header';
import { KpiStrip } from './components/kpis/KpiStrip';
import { ZoneShelfPanel } from './components/zones/ZoneShelfPanel';
import { HeatmapPanel } from './components/heatmap/HeatmapPanel';
import { ZoneFunnelTable } from './components/funnel/ZoneFunnelTable';
import { AlertsPanel } from './components/alerts/AlertsPanel';
import { VideoPanel } from './components/video/VideoPanel';
import { StoreMapPanel } from './components/storemap/StoreMapPanel';
import { FunnelPanel } from './components/dashboard/FunnelPanel';
import { PerformanceTable } from './components/dashboard/PerformanceTable';
import { PrivacyBar } from './components/dashboard/PrivacyBar';
import { DayRecapPanel } from './components/dashboard/DayRecapPanel';
import { HistoryPanel } from './components/history/HistoryPanel';
import { ReportDownloads } from './components/reports/ReportDownloads';
import { ProductTour } from './components/product-tour/ProductTour';
import { ANALYSIS_DEFAULTS, DATA_SOURCES, buildAnalyzeUrl } from './config/dataConfig';
import { BarChart3, Boxes, ChartNoAxesCombined, Clock, Gauge, House, Map, MapPin, PlayCircle, ShieldCheck } from 'lucide-react';

export default function App() {
  const { data, updateFromAnalysis, resetData } = useDashboardData();
  const [selectedFile, setSelectedFile] = useState(null);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisMessage, setAnalysisMessage] = useState('Listo para analizar un video.');
  const [lastResult, setLastResult] = useState(null);
  const [analysisCompleted, setAnalysisCompleted] = useState(false);
  const fileInputRef = useRef(null);
  const timerRef = useRef(null);
  const [activeSection, setActiveSection] = useState('cargar');
  const [zonasAuto, setZonasAuto] = useState(ANALYSIS_DEFAULTS.zonasAuto);
  const [frameSkip, setFrameSkip] = useState(ANALYSIS_DEFAULTS.frameSkip);
  const [recomendaciones, setRecomendaciones] = useState(null);
  const [fuenteReco, setFuenteReco] = useState(null);
  const [historialKey, setHistorialKey] = useState(0);
  const [zonaSeleccionada, setZonaSeleccionada] = useState(null);
  const [tourOpen, setTourOpen] = useState(false);
  const [videoTime, setVideoTime] = useState(0);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    const sectionIds = ['cargar', 'video', 'mapa-calor', 'mapa-tienda', 'estado-gondola', 'embudo-gondola', 'recomendaciones', 'historial'];
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

  const resumen = resumenGlobal(currentData.totalGlobal, currentData.zonasGondola);

  const handleAnalyze = async () => {
    if (!selectedFile) {
      setAnalysisMessage('Selecciona un video antes de analizar.');
      return;
    }

    setProcessing(true);
    setProgress(0);
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

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await fetch(buildAnalyzeUrl({ zonasAuto, frameSkip }), {
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

      setLastResult(payload);
      updateFromAnalysis(payload, Date.now());
      setAnalysisCompleted(true);
      setHistorialKey((k) => k + 1);

      // Las recomendaciones se piden aparte: si el motor falla, el resto del
      // análisis ya está en pantalla y no se pierde.
      if (payload?.analisis_id) {
        fetch(DATA_SOURCES.recomendaciones(payload.analisis_id))
          .then((r) => (r.ok ? r.json() : null))
          .then((reco) => {
            if (!reco) return;
            setRecomendaciones(reco.recomendaciones ?? []);
            setFuenteReco(reco.fuente ?? null);
          })
          .catch(() => { });
      }
      const realMessage = typeof payload?.message === 'string'
        ? payload.message
        : typeof payload?.status === 'string'
          ? payload.status
          : `Análisis completado para ${selectedFile.name}.`;
      setAnalysisMessage(realMessage);
    } catch (err) {
      const realError = err instanceof Error ? err.message : 'No se pudo completar la solicitud.';
      setLastResult((prev) => prev ?? { mensaje: realError });
      setAnalysisMessage(realError);
    } finally {
      if (timerRef.current) clearInterval(timerRef.current);
      setProgress(100);
      setTimeout(() => setProcessing(false), 500);
    }
  };

  const handleClearInformation = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    resetData();
    setSelectedFile(null);
    setProcessing(false);
    setProgress(0);
    setAnalysisMessage('Listo para analizar un video.');
    setLastResult(null);
    setAnalysisCompleted(false);
    setRecomendaciones(null);
    setFuenteReco(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" data-tour="welcome"><span className="brand-mark"><Gauge size={16} /></span><p className="brand-name">GondHawk<span>Funcionalidades</span></p></div>
        <nav className="nav-list" aria-label="Navegación principal">
          <a className={`nav-item ${activeSection === 'cargar' ? 'active' : ''}`} href="#cargar"><House size={14} />Cargar video</a>
          <a className={`nav-item ${activeSection === 'video' ? 'active' : ''}`} href="#video"><PlayCircle size={14} />Video analizado</a>
          <a className={`nav-item ${activeSection === 'mapa-calor' ? 'active' : ''}`} href="#mapa-calor"><Map size={14} />Mapa de calor</a>
          <a className={`nav-item ${activeSection === 'mapa-tienda' ? 'active' : ''}`} href="#mapa-tienda"><MapPin size={14} />Mapa de tienda</a>
          <a className={`nav-item ${activeSection === 'estado-gondola' ? 'active' : ''}`} href="#estado-gondola"><ChartNoAxesCombined size={14} />Estado por góndola</a>
          <a className={`nav-item ${activeSection === 'embudo-gondola' ? 'active' : ''}`} href="#embudo-gondola"><Boxes size={14} />Embudo por góndola</a>
          <a className={`nav-item ${activeSection === 'recomendaciones' ? 'active' : ''}`} href="#recomendaciones"><BarChart3 size={14} />Recomendaciones</a>
          <a className={`nav-item ${activeSection === 'historial' ? 'active' : ''}`} href="#historial"><Clock size={14} />Historial</a>
        </nav>
        <button type="button" className="product-tour-launch" onClick={() => setTourOpen(true)} aria-label="Ver recorrido guiado">
          ? Ver tour
        </button>
        <div className="sidebar-foot"><strong><ShieldCheck size={13} /> Privacidad por diseño</strong>Procesamiento local y métricas anónimas.</div>
      </aside>

      <main className="main-content">
        <div className="dashboard-header">
          <Header
            frames={currentData.resumenPipeline?.frames_procesados}
            tiempo={currentData.resumenPipeline?.tiempo_procesamiento_seg}
          />
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
                    <label className="upload-button" data-tour="upload-video">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/*"
                        className="hidden"
                        onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                      />
                      {selectedFile ? 'Cambiar video' : 'Seleccionar video'}
                    </label>
                    <button type="button" onClick={handleAnalyze} disabled={processing} className="analyze-button" data-tour="start-analysis">
                      {processing ? 'Analizando...' : 'Analizar video'}
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="analysis-options" data-tour="analysis-options">
              <label className="analysis-option">
                <input
                  type="checkbox"
                  checked={zonasAuto}
                  onChange={(event) => setZonasAuto(event.target.checked)}
                />
                <span>
                  Detectar zonas automáticamente
                  <small>Recomendado. Sin esto se usan las zonas del video de calibración.</small>
                </span>
              </label>
              <label className="analysis-option">
                <span>
                  Frames analizados
                  <small>Saltar frames acelera el análisis pero fragmenta el seguimiento.</small>
                </span>
                <select value={frameSkip} onChange={(event) => setFrameSkip(Number(event.target.value))}>
                  <option value={1}>Todos (mejor precisión)</option>
                  <option value={2}>1 de cada 2</option>
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
                {lastResult.message ?? lastResult.detail ?? lastResult.mensaje ?? 'El backend no devolvió un mensaje.'}
              </div>
            )}
          </section>

          <KpiStrip resumen={resumen} />

          <DayRecapPanel
            totalGlobal={currentData.totalGlobal}
            zonasGondola={currentData.zonasGondola}
            conteoZonas={currentData.conteoZonas}
          />

{/* Primera fila: Video + Mapa de calor */}
          <div id="video" className="dashboard-grid dashboard-grid-2">
            <section className="panel">
              <div className="panel-head">
                <h3>Video analizado</h3>
                <span className="badge badge-ok">Anonimizado</span>
              </div>
              <VideoPanel
                videoUrl={currentData.videoAnotadoUrl}
                zonasUrl={currentData.zonasPropuestasUrl}
                embebido
                onTimeUpdate={setVideoTime}
              />
            </section>

            <section id="mapa-calor" className="panel" data-tour="heatmap">
              <div className="panel-head"><h3>Mapa de calor de flujo</h3></div>
              <HeatmapPanel heatmapUrl={currentData.heatmapUrl} />
            </section>
          </div>

          {/* Segunda fila: Embudo + Mapa de tienda */}
          <div className="dashboard-grid dashboard-grid-2">
            <FunnelPanel
              total={currentData.totalGlobal}
              zonas={currentData.zonasGondola}
              zonaSeleccionada={zonaSeleccionada}
              onSeleccionar={setZonaSeleccionada}
            />

            <section id="mapa-tienda" className="panel" data-tour="store-map">
              <StoreMapPanel
                zonasData={currentData.zonasPropuestas}
                conteoZonas={currentData.conteoZonas}
                tracking={currentData.tracking}
                currentTimeSec={videoTime}
              />
            </section>
          </div>

          {/* Tercera fila: Estado góndola + Recomendaciones */}
          <div id="estado-gondola" className="dashboard-grid dashboard-grid-2">
            <PerformanceTable
              zonas={currentData.zonasGondola}
              zonaSeleccionada={zonaSeleccionada}
              onSeleccionar={setZonaSeleccionada}
            />

            <section id="recomendaciones" className="panel" data-tour="recommendations">
              <div className="panel-head"><h3>Recomendaciones</h3></div>
              <div className="panel-body">
                <AlertsPanel
                  alertas={currentData.alertas}
                  recomendaciones={recomendaciones}
                  fuente={fuenteReco}
                />
              </div>
            </section>
          </div>

          <div id="embudo-gondola" className="dashboard-grid dashboard-grid-2">
            <section className="panel">
              <div className="panel-head"><h3>Detalle por góndola</h3></div>
              <div className="panel-body">
                <ZoneShelfPanel zonasGondola={currentData.zonasGondola} />
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <h3>Embudo detallado</h3>
              </div>
              <div className="panel-body">
                <ZoneFunnelTable zonasGondola={currentData.zonasGondola} />
                {currentData.analisisId && (
                  <div className="mt-4">
                    <ReportDownloads analisisId={currentData.analisisId} />
                  </div>
                )}
              </div>
            </section>
          </div>

          <div id="historial" className="dashboard-grid dashboard-grid-2">
            <HistoryPanel
              recargar={historialKey}
              onAbrir={(detalle, id) => {
                updateFromAnalysis({ ...detalle, analisis_id: id }, Date.now());
                setAnalysisCompleted(true);
                setAnalysisMessage(`Mostrando análisis de ${detalle?.video ?? id}.`);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
            />
            <PrivacyBar />
          </div>

        </div>
      </main>
      <ProductTour isOpen={tourOpen} onClose={() => setTourOpen(false)} />
    </div>
  );
}