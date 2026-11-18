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
from collections import defaultdict
import json
import queue
import sys
import threading
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
from person_detector import PERFILES, PersonDetector

# Módulo 3 — Juan
from tracker import PersonTracker

# Módulo 4 — Arturo
# Justo antes de importar heatmap_generator, apuntamos el nombre genérico
# "trajectory_reader" a SU versión, para que su "from trajectory_reader
# import read_trajectories, load_zonas" (línea 34 de heatmap_generator.py,
# que no tocamos) resuelva al archivo correcto.
sys.modules["trajectory_reader"] = _heatmap_trajectory_reader
from heatmap_generator import (
    build_zone_masks,
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
from zonas import Layout, Zona, cargar_layout

# Preproceso propio del pipeline: escalado de zonas a la resolución real,
# anonimización de rostros y verificación de que la escena sea retail.
from video_anotado import VideoAnotado
from preproceso import (
    AnonimizadorRostros,
    ConfigAnonimizacion,
    escalar_zonas,
    evaluar_escena_retail,
    muestrear_frames_con_indices,
)

try:
    from zonas_auto import (
        dibujar_propuesta,
        guardar_propuesta,
        proponer_zonas,
        transito_desde_detecciones,
    )
    _HAS_ZONAS_AUTO = True
except ImportError:
    _HAS_ZONAS_AUTO = False

try:
    from recomendador import generar_recomendaciones
except ImportError:
    def generar_recomendaciones(_metricas: dict[str, Any], usar_ia: bool = False) -> dict[str, Any]:
        return {"recomendaciones": [], "fuente": "reglas-basicas"}

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


class VideoNoRetailError(RuntimeError):
    """El video subido no parece corresponder a una superficie comercial."""

    def __init__(self, mensaje: str, escena: dict[str, Any]):
        super().__init__(mensaje)
        self.escena = escena


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
        model_path: str | None = None,
        conf_threshold: float | None = None,
        colormap: str = "turbo",
        anonimizar: bool = True,
        modo_anonimizacion: str = "blur",
        verificar_escena: bool = True,
        umbral_escena: float = 0.45,
        frame_skip: int = 1,
        video_anotado: bool = True,
        zonas_auto: bool = False,
        usar_ia: bool = True,
        detector: PersonDetector | None = None,
        perfil: str | None = "sintetico",
        batch_size: int | None = None,
    ):
        self.video_source = video_source
        self.zonas_path = zonas_path
        self.outdir = outdir
        self.productos = _cargar_productos(productos_path)
        self.t0 = datetime.fromisoformat(t0_str)
        self.min_dwell_s = min_dwell_s
        self.max_frames = max_frames
        self.colormap = colormap
        self.frame_skip = max(1, int(frame_skip))

        gracia_efectiva = max(1, round(gracia_frames / self.frame_skip))
        self.generar_video_anotado = video_anotado
        self.zonas_auto = zonas_auto
        self.usar_ia = usar_ia
        self._writer_video: VideoAnotado | None = None
        self.verificar_escena = verificar_escena
        self.umbral_escena = umbral_escena
        self.anonimizador = AnonimizadorRostros(
            ConfigAnonimizacion(activo=anonimizar, modo=modo_anonimizacion)
        )
        self.info_zonas: dict[str, Any] = {}
        self.escena: dict[str, Any] = {}

        self.outdir.mkdir(parents=True, exist_ok=True)

        # ── Módulo 2: Detector de personas ──────────────────────────────────
        if detector is not None:
            detector.reset_stats()
            self.detector = detector
        elif model_path is not None or conf_threshold is not None:
            base = PERFILES.get(perfil, {}) if perfil else {}
            self.detector = PersonDetector(
                model_path=model_path or base.get("model", "yolov8n.pt"),
                conf_threshold=conf_threshold if conf_threshold is not None else base.get("conf", 0.4),
                iou_threshold=base.get("iou", 0.45),
                imgsz=base.get("imgsz", 640),
            )
        else:
            print("[pipeline] Iniciando módulo 2 — Detección de personas (Samuel)...")
            self.detector = PersonDetector(perfil=perfil or "sintetico")

        if batch_size is not None:
            self.batch_size = max(1, int(batch_size))
        else:
            dev = getattr(self.detector, "_torch_device", None)
            self.batch_size = 8 if (dev is not None and dev.type == "cuda") else 4

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
            grace_frames=gracia_efectiva,
        )

        # ── Módulo 1: Máquina de estados ────────────────────────────────────
        print("[pipeline] Iniciando módulo 1 — Detección de eventos (Nicol)...")
        layout = cargar_layout(zonas_path)
        self.maquina = InteractionStateMachine(
            layout=layout,
            config=InteractionConfig(
                min_dwell_s=min_dwell_s,
                gracia_frames=gracia_efectiva,
            ),
            reach_config=ReachConfig(),
            modo_alcance=modo_alcance,
        )

        # ── Módulo 4: Datos para heatmap (acumulador en memoria) ─────────────
        print("[pipeline] Iniciando módulo 4 — Mapa de calor (Arturo)...")
        self.zonas_data_heatmap: dict | None = None  # se inicializa al leer el video
        self._conteos_zonas: dict[str, Any] = {"video_ref": None, "frames_procesados": 1, "zonas": []}

        # Escritores JSONL intermedios con buffer amplio
        self._fh_detecciones = open(outdir / "detecciones.jsonl", "w", encoding="utf-8", buffering=65536)
        self._fh_tracking = open(outdir / "tracking.jsonl", "w", encoding="utf-8", buffering=65536)

        # Métricas globales
        self._frames_procesados = 0
        self._total_detecciones = 0
        self._ultimo_ts = 0.0
        self._frame_ref: np.ndarray | None = None

    # ── Helpers internos ────────────────────────────────────────────────────

    def _cerrar_recursos_abiertos(self) -> None:
        if self._writer_video is not None:
            try:
                self._writer_video.cerrar()
            except Exception:
                pass
            self._writer_video = None
        if not self._fh_detecciones.closed:
            self._fh_detecciones.close()
        if not self._fh_tracking.closed:
            self._fh_tracking.close()

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
        # Muestreo unico reutilizado entre validacion de escena y zonas_auto.
        muestras_idx: list[tuple[int, np.ndarray]] = []
        if (self.verificar_escena or (self.zonas_auto and _HAS_ZONAS_AUTO)) and not str(self.video_source).isdigit():
            n_muestras = 20 if self.zonas_auto else 12
            muestras_idx = muestrear_frames_con_indices(str(self.video_source), n=n_muestras)

        # Verificación de escena ANTES de gastar minutos de inferencia en un
        # video que no es de una superficie comercial.
        if self.verificar_escena and not str(self.video_source).isdigit():
            print("[pipeline] Verificando que el video sea de una superficie comercial...")
            if len(muestras_idx) > 12:
                paso_m = len(muestras_idx) / 12
                muestras_escena = [muestras_idx[int(i * paso_m)][1] for i in range(12)]
            else:
                muestras_escena = [f for _, f in muestras_idx]
            resultado = evaluar_escena_retail(
                muestras_escena, umbral=self.umbral_escena
            )
            self.escena = resultado.to_dict()
            if resultado.senales:
                print(f"[pipeline] Puntaje de escena retail: {resultado.puntaje:.2f}")
            else:
                print(f"[aviso] {resultado.motivo}")
            if not resultado.es_retail:
                self._fh_detecciones.close()
                self._fh_tracking.close()
                raise VideoNoRetailError(resultado.motivo, self.escena)

        if not str(source).isdigit() and not Path(str(source)).exists():
            self._fh_detecciones.close()
            self._fh_tracking.close()
            raise FileNotFoundError(
                f"[pipeline] No existe el archivo de video: {source}\n"
                f"           Ruta absoluta buscada: {Path(str(source)).resolve()}"
            )

        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            self._fh_detecciones.close()
            self._fh_tracking.close()
            raise RuntimeError(
                f"[pipeline] El archivo existe pero OpenCV no pudo abrirlo: {source}. "
                "Puede ser un códec no soportado; prueba convertirlo a .mp4 (H.264)."
            )

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
        cache_detecciones: dict[int, list[dict[str, Any]]] = {}
        if self.zonas_auto and not _HAS_ZONAS_AUTO:
            print("[aviso] zonas_auto solicitado pero módulo zonas_auto no disponible; se usan zonas fijas escaladas.")
        elif self.zonas_auto and _HAS_ZONAS_AUTO:
            print("[pipeline] Proponiendo zonas a partir del video...")
            if not muestras_idx:
                muestras_idx = muestrear_frames_con_indices(str(self.video_source), n=20)
            muestras = [f for _, f in muestras_idx]

            print(f"[pipeline] Estimando tránsito sobre {len(muestras)} frames de muestra...")
            detecciones_muestra: list[list[dict[str, Any]]] = []
            for i in range(0, len(muestras), self.batch_size):
                lote = muestras[i : i + self.batch_size]
                for dets in self.detector.detect_batch(lote):
                    detecciones_muestra.append([d.to_dict() for d in dets])
            for (idx_f, _), det_dicts in zip(muestras_idx, detecciones_muestra):
                if idx_f >= 0:
                    cache_detecciones[idx_f] = det_dicts

            n_personas = sum(len(d) for d in detecciones_muestra)
            transito = transito_desde_detecciones(detecciones_muestra, width, height)
            print(f"[pipeline] {n_personas} personas detectadas en las muestras")

            propuesta = proponer_zonas(
                muestras, width, height, transito_precalculado=transito
            )
            guardar_propuesta(propuesta, self.outdir / "zonas_propuestas.json")
            if muestras:
                frame_preview = self.anonimizador.aplicar(muestras[0], detecciones_muestra[0])
                dibujar_propuesta(
                    frame_preview, propuesta, self.outdir / "zonas_propuestas.png"
                )
            conteo = propuesta["_propuesta"]["conteo"]
            print(
                f"[pipeline] Zonas propuestas: {conteo['gondola']} góndolas, "
                f"{conteo['pasillo']} pasillos, {conteo['caja']} cajas"
            )
            print(f"[aviso] {propuesta['_propuesta']['advertencia']}")
            zonas_raw = propuesta

        # Libera frames muestreados de RAM antes de procesar el video completo.
        muestras_idx.clear()

        self.zonas_data_heatmap, self.info_zonas = escalar_zonas(zonas_raw, width, height)

        (self.outdir / "zonas_usadas.json").write_text(
            json.dumps(self.zonas_data_heatmap, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        zonas_lista = self.zonas_data_heatmap.get("zonas", [])
        self.maquina.layout = Layout(
            [
                Zona(
                    zone_id=z["zone_id"],
                    poligono=[(float(px), float(py)) for px, py in z["poligono"]],
                    es_gondola=z.get("es_gondola"),
                )
                for z in zonas_lista
            ],
            metadata={
                k: v for k, v in self.zonas_data_heatmap.items() if k != "zonas"
            },
        )

        self.dwell_analyzer.zones = {
            z["zone_id"]: {"vertices": z["poligono"]}
            for z in zonas_lista
        }
        self.dwell_analyzer.zone_polygons = {
            zid: self.dwell_analyzer._validar_vertices(zid, zdata)
            for zid, zdata in self.dwell_analyzer.zones.items()
        }
        self.dwell_analyzer._reconstruir_bboxes()

        if self.info_zonas["escalado_aplicado"]:
            print(
                f"[pipeline] Zonas reproyectadas {self.info_zonas['resolucion_origen']} "
                f"-> {self.info_zonas['resolucion_destino']}"
            )
        if not self.info_zonas["confiable"]:
            print(f"[aviso] {self.info_zonas['advertencia']}")

        if self.generar_video_anotado:
            self._writer_video = VideoAnotado(
                self.outdir / "video_anotado.mp4",
                fps=max(1.0, fps / self.frame_skip),
                ancho=width,
                alto=height,
                zonas=zonas_lista,
                anonimizador=self.anonimizador,
            )

        zone_masks = build_zone_masks(zonas_lista, width, height)
        visitas_por_zona: dict[str, set[str]] = defaultdict(set)
        frames_ocupada_por_zona: dict[str, set[int]] = defaultdict(set)
        frames_con_tracks: set[int] = set()

        t_inicio = time.time()

        # Productor de lotes en segundo plano usando grab() + retrieve() selectivo.
        cola_lotes: queue.Queue[list[tuple[int, float, np.ndarray]] | None] = queue.Queue(maxsize=3)
        error_lectura: list[BaseException] = []
        detener_lectura = threading.Event()

        def _leer_lotes() -> None:
            lote: list[tuple[int, float, np.ndarray]] = []
            fid = 0
            try:
                while not detener_lectura.is_set():
                    if self.max_frames is not None and fid >= self.max_frames:
                        break
                    if not cap.grab():
                        break
                    if fid % self.frame_skip != 0:
                        fid += 1
                        continue
                    ok, frame = cap.retrieve()
                    if not ok:
                        break
                    ts_ms = (fid / fps) * 1000.0
                    lote.append((fid, ts_ms, frame))
                    if len(lote) >= self.batch_size:
                        cola_lotes.put(lote)
                        lote = []
                    fid += 1
                if lote and not detener_lectura.is_set():
                    cola_lotes.put(lote)
            except BaseException as exc:  # noqa: BLE001
                error_lectura.append(exc)
            finally:
                cola_lotes.put(None)

        lector = threading.Thread(target=_leer_lotes, daemon=True)
        lector.start()

        try:
            while True:
                lote = cola_lotes.get()
                if lote is None:
                    break

                # Deteccion por lotes solo para frames que no fueron muestreados ya.
                indices_pendientes = [i for i, (fid, _, _) in enumerate(lote) if fid not in cache_detecciones]
                if indices_pendientes:
                    frames_pendientes = [lote[i][2] for i in indices_pendientes]
                    dets_lote = self.detector.detect_batch(frames_pendientes)
                    for idx_pos, dets in zip(indices_pendientes, dets_lote):
                        fid_pend = lote[idx_pos][0]
                        cache_detecciones[fid_pend] = [d.to_dict() for d in dets]

                for fid, timestamp_ms, frame in lote:
                    det_dicts = cache_detecciones.pop(fid, [])

                    if self._frame_ref is None:
                        self._frame_ref = self.anonimizador.aplicar(frame, det_dicts)

                    self._fh_detecciones.write(
                        json.dumps(
                            {
                                "frame_id": fid,
                                "timestamp_ms": round(timestamp_ms, 2),
                                "detections": det_dicts,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )

                    # ── Etapa 3: Tracking ────────────────────────────────────
                    tracks = self.tracker.update(det_dicts, frame_shape=frame.shape)

                    self._fh_tracking.write(
                        json.dumps(
                            {
                                "frame_id": fid,
                                "timestamp_ms": round(timestamp_ms, 2),
                                "tracks": tracks,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )

                    # ── Etapa 4: Acumulación del heatmap y conteos por zona ──
                    for t in tracks:
                        bbox = t.get("bbox", [])
                        if len(bbox) == 4:
                            x1, y1, x2, y2 = bbox
                            cx = int(round((x1 + x2) / 2))
                            cy = int(round((y1 + y2) / 2))
                            tid = t.get("person_id", t.get("track_id"))
                            tid_str = str(tid) if tid is not None else None
                            if tid_str is not None:
                                frames_con_tracks.add(fid)
                            if 0 <= cx < width and 0 <= cy < height:
                                self._heatmap_acum[cy, cx] += 1
                                if tid_str is not None:
                                    for zid, zmask in zone_masks.items():
                                        if zmask[cy, cx]:
                                            visitas_por_zona[zid].add(tid_str)
                                            frames_ocupada_por_zona[zid].add(fid)

                    # ── Etapa 5: Tiempo de permanencia ───────────────────────
                    self.dwell_analyzer.process_frame(timestamp_ms, tracks)

                    # ── Etapa 1: Detección de eventos ────────────────────────
                    n_eventos_previos = len(self.maquina.eventos)
                    self.maquina.process_frame(timestamp_ms, tracks)
                    eventos_nuevos = self.maquina.eventos[n_eventos_previos:]

                    # ── Etapa 6: Video anotado ───────────────────────────────
                    if self._writer_video is not None:
                        self._writer_video.escribir(
                            frame, det_dicts, tracks, eventos_nuevos, timestamp_ms
                        )

                    self._frames_procesados += 1
                    self._total_detecciones += len(det_dicts)
                    self._ultimo_ts = timestamp_ms

                    if self._frames_procesados % 100 == 0:
                        elapsed = time.time() - t_inicio
                        print(
                            f"[pipeline] Frame {fid + 1} | "
                            f"{elapsed:.1f}s | "
                            f"{self._frames_procesados / elapsed:.1f} fps efectivos"
                        )
        except BaseException:
            self._cerrar_recursos_abiertos()
            raise
        finally:
            detener_lectura.set()
            # Drena un elemento si el productor quedo bloqueado en put()
            try:
                while not cola_lotes.empty():
                    cola_lotes.get_nowait()
            except queue.Empty:
                pass
            lector.join(timeout=5)
            cap.release()

        if error_lectura:
            self._cerrar_recursos_abiertos()
            raise error_lectura[0]

        n_frames_conteo = len(frames_con_tracks) if frames_con_tracks else 1
        self._conteos_zonas = {
            "video_ref": self.zonas_data_heatmap.get("video_ref"),
            "frames_procesados": n_frames_conteo,
            "zonas": [
                {
                    "zone_id": z["zone_id"],
                    "visitas_unicas": len(visitas_por_zona.get(z["zone_id"], ())),
                    "frames_ocupada": (ocupada := len(frames_ocupada_por_zona.get(z["zone_id"], ()))),
                    "pct_tiempo_ocupada": round(100 * ocupada / n_frames_conteo, 2),
                }
                for z in zonas_lista
            ],
        }

        if self._writer_video is not None:
            info_video = self._writer_video.cerrar()
            self._writer_video = None
            print(f"[pipeline] Video anotado: {info_video['frames']} frames -> {info_video['ruta']}")

        # ── Finalizar módulos ────────────────────────────────────────────────
        self.dwell_analyzer.finalize(self._ultimo_ts)
        all_dwell = self.dwell_analyzer.get_events()
        with open(self.outdir / "dwell_time.jsonl", "w", encoding="utf-8", buffering=65536) as fh:
            for ev in all_dwell:
                fh.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")

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

        meta["escena"] = self.escena
        meta["zonas"] = self.info_zonas
        meta["frame_skip"] = self.frame_skip
        meta["rostros_anonimizados"] = self.anonimizador.rostros_cubiertos

        # ── Módulo 4: Heatmap ────────────────────────────────────────────────
        print("[pipeline] Generando heatmap (módulo 4 — Arturo)...")
        heatmap_smooth = smooth_heatmap(self._heatmap_acum)
        conteos_zonas = self._conteos_zonas

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
        metricas = calcular_metricas(
            eventos, [z.zone_id for z in self.maquina.layout.gondolas]
        )
        resultado_reco = generar_recomendaciones(metricas, usar_ia=self.usar_ia)
        metricas["recomendaciones"] = resultado_reco["recomendaciones"]
        metricas["recomendaciones_fuente"] = resultado_reco["fuente"]
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
        default=None,
        help="Pesos de YOLO para la detección de personas (default: perfil sintetico)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=None,
        help="Umbral de confianza para YOLO (default: segun perfil)",
    )
    parser.add_argument(
        "--colormap",
        default="turbo",
        choices=["jet", "turbo", "inferno", "hot", "magma"],
        help="Colormap del heatmap (default: turbo)",
    )
    parser.add_argument(
        "--sin-ia",
        action="store_true",
        help="Recomendaciones solo por reglas, sin llamar al modelo de lenguaje",
    )
    parser.add_argument(
        "--zonas-auto",
        action="store_true",
        help="Propone zonas automáticamente si zonas_auto está disponible",
    )
    parser.add_argument(
        "--sin-video-anotado",
        action="store_true",
        help="No generar video_anotado.mp4",
    )
    parser.add_argument(
        "--frame-skip",
        type=int,
        default=1,
        help="Procesar 1 de cada N frames (default: 1)",
    )
    parser.add_argument(
        "--sin-anonimizar",
        action="store_true",
        help="Desactiva el difuminado de rostros",
    )
    parser.add_argument(
        "--sin-verificar-escena",
        action="store_true",
        help="Omite la verificación de escena retail",
    )
    parser.add_argument(
        "--umbral-escena",
        type=float,
        default=0.45,
        help="Puntaje mínimo para aceptar el video como retail (default: 0.45)",
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
        anonimizar=not args.sin_anonimizar,
        verificar_escena=not args.sin_verificar_escena,
        umbral_escena=args.umbral_escena,
        frame_skip=args.frame_skip,
        video_anotado=not args.sin_video_anotado,
        zonas_auto=args.zonas_auto,
        usar_ia=not args.sin_ia,
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
