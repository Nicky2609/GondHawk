import { useState } from 'react';
import { DATA_SOURCES } from '../config/dataConfig';

const EMPTY_DATA = {
  zonasGondola: [],
  totalGlobal: { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
  alertas: [],
  resumenPipeline: {},
  conteoZonas: [],
  heatmapUrl: null,
};

export function normalizeAnalysisResponse(payload, cacheKey = '') {
  const interaction = payload?.interaction ?? payload ?? {};
  const pipeline = payload?.pipeline ?? {};
  const conteo = payload?.conteo_zonas ?? { zonas: [] };

  return {
    zonasGondola: Array.isArray(interaction.zonas) ? interaction.zonas : [],
    totalGlobal: interaction.total ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
    alertas: Array.isArray(interaction.alertas) ? interaction.alertas : [],
    resumenPipeline: pipeline,
    conteoZonas: Array.isArray(conteo.zonas) ? conteo.zonas : [],
    heatmapUrl: payload?.heatmap_url
      ? `${DATA_SOURCES.apiBase}${payload.heatmap_url}${cacheKey ? `?analysis=${cacheKey}` : ''}`
      : null,
  };
}

export function useDashboardData() {
  const [data, setData] = useState(EMPTY_DATA);
  const [status] = useState('ready');
  const [error, setError] = useState(null);

  function updateFromAnalysis(payload, cacheKey) {
    setData(normalizeAnalysisResponse(payload, cacheKey));
    setError(null);
  }

  function resetData() {
    setData(EMPTY_DATA);
    setError(null);
  }

  return { data, status, error, updateFromAnalysis, resetData };
}