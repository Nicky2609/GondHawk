"""
pipeline.py
Módulo 6 — Backend / Pipeline — GondHawk (Reto Góndola Inteligente)
Integrante 6 (Laura)

Responsabilidad (según la guía del reto):
    Juntar todo lo que hacen los demás en un solo flujo: el video entra,
    pasa por detección, tracking y eventos, y al final quedan las métricas
    guardadas. También se encarga de que todo esto corra localmente,
    sin depender de la nube.

Dependencias del flujo (guía, sección 3):
    2 (Samuel) → 3 (Juan) → (4 Arturo y 5 Diego) → 1 (Nicol) → 6 (Laura)

Entradas:
    - Video fuente (.mp4 / .avi / 0 para webcam)
    - mapas_de_calor/config/zonas.json  (fuente única de zonas del proyecto)
    - config/productos.json             (opcional: zone_id → SKU)

Salidas (todas en pipeline/output/):
    - detecciones.jsonl          salida del módulo 2
    - detecciones.meta.json      metadatos del video (fps, resolución)
    - tracking.jsonl             salida del módulo 3
    - dwell_time.jsonl           salida del módulo 5
    - eventos_interaccion.jsonl  salida del módulo 1 (formato canónico)
    - eventos_compliance.jsonl   salida del módulo 1 (validador módulo 8)
    - metricas_interaccion.json  embudo por góndola
    - heatmap.png                mapa de calor (módulo 4)
    - heatmap_matrix.npy         matriz suavizada (módulo 4)
    - heatmap_raw.npy            matriz cruda (módulo 4)
    - conteo_zonas.json          conteos por zona (módulo 4)
    - metricas_pipeline.json     resumen global del pipeline

Cumplimiento de privacidad (Ley 1581 de 2012):
    - Este módulo no guarda ningún frame del video.
    - No guarda recortes de personas ni datos biométricos.
    - Todos los archivos de salida contienen solo métricas numéricas
      y coordenadas anónimas, exactamente como los entrega cada módulo.
    - Los track_id son IDs opacos de ByteTrack: no permiten identificar
      a ninguna persona real.

Ejecución:
    # Pipeline completo
    python pipeline/src/pipeline.py --video data/vtest.avi

    # Con opciones avanzadas
    python pipeline/src/pipeline.py \\
        --video data/vtest.avi \\
        --zonas mapas_de_calor/config/zonas.json \\
        --productos pipeline/config/productos.json \\
        --outdir pipeline/output \\
        --t0 2026-08-20T09:00:00 \\
        --min-dwell 2.0 \\
        --max-frames 500
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Añadimos los src de cada módulo al path para importarlos directamente ──
ROOT = Path(__file__).resolve().parents[2]

# NOTA (Laura, módulo 6): mapas_de_calor/src/trajectory_reader.py (Arturo) y
# tiempo_permanencia/src/trajectory_reader.py (Diego) son dos archivos DISTINTOS
# que por coincidencia tienen el mismo nombre. Si ambas carpetas están en
# sys.path al mismo tiempo, "import trajectory_reader" es ambiguo: Python
# resuelve al primero que encuentre y lo cachea en sys.modules bajo ese nombre,
# así que el segundo "from trajectory_reader import ..." reutiliza el mismo
# módulo equivocado en vez de volver a leer el archivo correcto — de ahí el
# ImportError. Los cargamos aquí explícitamente por ruta, cada uno bajo un
# nombre único, para que no puedan pisarse sin importar el orden de sys.path.
import importlib.util


def _cargar_modulo_por_ruta(nombre_unico: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre_unico, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre_unico] = modulo
    spec.loader.exec_module(modulo)
    return modulo


_heatmap_trajectory_reader = _cargar_modulo_por_ruta(
    "_gondhawk_heatmap_trajectory_reader",
    ROOT / "mapas_de_calor" / "src" / "trajectory_reader.py",
)
_dwell_trajectory_reader = _cargar_modulo_por_ruta(
    "_gondhawk_dwell_trajectory_reader",
    ROOT / "tiempo_permanencia" / "src" / "trajectory_reader.py",
)

sys.path.insert(0, str(ROOT / "deteccion_personas" / "src"))
sys.path.insert(0, str(ROOT / "tracking" / "src"))
sys.path.insert(0, str(ROOT / "mapas_de_calor" / "src"))
sys.path.insert(0, str(ROOT / "tiempo_permanencia" / "src"))
sys.path.insert(0, str(ROOT / "deteccion_eventos" / "src"))

import cv2

# Módulo 2 — Samuel
from person_detector import PersonDetector

# Módulo 3 — Juan
from tracker import PersonTracker

# Módulo 4 — Arturo
# Justo antes de importar heatmap_generator, apuntamos el nombre genérico
# "trajectory_reader" a SU versión, para que su "from trajectory_reader
# import read_trajectories, load_zonas" (línea 34 de heatmap_generator.py,
# que no tocamos) resuelva al archivo correcto.
sys.modules["trajectory_reader"] = _heatmap_trajectory_reader
from heatmap_generator import (
    build_heatmap_and_counts,
    draw_zonas_on_image,
    render_heatmap_image,
    save_with_colorbar,
    smooth_heatmap,
)

# Módulo 5 — Diego
# Ahora re-apuntamos "trajectory_reader" a SU versión antes de importar
# dwell_time.py, que hace "from trajectory_reader import TrajectoryReader".
sys.modules["trajectory_reader"] = _dwell_trajectory_reader
from dwell_time import DwellTimeAnalyzer, load_zones_from_json

# Liberamos la clave genérica para que nada más la reutilice por accidente.
del sys.modules["trajectory_reader"]

# Módulo 1 — Nicol
from metrics import DwellIndex, calcular_metricas
from reach_detector import ReachConfig
from state_machine import InteractionConfig, InteractionStateMachine
from zonas import cargar_layout

# La proyección al esquema del módulo 8 y la carga del mapa de productos se
# IMPORTAN del módulo 1; antes estaban copiadas aquí. Con la copia, cualquier
# cambio de esquema en run_events.py dejaba al pipeline emitiendo el formato
# viejo sin que nadie se enterara hasta la validación final. Un solo lugar
# define el contrato de cumplimiento.
from run_events import (
    cargar_productos as _cargar_productos,
    proyectar_compliance as _proyectar_compliance,
)

import numpy as np


# ── Constantes ──────────────────────────────────────────────────────────────

DEFAULT_ZONAS = ROOT / "mapas_de_calor" / "config" / "zonas.json"
DEFAULT_OUTDIR = ROOT / "pipeline" / "output"
DEFAULT_T0 = "2026-08-20T09:00:00"


# ── Helpers ─────────────────────────────────────────────────────────────────

# ── Pipeline principal ───────────────────────────────────────────────────────

class GondolaPipeline:
    """
    Orquesta todos los módulos del proyecto en un único flujo local.

    Procesa el video frame a frame sin cargar nada completo en memoria
    (streaming), lo que cumple el requisito de viabilidad edge del reto
    y evita depender de la nube.

    Etapas por frame:
        1. Detección de personas (Módulo 2 — Samuel)
        2. Tracking y asignación de IDs (Módulo 3 — Juan)
        3. Actualización del mapa de calor (Módulo 4 — Arturo)
        4. Tiempo de permanencia (Módulo 5 — Diego)
        5. Detección de eventos de interacción (Módulo 1 — Nicol)
        6. Escritura en streaming de JSONL intermedios

    Al final del video:
        - Se guardan los archivos JSONL finales
        - Se genera el heatmap con matplotlib
        - Se calculan las métricas del embudo
        - Se escribe el resumen global del pipeline
    """

    def __init__(
        self,
        video_source: str | int,
        zonas_path: Path,
        outdir: Path,
        productos_path: Path | None = None,
        t0_str: str = DEFAULT_T0,
        min_dwell_s: float = 2.0,
        gracia_frames: int = 5,
        modo_alcance: str = "geometrico",
        max_frames: int | None = None,
        model_path: str = "yolov8n.pt",
        conf_threshold: float = 0.4,
        colormap: str = "turbo",
    ):
        self.video_source = video_source
        self.zonas_path = zonas_path
        self.outdir = outdir
        self.productos = _cargar_productos(productos_path)
        self.t0 = datetime.fromisoformat(t0_str)
        self.min_dwell_s = min_dwell_s
        self.max_frames = max_frames
        self.colormap = colormap

        self.outdir.mkdir(parents=True, exist_ok=True)

        # ── Módulo 2: Detector de personas ──────────────────────────────────
        print("[pipeline] Iniciando módulo 2 — Detección de personas (Samuel)...")
        self.detector = PersonDetector(
            model_path=model_path,
            conf_threshold=conf_threshold,
        )

        # ── Módulo 3: Tracker ────────────────────────────────────────────────
        print("[pipeline] Iniciando módulo 3 — Tracking (Juan)...")
        self.tracker = PersonTracker(
            track_buffer=gracia_frames * 6,
        )

        # ── Módulo 5: Tiempo de permanencia ─────────────────────────────────
        print("[pipeline] Iniciando módulo 5 — Tiempo de permanencia (Diego)...")
        zones_dwell = load_zones_from_json(zonas_path)
        self.dwell_analyzer = DwellTimeAnalyzer(
            zones=zones_dwell,
            min_dwell_ms=min_dwell_s * 1000.0,
            grace_frames=gracia_frames,
        )

        # ── Módulo 1: Máquina de estados ────────────────────────────────────
        print("[pipeline] Iniciando módulo 1 — Detección de eventos (Nicol)...")
        layout = cargar_layout(zonas_path)
        self.maquina = InteractionStateMachine(
            layout=layout,
            config=InteractionConfig(
                min_dwell_s=min_dwell_s,
                gracia_frames=gracia_frames,
            ),
            reach_config=ReachConfig(),
            modo_alcance=modo_alcance,
        )

        # ── Módulo 4: Datos para heatmap (acumulador en memoria) ─────────────
        print("[pipeline] Iniciando módulo 4 — Mapa de calor (Arturo)...")
        self.zonas_data_heatmap: dict | None = None  # se inicializa al leer el video

        # Escritores JSONL intermedios
        self._fh_detecciones = open(outdir / "detecciones.jsonl", "w", encoding="utf-8")
        self._fh_tracking = open(outdir / "tracking.jsonl", "w", encoding="utf-8")
        self._fh_dwell = open(outdir / "dwell_time.jsonl", "w", encoding="utf-8")

        # Métricas globales
        self._frames_procesados = 0
        self._total_detecciones = 0
        self._ultimo_ts = 0.0
        self._frame_ref: np.ndarray | None = None

    # ── Bucle principal ─────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """
        Ejecuta el pipeline completo sobre el video.

        Returns:
            Resumen global con rutas de salida y métricas principales.
        """
        source = (
            int(self.video_source)
            if str(self.video_source).isdigit()
            else self.video_source
        )
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"[pipeline] No se pudo abrir el video: {source}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(
            f"[pipeline] Video: {source} | "
            f"{width}×{height} | {fps:.2f} fps | "
            f"{'∞' if total_frames <= 0 else total_frames} frames"
        )

        # Guardar metadatos del video (los necesitan otros módulos)
        meta = {
            "video_source": str(source),
            "fps_origen": fps,
            "frame_width": width,
            "frame_height": height,
            "frame_count": total_frames,
        }

        # Inicializar acumulador del heatmap ahora que conocemos la resolución
        self._heatmap_acum = np.zeros((height, width), dtype=np.float64)

        # Inicializar estructura de zonas para el heatmap
        with open(self.zonas_path, "r", encoding="utf-8") as f:
            zonas_raw = json.load(f)
        # Asegurar que frame_width/height están en el JSON (módulo 4 los necesita)
        zonas_raw.setdefault("frame_width", width)
        zonas_raw.setdefault("frame_height", height)
        self.zonas_data_heatmap = zonas_raw
        # Nota: no se construyen aquí las máscaras de zona. build_heatmap_and_counts()
        # las arma internamente (heatmap_generator.py línea 81), así que hacerlo
        # también aquí era trabajo repetido sobre un resultado que se descartaba.

        t_inicio = time.time()
        frame_id = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if self.max_frames is not None and frame_id >= self.max_frames:
                break

            timestamp_ms = (frame_id / fps) * 1000.0

            # Guardar primer frame para el heatmap de fondo
            if frame_id == 0:
                self._frame_ref = frame.copy()

            # ── Etapa 2: Detección ───────────────────────────────────────────
            detecciones = self.detector.detect_frame(frame)
            det_dicts = [d.to_dict() for d in detecciones]

            self._fh_detecciones.write(
                json.dumps(
                    {
                        "frame_id": frame_id,
                        "timestamp_ms": round(timestamp_ms, 2),
                        "detections": det_dicts,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            # ── Etapa 3: Tracking ────────────────────────────────────────────
            tracks = self.tracker.update(det_dicts, frame_shape=frame.shape)

            self._fh_tracking.write(
                json.dumps(
                    {
                        "frame_id": frame_id,
                        "timestamp_ms": round(timestamp_ms, 2),
                        "tracks": tracks,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            # ── Etapa 4: Acumulación del heatmap ────────────────────────────
            for t in tracks:
                bbox = t.get("bbox", [])
                if len(bbox) == 4:
                    x1, y1, x2, y2 = bbox
                    cx = int(round((x1 + x2) / 2))
                    cy = int(round((y1 + y2) / 2))
                    if 0 <= cx < width and 0 <= cy < height:
                        self._heatmap_acum[cy, cx] += 1

            # ── Etapa 5: Tiempo de permanencia ───────────────────────────────
            prev_events_count = len(self.dwell_analyzer.get_events())
            self.dwell_analyzer.process_frame(timestamp_ms, tracks)
            new_events = self.dwell_analyzer.get_events()[prev_events_count:]
            for ev in new_events:
                self._fh_dwell.write(json.dumps(ev, ensure_ascii=False) + "\n")

            # ── Etapa 1: Detección de eventos ────────────────────────────────
            self.maquina.process_frame(timestamp_ms, tracks)

            self._frames_procesados += 1
            self._total_detecciones += len(det_dicts)
            self._ultimo_ts = timestamp_ms
            frame_id += 1

            if frame_id % 100 == 0:
                elapsed = time.time() - t_inicio
                print(
                    f"[pipeline] Frame {frame_id} | "
                    f"{elapsed:.1f}s | "
                    f"{frame_id / elapsed:.1f} fps efectivos"
                )

        cap.release()

        # ── Finalizar módulos ────────────────────────────────────────────────
        self.dwell_analyzer.finalize(self._ultimo_ts)
        # Escribir eventos de dwell que quedaron al cerrar el video
        # (los que estaban activos al final no se escribieron en el bucle)
        all_dwell = self.dwell_analyzer.get_events()
        self._fh_dwell.close()
        # Reescribir completo para incluir los finalizados
        with open(self.outdir / "dwell_time.jsonl", "w", encoding="utf-8") as fh:
            for ev in all_dwell:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

        self.maquina.finalize(self._ultimo_ts)

        self._fh_detecciones.close()
        self._fh_tracking.close()

        # Metadatos del video (con frames reales procesados)
        meta["frames_procesados"] = self._frames_procesados
        meta["total_detecciones"] = self._total_detecciones
        meta["tiempo_procesamiento_seg"] = round(time.time() - t_inicio, 2)
        (self.outdir / "detecciones.meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # ── Guardar salidas finales ──────────────────────────────────────────
        resumen = self._guardar_salidas(meta)
        return resumen

    # ── Guardado de salidas ─────────────────────────────────────────────────

    def _guardar_salidas(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Genera y guarda todas las salidas finales del pipeline."""

        # ── Módulo 4: Heatmap ────────────────────────────────────────────────
        print("[pipeline] Generando heatmap (módulo 4 — Arturo)...")
        heatmap_smooth = smooth_heatmap(self._heatmap_acum)

        # Calcular conteos por zona usando la misma lógica del módulo 4
        _, conteos_zonas = build_heatmap_and_counts(
            self.outdir / "tracking.jsonl",
            self.zonas_data_heatmap,
        )

        img_heatmap = render_heatmap_image(
            heatmap_smooth,
            self._frame_ref,
            colormap_name=self.colormap,
            zonas=self.zonas_data_heatmap.get("zonas", []),
        )
        img_heatmap = draw_zonas_on_image(
            img_heatmap,
            self.zonas_data_heatmap.get("zonas", []),
            conteos_zonas["zonas"],
        )
        save_with_colorbar(img_heatmap, str(self.outdir / "heatmap.png"), self.colormap)
        np.save(str(self.outdir / "heatmap_matrix.npy"), heatmap_smooth)
        np.save(str(self.outdir / "heatmap_raw.npy"), self._heatmap_acum)

        with open(self.outdir / "conteo_zonas.json", "w", encoding="utf-8") as fh:
            json.dump(conteos_zonas, fh, indent=2, ensure_ascii=False)

        # ── Módulo 1: Eventos e interacción ──────────────────────────────────
        print("[pipeline] Guardando eventos de interacción (módulo 1 — Nicol)...")
        eventos = self.maquina.eventos
        dwell_index = DwellIndex(self.dwell_analyzer.get_events())

        # Formato canónico (interno del proyecto)
        with open(self.outdir / "eventos_interaccion.jsonl", "w", encoding="utf-8") as fh:
            for evento in eventos:
                registro = evento.to_dict()
                cruce = dwell_index.buscar(
                    evento.track_id, evento.zone_id, evento.timestamp_ms
                )
                if cruce is not None:
                    registro["dwell_modulo5_s"] = cruce.get("dwell_time_s")
                    registro["detuvo_modulo5"] = cruce.get("detuvo")
                fh.write(json.dumps(registro, ensure_ascii=False) + "\n")

        # Proyección para el validador del módulo 8 (Paula)
        n_compliance = 0
        with open(self.outdir / "eventos_compliance.jsonl", "w", encoding="utf-8") as fh:
            for evento in eventos:
                registro = _proyectar_compliance(evento, self.t0, self.productos)
                if registro is not None:
                    fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
                    n_compliance += 1

        # Métricas del embudo por góndola
        layout = cargar_layout(self.zonas_path)
        metricas = calcular_metricas(eventos, [z.zone_id for z in layout.gondolas])
        metricas["meta"] = {
            "video_ref": str(self.video_source),
            "frames_procesados": self._frames_procesados,
            "t0": self.t0.isoformat(),
            "min_dwell_s": self.min_dwell_s,
        }
        (self.outdir / "metricas_interaccion.json").write_text(
            json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # ── Resumen global del pipeline ──────────────────────────────────────
        print("[pipeline] Guardando resumen global...")
        total = metricas["total"]
        resumen = {
            "pipeline": "GondHawk — Integrante 6 (Laura)",
            "video_fuente": str(self.video_source),
            "frames_procesados": self._frames_procesados,
            "tiempo_procesamiento_seg": meta.get("tiempo_procesamiento_seg", 0),
            "total_detecciones": self._total_detecciones,
            "eventos_generados": len(eventos),
            "eventos_compliance": n_compliance,
            "embudo_global": {
                "visitas": total["visitas"],
                "se_detiene": total["se_detiene"],
                "toma_producto": total["toma_producto"],
                "devuelve": total["devuelve"],
                "tasa_interaccion": total["tasa_interaccion"],
                "tasa_rechazo": total["tasa_rechazo"],
            },
            "alertas": metricas.get("alertas", []),
            "salidas": {
                "detecciones": str(self.outdir / "detecciones.jsonl"),
                "tracking": str(self.outdir / "tracking.jsonl"),
                "dwell_time": str(self.outdir / "dwell_time.jsonl"),
                "eventos_interaccion": str(self.outdir / "eventos_interaccion.jsonl"),
                "eventos_compliance": str(self.outdir / "eventos_compliance.jsonl"),
                "metricas_interaccion": str(self.outdir / "metricas_interaccion.json"),
                "heatmap": str(self.outdir / "heatmap.png"),
                "conteo_zonas": str(self.outdir / "conteo_zonas.json"),
            },
        }
        (self.outdir / "metricas_pipeline.json").write_text(
            json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return resumen


# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "GondHawk — Pipeline completo (Módulo 6, Laura).\n"
            "Junta todos los módulos en un solo flujo local sin depender de la nube."
        )
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Ruta al video (.mp4, .avi) o '0' para webcam",
    )
    parser.add_argument(
        "--zonas",
        default=str(DEFAULT_ZONAS),
        help=f"Archivo de zonas (default: {DEFAULT_ZONAS})",
    )
    parser.add_argument(
        "--productos",
        default=None,
        help="JSON con mapa zone_id → SKU (opcional)",
    )
    parser.add_argument(
        "--outdir",
        default=str(DEFAULT_OUTDIR),
        help=f"Carpeta de salida (default: {DEFAULT_OUTDIR})",
    )
    parser.add_argument(
        "--t0",
        default=DEFAULT_T0,
        help="Hora real de inicio del video en ISO 8601 (para timestamps absolutos)",
    )
    parser.add_argument(
        "--min-dwell",
        type=float,
        default=2.0,
        help="Segundos mínimos para considerar que alguien se detuvo (default: 2.0)",
    )
    parser.add_argument(
        "--gracia-frames",
        type=int,
        default=5,
        help="Frames sin ver un track antes de cerrar su episodio (default: 5)",
    )
    parser.add_argument(
        "--modo-alcance",
        choices=["geometrico", "pose"],
        default="geometrico",
        help="Señal para detectar alcance al estante (default: geometrico)",
    )
    parser.add_argument(
        "--model",
        default="yolov8n.pt",
        help="Pesos de YOLO para la detección de personas (default: yolov8n.pt)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.4,
        help="Umbral de confianza para YOLO (default: 0.4)",
    )
    parser.add_argument(
        "--colormap",
        default="turbo",
        choices=["jet", "turbo", "inferno", "hot", "magma"],
        help="Colormap del heatmap (default: turbo)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Límite de frames a procesar (útil para pruebas rápidas)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pipeline = GondolaPipeline(
        video_source=args.video,
        zonas_path=Path(args.zonas),
        outdir=Path(args.outdir),
        productos_path=Path(args.productos) if args.productos else None,
        t0_str=args.t0,
        min_dwell_s=args.min_dwell,
        gracia_frames=args.gracia_frames,
        modo_alcance=args.modo_alcance,
        max_frames=args.max_frames,
        model_path=args.model,
        conf_threshold=args.conf,
        colormap=args.colormap,
    )

    print("\n[pipeline] ▶  Iniciando pipeline completo — GondHawk (Laura)\n")
    resumen = pipeline.run()

    # ── Consola final ────────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("[pipeline] ✅  Pipeline completado")
    print(f"[pipeline]    Frames procesados : {resumen['frames_procesados']}")
    print(f"[pipeline]    Detecciones totales: {resumen['total_detecciones']}")
    print(f"[pipeline]    Eventos generados  : {resumen['eventos_generados']}")
    print(f"[pipeline]    Eventos compliance : {resumen['eventos_compliance']}")

    embudo = resumen["embudo_global"]
    print(
        f"[pipeline]    Embudo global     : "
        f"{embudo['visitas']} visitas → "
        f"{embudo['se_detiene']} paradas → "
        f"{embudo['toma_producto']} tomas → "
        f"{embudo['devuelve']} devoluciones"
    )
    print(
        f"[pipeline]    Tasa interacción  : {embudo['tasa_interaccion']:.1%} | "
        f"Tasa rechazo: {embudo['tasa_rechazo']:.1%}"
    )

    for alerta in resumen.get("alertas", []):
        print(f"[pipeline]  ⚠  {alerta['zone_id']} — {alerta['tipo']}: {alerta['mensaje']}")

    print(f"\n[pipeline]    Salidas en: {Path(args.outdir).resolve()}")
    print("─" * 60 + "\n")


if __name__ == "__main__":
    main()
