import { useEffect, useRef, useState } from 'react';

/**
 * Reproductor del video anotado: detección, tracking y rostros difuminados.
 *
 * Es la pieza que hace visible el backend. Se muestra junto a la imagen de
 * zonas propuestas porque las dos responden preguntas distintas: el video
 * muestra si el sistema sigue bien a las personas, y la imagen de zonas
 * muestra si las está midiendo en el lugar correcto. Un análisis puede fallar
 * en cualquiera de las dos y las métricas se ven igual de plausibles.
 */
export function VideoPanel({ videoUrl, zonasUrl, embebido = false, onTimeUpdate }) {
  const [vista, setVista] = useState('video');
  const [errorUrl, setErrorUrl] = useState(null);
  const videoRef = useRef(null);
  const rafRef = useRef(null);

  const errorVideo = Boolean(videoUrl && errorUrl === videoUrl);
  const vistaActiva = vista === 'zonas' && zonasUrl ? 'zonas' : 'video';

  const detenerSync = () => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  const iniciarSync = () => {
    detenerSync();
    const tick = () => {
      const el = videoRef.current;
      if (!el || el.paused || el.ended) {
        rafRef.current = null;
        return;
      }
      onTimeUpdate?.(el.currentTime);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  };

  useEffect(() => detenerSync, []);

  if (!videoUrl && !zonasUrl) {
    return (
      <div className={`p-6 text-base text-[var(--ink-muted)] ${embebido ? '' : 'rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]'}`}>
        El video con detección y seguimiento aparecerá después del análisis.
      </div>
    );
  }

  return (
    <div className={embebido ? '' : 'overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]'}>
      <div className="flex items-center justify-between gap-3 border-b border-[var(--panel-border)] px-4 py-3">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setVista('video')}
            className={`rounded-lg px-3 py-1.5 text-sm ${vistaActiva === 'video' ? 'bg-[var(--accent)] text-white' : 'text-[var(--ink-muted)]'}`}
          >
            Detección y seguimiento
          </button>
          {zonasUrl && (
            <button
              type="button"
              onClick={() => setVista('zonas')}
              className={`rounded-lg px-3 py-1.5 text-sm ${vistaActiva === 'zonas' ? 'bg-[var(--accent)] text-white' : 'text-[var(--ink-muted)]'}`}
            >
              Zonas detectadas
            </button>
          )}
        </div>
      </div>

      {vistaActiva === 'video' ? (
        videoUrl && !errorVideo ? (
          <video
            key={videoUrl}
            ref={videoRef}
            src={videoUrl}
            controls
            playsInline
            className="w-full bg-black"
            preload="metadata"
            onLoadedMetadata={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
            onPlay={iniciarSync}
            onPause={detenerSync}
            onEnded={(e) => {
              detenerSync();
              onTimeUpdate?.(e.currentTarget.currentTime);
            }}
            onSeeked={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
            onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
            onError={() => {
              detenerSync();
              setErrorUrl(videoUrl);
            }}
          >
            Tu navegador no puede reproducir este video.
          </video>
        ) : (
          <div className="p-6 text-sm text-[var(--ink-muted)]">
            {videoUrl
              ? 'No se pudo reproducir el video de este análisis. Verifica que el archivo esté codificado en H.264 o vuelve a analizar el video.'
              : 'Este análisis no tiene video guardado.'}
          </div>
        )
      ) : null}

      {vistaActiva === 'zonas' && zonasUrl ? (
        <div>
          <img src={zonasUrl} alt="Zonas detectadas sobre el video" className="w-full" />
          <p className="px-4 py-3 text-sm text-[var(--ink-muted)]">
            Zonas propuestas automáticamente. Verifica que los recuadros caigan sobre
            los estantes: si no, las métricas de interacción no son válidas.
          </p>
        </div>
      ) : null}
    </div>
  );
}
