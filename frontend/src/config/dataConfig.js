export const USE_MOCK = false;

const BASE = USE_MOCK ? '/mock' : '/data';

export const DATA_SOURCES = {
  metricasInteraccion: `${BASE}/metricas_interaccion.json`,
  metricasPipeline: `${BASE}/metricas_pipeline.json`,
  conteoZonas: `${BASE}/conteo_zonas.json`,
  heatmapImage: `${BASE}/heatmap.png`,
};