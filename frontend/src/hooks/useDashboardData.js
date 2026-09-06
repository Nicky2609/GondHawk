import { useState, useCallback } from 'react';
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
  zonasPropuestas: null,
  heatmapMatrix: null,
  analisisId: null,
  reportes: null,
};

function absoluta(ruta, cacheKey) {
  if (!ruta) return null;
  const base = ruta.startsWith('http') ? ruta : `${DATA_SOURCES.apiBase}${ruta}`;
  return cacheKey ? `${base}?analysis=${cacheKey}` : base;
}

async function fetchJson(url) {
  try {
    const resp = await fetch(url);
    if (resp.ok) return await resp.json();
  } catch {
    // ignore
  }
  return null;
}

export function normalizeAnalysisResponse(payload, cacheKey = '') {
  const interaction = payload?.interaction ?? payload ?? {};
  const pipeline = payload?.pipeline ?? {};
  const conteo = payload?.conteo_zonas ?? { zonas: [] };
  const analisisId = payload?.analisis_id ?? null;

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

  const updateFromAnalysis = useCallback(async (payload, cacheKey) => {
    const normalized = normalizeAnalysisResponse(payload, cacheKey);
    let zonasPropuestas = null;
    let heatmapMatrix = null;

    if (normalized.analisisId) {
      zonasPropuestas = await fetchJson(absoluta(`/api/analisis/${normalized.analisisId}/archivo/zonas_propuestas.json`, cacheKey));
      const heatmapRaw = await fetchJson(absoluta(`/api/analisis/${normalized.analisisId}/archivo/heatmap_raw.npy`, cacheKey));
      heatmapMatrix = heatmapRaw;
    } else if (payload?.pipeline?.salidas?.heatmap) {
      const heatmapPath = payload.pipeline.salidas.heatmap;
      const zonasPath = heatmapPath.replace('heatmap.png', 'zonas_propuestas.json');
      const rawPath = heatmapPath.replace('heatmap.png', 'heatmap_raw.npy');
      zonasPropuestas = await fetchJson(absoluta(zonasPath, cacheKey));
      heatmapMatrix = await fetchJson(absoluta(rawPath, cacheKey));
    }

    setData({ ...normalized, zonasPropuestas, heatmapMatrix });
  }, []);

  function resetData() {
    setData(EMPTY_DATA);
  }

  return { data, updateFromAnalysis, resetData };
}
