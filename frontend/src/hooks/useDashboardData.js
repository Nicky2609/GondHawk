import { useState } from 'react';
import { DATA_SOURCES } from '../config/dataConfig';

const EMPTY_DATA = {
  zonasGondola: [],
  totalGlobal: { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
  alertas: [],
  recomendaciones: [],
  recomendacionesFuente: null,
  resumenPipeline: {},
  conteoZonas: [],
  heatmapUrl: null,
  videoAnotadoUrl: null,
  zonasPropuestasUrl: null,
  analisisId: null,
  reportes: null,
  mensaje: null,
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

  // Los archivos SIEMPRE se sirven desde la carpeta del análisis. El campo
  // heatmap_url quedó guardado apuntando a /api/videos/heatmap, que devuelve
  // el último heatmap generado: al abrir un análisis del historial se veía la
  // imagen del análisis más reciente.
  const archivo = (nombre) =>
    analisisId ? absoluta(`/api/analisis/${analisisId}/archivo/${nombre}`, cacheKey) : null;

  return {
    zonasGondola: Array.isArray(interaction.zonas) ? interaction.zonas : [],
    totalGlobal: interaction.total ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
    alertas: Array.isArray(interaction.alertas) ? interaction.alertas : [],

    // El pipeline ya deja las recomendaciones dentro de las métricas, así que
    // no hace falta pedirlas por separado; el endpoint queda como respaldo
    // para análisis guardados antes de ese cambio.
    recomendaciones: Array.isArray(interaction.recomendaciones)
      ? interaction.recomendaciones
      : Array.isArray(payload?.recomendaciones)
        ? payload.recomendaciones
        : [],
    recomendacionesFuente: interaction.recomendaciones_fuente ?? null,

    resumenPipeline: pipeline,
    conteoZonas: Array.isArray(conteo.zonas) ? conteo.zonas : [],
    heatmapUrl: archivo('heatmap.png') ?? absoluta(payload?.heatmap_url, cacheKey),
    videoAnotadoUrl: archivo('video_anotado.mp4') ?? absoluta(payload?.video_anotado_url, cacheKey),
    zonasPropuestasUrl: archivo('zonas_propuestas.png'),
    analisisId,
    reportes: payload?.reportes ?? null,
    mensaje: payload?.mensaje ?? null,
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
