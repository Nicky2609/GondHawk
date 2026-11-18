export const API_BASE = 'http://localhost:8000';

export const ANALYSIS_DEFAULTS = {
  zonasAuto: false,
  frameSkip: 2,
};

export const DATA_SOURCES = {
  apiBase: API_BASE,
  analyzeVideo: `${API_BASE}/api/videos/analyze`,
  heatmapImage: `${API_BASE}/api/videos/heatmap`,
  historial: `${API_BASE}/api/analisis`,
  analisis: (id) => `${API_BASE}/api/analisis/${encodeURIComponent(id)}`,
  archivo: (id, nombre) => `${API_BASE}/api/analisis/${encodeURIComponent(id)}/archivo/${nombre}`,
  reporte: (id, formato) => `${API_BASE}/api/analisis/${encodeURIComponent(id)}/reporte/${formato}`,
  recomendaciones: (id) => `${API_BASE}/api/analisis/${encodeURIComponent(id)}/recomendaciones`,
};

export function buildAnalyzeUrl({ zonasAuto, frameSkip } = ANALYSIS_DEFAULTS) {
  const params = new URLSearchParams({
    zonas_auto: String(Boolean(zonasAuto)),
    frame_skip: String(frameSkip ?? 2),
  });
  return `${DATA_SOURCES.analyzeVideo}?${params.toString()}`;
}
