import { useState } from 'react';
import { DATA_SOURCES } from '../config/dataConfig';

const EMPTY_DATA = {
  zonasGondola: [],
  totalGlobal: { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
  alertas: [],
  resumenPipeline: {},
  conteoZonas: [],
  heatmapUrl: null,
  videoAnotadoUrl: null,
  zonasPropuestasUrl: null,
  analisisId: null,
  reportes: null,
};

function absoluta(ruta, cacheKey) {
  if (!ruta) return null;
  const base = ruta.startsWith('http') ? ruta : `${DATA_SOURCES.apiBase}${ruta}`;
  return cacheKey ? `${base}?analysis=${cacheKey}` : base;
}

export function normalizeAnalysisResponse(payload, cacheKey = '') {
  const interaction = payload?.interaction ?? payload ?? {};
  const pipeline = payload?.pipeline ?? {};
  const conteo = payload?.conteo_zonas ?? { zonas: [] };
  const analisisId = payload?.analisis_id ?? null;

   // El heatmap y el video SIEMPRE se sirven desde la carpeta del análisis.
  // payload.heatmap_url quedó guardado apuntando a /api/videos/heatmap, que
  // devuelve el último heatmap generado: al abrir un análisis del historial
  // mostraba la imagen del análisis más reciente.
  const archivoDelAnalisis = (nombre) =>
    analisisId ? absoluta(`/api/analisis/${analisisId}/archivo/${nombre}`, cacheKey) : null;

  return {
    zonasGondola: Array.isArray(interaction.zonas) ? interaction.zonas : [],
    totalGlobal: interaction.total ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
    alertas: Array.isArray(interaction.alertas) ? interaction.alertas : [],
    resumenPipeline: pipeline,
    conteoZonas: Array.isArray(conteo.zonas) ? conteo.zonas : [],
    heatmapUrl: archivoDelAnalisis('heatmap.png') ?? absoluta(payload?.heatmap_url, cacheKey),
    videoAnotadoUrl: archivoDelAnalisis('video_anotado.mp4') ?? absoluta(payload?.video_anotado_url, cacheKey),
    zonasPropuestasUrl: archivoDelAnalisis('zonas_propuestas.png'),
    analisisId,
    reportes: payload?.reportes ?? null,
  };
}

export function useDashboardData() {
  const [data, setData] = useState(EMPTY_DATA);

  function updateFromAnalysis(payload, cacheKey) {
    setData(normalizeAnalysisResponse(payload, cacheKey));
  }

  function resetData() {
    setData(EMPTY_DATA);
  }

  return { data, updateFromAnalysis, resetData };
}
