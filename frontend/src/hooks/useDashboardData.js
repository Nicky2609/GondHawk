import { useEffect, useState } from 'react';
import { DATA_SOURCES } from '../config/dataConfig';

const fallbackPipeline = {
  estado: 'mock',
  total: 0,
  resumen: 'Datos de prueba en modo mock',
};

async function safeJsonFetch(url, fallback) {
  try {
    const response = await fetch(url);
    if (!response.ok) return fallback;
    const text = await response.text();
    if (!text || text.trim() === '') return fallback;

    try {
      return JSON.parse(text);
    } catch {
      return fallback;
    }
  } catch {
    return fallback;
  }
}

export function useDashboardData() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelado = false;

    async function cargar() {
      try {
        const [metricasInteraccion, metricasPipeline, conteoZonas] = await Promise.all([
          safeJsonFetch(DATA_SOURCES.metricasInteraccion, { total: { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 }, zonas: [], alertas: [] }),
          safeJsonFetch(DATA_SOURCES.metricasPipeline, fallbackPipeline),
          safeJsonFetch(DATA_SOURCES.conteoZonas, { zonas: [] }),
        ]);

        if (cancelado) return;

        setData({
          zonasGondola: Array.isArray(metricasInteraccion.zonas) ? metricasInteraccion.zonas : [],
          totalGlobal: metricasInteraccion.total ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
          alertas: Array.isArray(metricasInteraccion.alertas) ? metricasInteraccion.alertas : [],
          resumenPipeline: metricasPipeline,
          conteoZonas: Array.isArray(conteoZonas.zonas) ? conteoZonas.zonas : [],
          heatmapUrl: DATA_SOURCES.heatmapImage,
        });
        setStatus('ready');
      } catch (err) {
        if (cancelado) return;
        setError(err);
        setStatus('error');
      }
    }

    cargar();
    return () => { cancelado = true; };
  }, []);

  return { data, status, error };
}