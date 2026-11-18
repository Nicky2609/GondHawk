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
import shutil
import subprocess
import tempfile
from typing import Any, Sequence

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


def _buscar_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _iou_bbox(a: Sequence[float] | list[float], b: Sequence[float] | list[float]) -> float:
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    iw = ix2 - ix1
    ih = iy2 - iy1
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    area_a = max(0.0, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(0.0, (b[2] - b[0]) * (b[3] - b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _combinar_sin_duplicados(
    detecciones: list[dict[str, Any]] | None,
    tracks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Une tracks y detecciones no emparejadas evitando difuminar dos veces."""
    trks = tracks or []
    dets = detecciones or []
    if not trks:
        return dets
    if not dets:
        return trks

    combinadas = list(trks)
    bboxes_tracks = [t["bbox"] for t in trks if t.get("bbox") and len(t["bbox"]) == 4]
    for det in dets:
        bbox = det.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        if not any(_iou_bbox(bbox, tb) > 0.5 for tb in bboxes_tracks):
            combinadas.append(det)
    return combinadas


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

        self.zonas = zonas or []
        self.anonimizador = anonimizador
        self.dibujar_zonas = dibujar_zonas
        self.dibujar_estela = dibujar_estela

        self.ancho = ancho
        self.alto = alto
        self._fps = max(1.0, fps)
        self._estelas: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.LARGO_ESTELA))
        self._eventos_recientes: list[tuple[int, dict[str, Any]]] = []
        self._frames_escritos = 0
        self._escala = max(0.45, min(ancho, alto) / 1100.0)

        # Precalcula el HUD y la capa estatica de zonas una sola vez.
        self._alto_barra = int(30 * self._escala + 14)
        self._hud_fondo = np.full((self._alto_barra, ancho, 3), (25, 25, 25), dtype=np.uint8)
        self._hud_y = int(self._alto_barra * 0.68)
        self._hud_font_stats = 0.5 * self._escala + 0.22
        self._hud_font_aviso = 0.4 * self._escala + 0.18
        self._hud_aviso = "ROSTROS ANONIMIZADOS - Ley 1581/2012"
        (tw, _), _ = cv2.getTextSize(self._hud_aviso, cv2.FONT_HERSHEY_SIMPLEX, self._hud_font_aviso, 1)
        self._hud_aviso_x = ancho - tw - 12

        self._zonas_roi: tuple[int, int, int, int] | None = None
        self._zonas_fill_roi: np.ndarray | None = None
        self._zonas_fill_mask3: np.ndarray | None = None
        self._zonas_draw_roi: np.ndarray | None = None
        self._zonas_draw_mask3: np.ndarray | None = None
        if self.dibujar_zonas and self.zonas:
            self._precalcular_zonas()

        # Escritura directa en H.264 mediante pipe a ffmpeg para evitar doble codificacion.
        self.codec = "mp4v"
        self.writer: cv2.VideoWriter | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._ffmpeg_stderr = None
        ffmpeg_exe = _buscar_ffmpeg()
        if ffmpeg_exe:
            try:
                cmd = [
                    ffmpeg_exe, "-y", "-loglevel", "error",
                    "-f", "rawvideo", "-vcodec", "rawvideo",
                    "-pix_fmt", "bgr24", "-s", f"{ancho}x{alto}",
                    "-r", f"{self._fps:.4f}", "-i", "-",
                    "-an", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-vcodec", "libx264", "-profile:v", "main", "-level", "4.0",
                    "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(self.ruta),
                ]
                self._ffmpeg_stderr = tempfile.TemporaryFile()
                self._ffmpeg_proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stderr=self._ffmpeg_stderr
                )
                self.codec = "h264"
            except Exception:
                if self._ffmpeg_stderr is not None:
                    self._ffmpeg_stderr.close()
                    self._ffmpeg_stderr = None
                self._ffmpeg_proc = None

        if self._ffmpeg_proc is None:
            self.writer = cv2.VideoWriter(
                str(self.ruta),
                cv2.VideoWriter_fourcc(*"mp4v"),
                self._fps,
                (ancho, alto),
            )
            if not self.writer.isOpened():
                raise RuntimeError(f"No se pudo abrir el escritor de video en {self.ruta}")

    def _precalcular_zonas(self) -> None:
        fill_full = np.zeros((self.alto, self.ancho, 3), dtype=np.uint8)
        fill_mask = np.zeros((self.alto, self.ancho), dtype=np.uint8)
        draw_full = np.zeros((self.alto, self.ancho, 3), dtype=np.uint8)
        draw_mask = np.zeros((self.alto, self.ancho), dtype=np.uint8)

        dibujo = False
        for zona in self.zonas:
            pts = np.array(zona.get("poligono", []), dtype=np.int32)
            if len(pts) < 3:
                continue
            dibujo = True
            es_gondola = str(zona.get("zone_id", "")).lower().startswith("gondola")
            color = VERDE_ZONA if es_gondola else (170, 170, 170)
            cv2.fillPoly(fill_full, [pts], color)
            cv2.fillPoly(fill_mask, [pts], 1)
            cv2.polylines(draw_full, [pts], True, color, 2)
            cv2.polylines(draw_mask, [pts], True, 1, 2)
            x, y = pts[0]
            pos = (int(x) + 6, int(y) + 22)
            escala_txt = 0.5 * self._escala + 0.25
            cv2.putText(draw_full, str(zona.get("zone_id", "")), pos, cv2.FONT_HERSHEY_SIMPLEX, escala_txt, color, 1, cv2.LINE_AA)
            cv2.putText(draw_mask, str(zona.get("zone_id", "")), pos, cv2.FONT_HERSHEY_SIMPLEX, escala_txt, 1, 1, cv2.LINE_AA)

        if not dibujo:
            return

        activo = (fill_mask > 0) | (draw_mask > 0)
        ys, xs = np.where(activo)
        if not len(ys):
            return
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        self._zonas_roi = (y0, y1, x0, x1)
        self._zonas_fill_roi = fill_full[y0:y1, x0:x1].copy()
        self._zonas_fill_mask3 = np.repeat(fill_mask[y0:y1, x0:x1, None] > 0, 3, axis=2)
        self._zonas_draw_roi = draw_full[y0:y1, x0:x1].copy()
        self._zonas_draw_mask3 = np.repeat(draw_mask[y0:y1, x0:x1, None] > 0, 3, axis=2)

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
            objetivos = _combinar_sin_duplicados(detecciones, tracks)
            lienzo = self.anonimizador.aplicar(frame, objetivos)
            if lienzo is frame:
                lienzo = frame.copy()
        else:
            lienzo = frame.copy()

        # 2. Zonas al fondo, semitransparentes, para no tapar la escena
        if self._zonas_roi is not None:
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

        if self._ffmpeg_proc is not None and self._ffmpeg_proc.stdin is not None:
            self._ffmpeg_proc.stdin.write(np.ascontiguousarray(lienzo).tobytes())
        elif self.writer is not None:
            self.writer.write(lienzo)
        self._frames_escritos += 1

    def cerrar(self) -> dict[str, Any]:
        if self._ffmpeg_proc is not None:
            try:
                if self._ffmpeg_proc.stdin is not None:
                    try:
                        self._ffmpeg_proc.stdin.close()
                    except OSError:
                        pass
                if self._frames_escritos == 0:
                    self._ffmpeg_proc.terminate()
                    self._ffmpeg_proc.wait(timeout=10)
                    self.ruta.unlink(missing_ok=True)
                else:
                    self._ffmpeg_proc.wait(timeout=300)
                    if self._ffmpeg_proc.returncode == 0 and self.ruta.exists() and self.ruta.stat().st_size > 1024:
                        print("[video] Escrito directamente en H.264 para reproducción en navegador.")
                    else:
                        msg = ""
                        if self._ffmpeg_stderr is not None:
                            self._ffmpeg_stderr.seek(0)
                            msg = self._ffmpeg_stderr.read().decode("utf-8", errors="ignore").strip()
                        print(f"[aviso] ffmpeg terminó con error ({self._ffmpeg_proc.returncode}): {msg}")
            finally:
                if self._ffmpeg_stderr is not None:
                    self._ffmpeg_stderr.close()
                    self._ffmpeg_stderr = None
                self._ffmpeg_proc = None
        elif self.writer is not None:
            self.writer.release()
            self.writer = None
            if self._frames_escritos > 0:
                self._convertir_a_h264()

        return {
            "ruta": str(self.ruta),
            "frames": self._frames_escritos,
            "existe": self.ruta.exists(),
            "bytes": self.ruta.stat().st_size if self.ruta.exists() else 0,
        }

    def _convertir_a_h264(self) -> None:
        """
        Reescribe el video en H.264 con el ffmpeg de imageio-ffmpeg.

        Los navegadores solo reproducen H.264 dentro de MP4; mp4v (MPEG-4
        Part 2) produce un archivo que Chrome descarga pero no decodifica.

        Falla en silencio a propósito: no poder convertir deja el video sin
        reproducirse en el tablero, pero no debe tumbar un análisis que ya
        terminó bien.
        """
        if not self.ruta.exists() or self.ruta.stat().st_size < 1024:
            print("[aviso] El video anotado quedó vacío; no se convierte.")
            return

        try:
            import subprocess

            import imageio_ffmpeg
        except ImportError:
            print(
                "[aviso] Instala imageio-ffmpeg (pip install imageio-ffmpeg) "
                "para que el video se reproduzca en el tablero."
            )
            return

        temporal = self.ruta.with_name(self.ruta.stem + "_h264.mp4")
        try:
            resultado = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                    "-i", str(self.ruta),
                    "-vcodec", "libx264", "-profile:v", "main", "-level", "4.0",
                    "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(temporal),
                ],
                capture_output=True,
                timeout=600,  # un ffmpeg colgado no debe bloquear la API
            )
            if (
                resultado.returncode == 0
                and temporal.exists()
                and temporal.stat().st_size > 1024
            ):
                temporal.replace(self.ruta)
                self.codec = "h264"
                print("[video] Convertido a H.264 para reproducción en navegador.")
            else:
                print("[aviso] ffmpeg no pudo convertir el video; se deja el original.")
                temporal.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[aviso] No se pudo convertir el video a H.264: {exc}")
            temporal.unlink(missing_ok=True)

    # ── Dibujo ───────────────────────────────────────────────────────────

    def _pintar_zonas(self, lienzo: np.ndarray) -> np.ndarray:
        if self._zonas_roi is None:
            return lienzo
        y0, y1, x0, x1 = self._zonas_roi
        roi = lienzo[y0:y1, x0:x1]
        blended = cv2.addWeighted(roi, 0.84, self._zonas_fill_roi, 0.16, 0)
        np.copyto(roi, blended, where=self._zonas_fill_mask3)
        np.copyto(roi, self._zonas_draw_roi, where=self._zonas_draw_mask3)
        return lienzo

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
        roi = lienzo[:self._alto_barra]
        cv2.addWeighted(roi, 0.45, self._hud_fondo, 0.55, 0, dst=roi)

        seg = timestamp_ms / 1000.0
        texto = f"GondHawk  |  personas: {n_tracks}  |  t={int(seg // 60):02d}:{int(seg % 60):02d}"
        cv2.putText(
            lienzo, texto, (12, self._hud_y),
            cv2.FONT_HERSHEY_SIMPLEX, self._hud_font_stats,
            (240, 240, 240), 1, cv2.LINE_AA,
        )

        cv2.putText(
            lienzo, self._hud_aviso, (self._hud_aviso_x, self._hud_y),
            cv2.FONT_HERSHEY_SIMPLEX, self._hud_font_aviso,
            (140, 230, 160), 1, cv2.LINE_AA,
        )