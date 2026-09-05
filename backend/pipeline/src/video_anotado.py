"""
video_anotado.py
Renderizado del video con detección, tracking y anonimización — GondHawk.

Genera el video que se reproduce en el frontend: cada persona con su caja, su
ID de track, su estela de trayectoria y su rostro difuminado. Es la pieza que
hace visible todo el backend en la demo — sin esto, el pipeline es un montón
de JSON que nadie ve.

Tres decisiones que vale la pena poder defender:

1. El difuminado se aplica ANTES de dibujar las cajas y SIEMPRE, aunque el
   usuario desactive la anonimización en el resto del pipeline. Este archivo es
   el único artefacto del sistema que contiene imágenes de personas; si sale
   sin anonimizar, todo el discurso de privacidad por diseño se cae.

2. Se escribe frame a frame mientras el pipeline procesa, no en una segunda
   pasada. Volver a leer el video entero para dibujar encima duplicaría el
   tiempo de análisis, que ya es el cuello de botella.

3. Los colores de las cajas se derivan del track_id con un hash. Así el mismo
   ID conserva su color a lo largo del video y se ve que el tracking mantiene
   la identidad, que es justamente lo que hay que demostrar.
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# Paleta de alto contraste sobre imagen de tienda (BGR).
PALETA = [
    (255, 179, 71), (94, 196, 121), (231, 121, 193), (86, 180, 233),
    (255, 214, 92), (145, 132, 246), (108, 224, 208), (243, 137, 118),
]

VERDE_ZONA = (140, 220, 140)
AMARILLO_EVENTO = (60, 220, 255)


def _color_de_track(track_id: str) -> tuple[int, int, int]:
    """Color estable por ID: el mismo track conserva su color todo el video."""
    return PALETA[hash(str(track_id)) % len(PALETA)]


class VideoAnotado:
    """
    Escritor incremental del video anotado.

    Uso dentro del bucle del pipeline:

        writer = VideoAnotado(ruta, fps, ancho, alto, zonas, anonimizador)
        for cada frame:
            writer.escribir(frame, det_dicts, tracks, eventos_nuevos)
        writer.cerrar()
    """

    LARGO_ESTELA = 45  # ~4.5 s de trayectoria visible a 10 fps

    def __init__(
        self,
        ruta_salida: Path | str,
        fps: float,
        ancho: int,
        alto: int,
        zonas: list[dict[str, Any]] | None = None,
        anonimizador: Any | None = None,
        dibujar_zonas: bool = True,
        dibujar_estela: bool = True,
    ):
        self.ruta = Path(ruta_salida)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

        # Los navegadores solo reproducen H.264 dentro de MP4. mp4v (MPEG-4
        # Part 2) produce un archivo válido que Chrome descarga pero no puede
        # decodificar: se ve el reproductor vacío y la conexión se corta.
        # Se intenta avc1 (H.264) primero y se cae a mp4v solo si la
        # compilación de OpenCV no lo trae.
        self.writer = None
        for codec in ("avc1", "H264", "mp4v"):
            writer = cv2.VideoWriter(
                str(self.ruta), cv2.VideoWriter_fourcc(*codec), max(1.0, fps), (ancho, alto)
            )
            if writer.isOpened():
                self.writer = writer
                self.codec = codec
                if codec == "mp4v":
                    print(
                        "[aviso] Video anotado en mp4v: los navegadores no lo "
                        "reproducen. Conviértelo con: "
                        "ffmpeg -i video_anotado.mp4 -vcodec libx264 salida.mp4"
                    )
                break
            writer.release()

        if self.writer is None:
            raise RuntimeError(f"No se pudo abrir el escritor de video en {self.ruta}")

        self.zonas = zonas or []
        self.anonimizador = anonimizador
        self.dibujar_zonas = dibujar_zonas
        self.dibujar_estela = dibujar_estela

        self.ancho = ancho
        self.alto = alto
        self._estelas: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.LARGO_ESTELA))
        self._eventos_recientes: list[tuple[int, dict[str, Any]]] = []
        self._frames_escritos = 0
        self._escala = max(0.45, min(ancho, alto) / 1100.0)

    # ── API ──────────────────────────────────────────────────────────────

    def escribir(
        self,
        frame: np.ndarray,
        detecciones: list[dict[str, Any]],
        tracks: list[dict[str, Any]],
        eventos: list[Any] | None = None,
        timestamp_ms: float = 0.0,
    ) -> None:
        """Anota un frame y lo escribe. No modifica el frame original."""
        # 1. Anonimizar SIEMPRE. Este es el único artefacto con imágenes.
        if self.anonimizador is not None:
            lienzo = self.anonimizador.aplicar(frame, detecciones or tracks)
        else:
            lienzo = frame.copy()

        # 2. Zonas al fondo, semitransparentes, para no tapar la escena
        if self.dibujar_zonas and self.zonas:
            lienzo = self._pintar_zonas(lienzo)

        # 3. Estelas de trayectoria
        for t in tracks:
            bbox = t.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            tid = str(t.get("person_id", t.get("track_id", "?")))
            cx = int((bbox[0] + bbox[2]) / 2)
            cy = int((bbox[1] + bbox[3]) / 2)
            self._estelas[tid].append((cx, cy))

        if self.dibujar_estela:
            for tid, puntos in self._estelas.items():
                self._pintar_estela(lienzo, tid, puntos)

        # 4. Cajas e IDs encima
        for t in tracks:
            self._pintar_track(lienzo, t)

        # 5. Eventos de interacción, visibles ~1.5 s desde que ocurren
        if eventos:
            for ev in eventos:
                self._eventos_recientes.append((self._frames_escritos, ev))
        self._pintar_eventos(lienzo)

        # 6. Marca de anonimización, para que se vea en el video mismo
        self._pintar_hud(lienzo, len(tracks), timestamp_ms)

        self.writer.write(lienzo)
        self._frames_escritos += 1

    def cerrar(self) -> dict[str, Any]:
        self.writer.release()
        return {
            "ruta": str(self.ruta),
            "frames": self._frames_escritos,
            "existe": self.ruta.exists(),
            "bytes": self.ruta.stat().st_size if self.ruta.exists() else 0,
        }

    # ── Dibujo ───────────────────────────────────────────────────────────

    def _pintar_zonas(self, lienzo: np.ndarray) -> np.ndarray:
        capa = lienzo.copy()
        for zona in self.zonas:
            pts = np.array(zona.get("poligono", []), dtype=np.int32)
            if len(pts) < 3:
                continue
            es_gondola = str(zona.get("zone_id", "")).lower().startswith("gondola")
            color = VERDE_ZONA if es_gondola else (170, 170, 170)
            cv2.fillPoly(capa, [pts], color)
            cv2.polylines(lienzo, [pts], True, color, 2)
            x, y = pts[0]
            cv2.putText(
                lienzo, str(zona.get("zone_id", "")), (int(x) + 6, int(y) + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5 * self._escala + 0.25, color, 1, cv2.LINE_AA,
            )
        return cv2.addWeighted(capa, 0.16, lienzo, 0.84, 0)

    def _pintar_estela(self, lienzo: np.ndarray, tid: str, puntos: deque) -> None:
        if len(puntos) < 2:
            return
        color = _color_de_track(tid)
        lista = list(puntos)
        for i in range(1, len(lista)):
            # La estela se desvanece hacia el pasado: el grosor decrece con la
            # antigüedad, así se lee la dirección del movimiento.
            grosor = max(1, int(3 * (i / len(lista))))
            cv2.line(lienzo, lista[i - 1], lista[i], color, grosor, cv2.LINE_AA)

    def _pintar_track(self, lienzo: np.ndarray, track: dict[str, Any]) -> None:
        bbox = track.get("bbox")
        if not bbox or len(bbox) != 4:
            return
        x1, y1, x2, y2 = (int(v) for v in bbox)
        tid = str(track.get("person_id", track.get("track_id", "?")))
        color = _color_de_track(tid)

        cv2.rectangle(lienzo, (x1, y1), (x2, y2), color, 2)

        etiqueta = f"ID {tid}"
        fuente = cv2.FONT_HERSHEY_SIMPLEX
        escala = 0.45 * self._escala + 0.25
        (tw, th), _ = cv2.getTextSize(etiqueta, fuente, escala, 1)
        cv2.rectangle(lienzo, (x1, max(0, y1 - th - 9)), (x1 + tw + 10, y1), color, -1)
        cv2.putText(
            lienzo, etiqueta, (x1 + 5, max(th, y1 - 5)),
            fuente, escala, (20, 20, 20), 1, cv2.LINE_AA,
        )

    def _pintar_eventos(self, lienzo: np.ndarray) -> None:
        vigentes = []
        for frame_origen, ev in self._eventos_recientes:
            if self._frames_escritos - frame_origen > 15:
                continue
            vigentes.append((frame_origen, ev))

            tipo = getattr(ev, "event_type", None) or (
                ev.get("event_type") if isinstance(ev, dict) else None
            )
            tid = getattr(ev, "track_id", None) or (
                ev.get("track_id") if isinstance(ev, dict) else "?"
            )
            if tipo not in ("pickup", "return"):
                continue

            puntos = self._estelas.get(str(tid))
            if not puntos:
                continue
            cx, cy = puntos[-1]
            texto = "TOMA" if tipo == "pickup" else "DEVUELVE"
            cv2.circle(lienzo, (cx, cy), 26, AMARILLO_EVENTO, 2)
            cv2.putText(
                lienzo, texto, (cx - 34, cy - 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5 * self._escala + 0.25,
                AMARILLO_EVENTO, 2, cv2.LINE_AA,
            )
        self._eventos_recientes = vigentes

    def _pintar_hud(self, lienzo: np.ndarray, n_tracks: int, timestamp_ms: float) -> None:
        alto_barra = int(30 * self._escala + 14)
        capa = lienzo.copy()
        cv2.rectangle(capa, (0, 0), (self.ancho, alto_barra), (25, 25, 25), -1)
        cv2.addWeighted(capa, 0.55, lienzo, 0.45, 0, dst=lienzo)

        seg = timestamp_ms / 1000.0
        texto = f"GondHawk  |  personas: {n_tracks}  |  t={int(seg // 60):02d}:{int(seg % 60):02d}"
        cv2.putText(
            lienzo, texto, (12, int(alto_barra * 0.68)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5 * self._escala + 0.22,
            (240, 240, 240), 1, cv2.LINE_AA,
        )

        aviso = "ROSTROS ANONIMIZADOS - Ley 1581/2012"
        (tw, _), _ = cv2.getTextSize(aviso, cv2.FONT_HERSHEY_SIMPLEX, 0.4 * self._escala + 0.18, 1)
        cv2.putText(
            lienzo, aviso, (self.ancho - tw - 12, int(alto_barra * 0.68)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4 * self._escala + 0.18,
            (140, 230, 160), 1, cv2.LINE_AA,
        )
