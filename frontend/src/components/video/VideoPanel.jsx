import { useState } from 'react';

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
  const [errorVideo, setErrorVideo] = useState(false);

  if (!videoUrl && !zonasUrl) {
    return (
      <div className={`p-6 text-sm text-[var(--ink-muted)] ${embebido ? '' : 'rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]'}`}>
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
            className={`rounded-lg px-3 py-1.5 text-xs ${vista === 'video' ? 'bg-[var(--accent)] text-white' : 'text-[var(--ink-muted)]'}`}
          >
            Detección y seguimiento
          </button>
          {zonasUrl && (
            <button
              type="button"
              onClick={() => setVista('zonas')}
              className={`rounded-lg px-3 py-1.5 text-xs ${vista === 'zonas' ? 'bg-[var(--accent)] text-white' : 'text-[var(--ink-muted)]'}`}
            >
              Zonas detectadas
            </button>
          )}
        </div>
      </div>

      {vista === 'video' ? (
        videoUrl && !errorVideo ? (
          <video
            src={videoUrl}
            controls
            className="w-full bg-black"
            preload="metadata"
            onError={() => setErrorVideo(true)}
            onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
            onSeeked={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
          >
            Tu navegador no puede reproducir este video.
          </video>
        ) : (
          // Sin este caso el panel quedaba en blanco: la URL existía, así que
          // no entraba en el estado vacío, pero el video no cargaba y no había
          // ningún mensaje que lo explicara.
          <div className="p-6 text-sm text-[var(--ink-muted)]">
            {videoUrl
              ? 'No se pudo cargar el video de este análisis. Si es un análisis antiguo, puede que no se haya archivado; vuelve a subir el video.'
              : 'Este análisis no tiene video guardado.'}
          </div>
        )
      ) : null}

      {vista === 'zonas' && zonasUrl ? (
        <div>
          <img src={zonasUrl} alt="Zonas detectadas sobre el video" className="w-full" />
          <p className="px-4 py-3 text-xs text-[var(--ink-muted)]">
            Zonas propuestas automáticamente. Verifica que los recuadros caigan sobre
            los estantes: si no, las métricas de interacción no son válidas.
          </p>
        </div>
      ) : null}
    </div>
  );
}
