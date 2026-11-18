import { useRef, useState } from 'react';
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
  tracking: [],
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

  const archivo = (nombre) =>
    analisisId
      ? absoluta(`/api/analisis/${encodeURIComponent(analisisId)}/archivo/${nombre}`, cacheKey)
      : null;

  return {
    zonasGondola: Array.isArray(interaction.zonas) ? interaction.zonas : [],
    totalGlobal: interaction.total ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
    alertas: Array.isArray(interaction.alertas) ? interaction.alertas : [],
    resumenPipeline: pipeline,
    conteoZonas: Array.isArray(conteo.zonas) ? conteo.zonas : [],
    heatmapUrl: archivo('heatmap.png') ?? absoluta(payload?.heatmap_url, cacheKey),
    videoAnotadoUrl: archivo('video_anotado.mp4') ?? absoluta(payload?.video_anotado_url, cacheKey),
    zonasPropuestasUrl: archivo('zonas_propuestas.png'),
    zonasPropuestasJsonUrl: archivo('zonas_propuestas.json'),
    zonasUsadasJsonUrl: archivo('zonas_usadas.json'),
    conteoZonasJsonUrl: archivo('conteo_zonas.json'),
    trackingUrl: archivo('tracking.jsonl'),
    zonasPropuestas: null,
    tracking: [],
    analisisId,
    reportes: payload?.reportes ?? null,
    mensaje: payload?.mensaje ?? null,
  };
}

function parseJsonl(texto) {
  return texto
    .split('\n')
    .map((linea) => linea.trim())
    .filter(Boolean)
    .map((linea) => {
      try {
        return JSON.parse(linea);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

export function useDashboardData() {
  const [data, setData] = useState(EMPTY_DATA);
  const [status] = useState('ready');
  const [error, setError] = useState(null);
  const generacionRef = useRef(0);

  function updateFromAnalysis(payload, cacheKey) {
    const generacion = ++generacionRef.current;
    const normalizado = normalizeAnalysisResponse(payload, cacheKey);
    setData(normalizado);
    setError(null);

    const fuentesZonas = [
      normalizado.zonasPropuestasJsonUrl,
      normalizado.zonasUsadasJsonUrl,
    ].filter(Boolean);

    (async () => {
      for (const url of fuentesZonas) {
        try {
          const res = await fetch(url);
          if (!res.ok) continue;
          const zonasPropuestas = await res.json();
          if (zonasPropuestas?.zonas?.length) {
            if (generacionRef.current !== generacion) return;
            setData((prev) => ({ ...prev, zonasPropuestas }));
            return;
          }
        } catch {
          // se intenta la siguiente fuente
        }
      }
    })();

    if (normalizado.conteoZonas.length === 0 && normalizado.conteoZonasJsonUrl) {
      fetch(normalizado.conteoZonasJsonUrl)
        .then((res) => (res.ok ? res.json() : null))
        .then((conteo) => {
          const zonas = Array.isArray(conteo?.zonas) ? conteo.zonas : [];
          if (!zonas.length || generacionRef.current !== generacion) return;
          setData((prev) => (prev.conteoZonas.length ? prev : { ...prev, conteoZonas: zonas }));
        })
        .catch(() => {});
    }

    if (normalizado.trackingUrl) {
      fetch(normalizado.trackingUrl)
        .then((res) => (res.ok ? res.text() : null))
        .then((texto) => {
          if (!texto) return;
          if (generacionRef.current !== generacion) return;
          setData((prev) => ({ ...prev, tracking: parseJsonl(texto) }));
        })
        .catch(() => {});
    }
  }

  function resetData() {
    generacionRef.current += 1;
    setData(EMPTY_DATA);
    setError(null);
  }

  return { data, status, error, updateFromAnalysis, resetData };
}