"""
person_detector.py
Modulo de Deteccion de Personas - GondHawk (Reto Gondola Inteligente)
Integrante 2 (Deteccion de personas)

Responsabilidad de este modulo (segun la guia del reto):
  - Reconocer personas en cada cuadro del video usando YOLO (Ultralytics).
  - NO guarda ni analiza caras. Solo entrega la posicion (bounding box) de
    cada persona detectada en cada frame, para que el integrante 3
    (Tracking) le asigne un ID y arme las trayectorias.

Cumplimiento de privacidad (Ley 1581 de 2012):
  - Este modulo nunca recorta, guarda ni procesa la region facial.
  - No se hace ningun tipo de reconocimiento facial ni biometrico.
  - Solo se conserva: bounding box, confianza y clase ("person").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.data.augment import LetterBox
from ultralytics.utils import nms, ops

# En el dataset COCO (con el que viene entrenado YOLO por defecto),
# la clase 0 es "person". Filtramos solo esa clase.
PERSON_CLASS_ID = 0

# Raiz del proyecto (GondHawk-main), calculada desde este archivo para que
# el path del modelo no dependa de la maquina/usuario donde se clone el repo.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_WEIGHTS_DIR = _PROJECT_ROOT / "runs" / "detect" / "train" / "weights"


def _resolver_modelo_sintetico() -> str:
    """Devuelve best.pt o last.pt si existen en el repo; si no, yolov8n.pt."""
    for nombre in ("best.pt", "last.pt"):
        candidato = _WEIGHTS_DIR / nombre
        if candidato.exists():
            return str(candidato)
    return "yolov8n.pt"


_MODELO_SINTETICO = _resolver_modelo_sintetico()

# Perfiles de deteccion segun el origen del video.
PERFILES = {
    # Video grabado en tienda: la textura y la iluminacion reales dan
    # confianzas altas, asi que se puede exigir mas y evitar falsos positivos.
    "real": {"conf": 0.40, "iou": 0.50, "imgsz": 640},
    # Escena sintetica renderizada: ahora con un modelo entrenado específicamente
    # sobre figuras 3D, podemos subir la confianza y mejorar la precisión.
    # 736 es el multiplo de 32 al que Ultralytics redondeaba 720 en cada frame.
    "sintetico": {
        "conf": 0.35,
        "iou": 0.45,
        "imgsz": 736,
        "model": _MODELO_SINTETICO,
    },
    # Para diagnosticar: acepta casi todo. Sirve para saber si el detector
    # "ve" algo o no ve nada, no para producir metricas.
    "permisivo": {"conf": 0.10, "iou": 0.45, "imgsz": 736},
}


@dataclass
class Detection:
    """Una deteccion de persona en un frame (formato acordado con el equipo)."""

    bbox: List[float]  # [x1, y1, x2, y2] en pixeles, esquina sup-izq / inf-der
    confidence: float
    cls: str = "person"

    def to_dict(self) -> dict:
        return {
            "bbox": [round(float(v), 1) for v in self.bbox],
            "confidence": round(float(self.confidence), 4),
            "class": self.cls,
        }


class PersonDetector:
    """Envoltorio simple sobre YOLO de Ultralytics para detectar personas."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        device: Optional[str] = None,
        imgsz: int = 640,
        perfil: Optional[str] = None,
        min_area: float = 0.0,
    ):
        """
        Args:
            model_path: pesos de YOLO.
            conf_threshold: confianza minima para aceptar una deteccion.
            iou_threshold: umbral de IoU para el Non-Max Suppression interno.
            device: "cpu", "cuda", "cuda:0", etc. None deja que Ultralytics elija.
            imgsz: resolucion de inferencia.
            perfil: "real", "sintetico" o "permisivo".
            min_area: area minima del bbox en pixeles cuadrados.
        """
        if perfil is not None:
            if perfil not in PERFILES:
                raise ValueError(
                    f"Perfil desconocido: {perfil}. Opciones: {list(PERFILES)}"
                )
            ajustes = PERFILES[perfil]
            conf_threshold = ajustes["conf"]
            iou_threshold = ajustes["iou"]
            imgsz = ajustes["imgsz"]
            if "model" in ajustes:
                model_path = ajustes["model"]

        self.model = YOLO(model_path)
        self.model_path = str(model_path)
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        # Asegura multiplo de 32 sin warnings repetidos de Ultralytics.
        self.imgsz = int(((int(imgsz) + 31) // 32) * 32)
        self.perfil = perfil
        self.min_area = min_area

        # Fast-path PyTorch: fusiona Conv+BN una sola vez y evita crear un
        # DetectionPredictor nuevo en cada frame o lote.
        self._fast_net = None
        self._torch_device = None
        self._letterbox = None
        self._stride = 32
        self._preparar_fast_path()

        # Contadores para diagnostico: si las detecciones caen, lo primero que
        # hay que saber es si el detector no ve nada o si se estan filtrando.
        self.total_detectadas = 0
        self.total_descartadas_por_area = 0

    def _preparar_fast_path(self) -> None:
        if not self.model_path.lower().endswith(".pt"):
            return
        net = getattr(self.model, "model", None)
        if not isinstance(net, torch.nn.Module) or getattr(net, "end2end", False):
            return
        try:
            dev_str = self.device or ("cuda:0" if torch.cuda.is_available() else "cpu")
            dev = torch.device(dev_str)
            net.to(dev)
            net.eval()
            if hasattr(net, "fuse"):
                net.fuse(verbose=False)
            stride_val = getattr(net, "stride", 32)
            if hasattr(stride_val, "max"):
                stride_val = int(stride_val.max())
            else:
                stride_val = int(stride_val)
            self._stride = max(32, stride_val)
            self._torch_device = dev
            self._fast_net = net
            self._letterbox = LetterBox((self.imgsz, self.imgsz), auto=True, stride=self._stride)
        except Exception:
            self._fast_net = None

    def reset_stats(self) -> None:
        self.total_detectadas = 0
        self.total_descartadas_por_area = 0

    def _filtrar_cajas(self, cajas_xyxy: Sequence[Sequence[float]], confs: Sequence[float]) -> List[Detection]:
        detections: List[Detection] = []
        min_area = self.min_area
        for xyxy, conf in zip(cajas_xyxy, confs):
            if min_area > 0:
                if (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1]) < min_area:
                    self.total_descartadas_por_area += 1
                    continue
            detections.append(Detection(bbox=list(xyxy), confidence=float(conf)))
        self.total_detectadas += len(detections)
        return detections

    def detect_batch(self, frames: Sequence[np.ndarray]) -> List[List[Detection]]:
        """Detecta personas en un lote de frames BGR conservando el orden."""
        if not frames:
            return []

        if self._fast_net is not None:
            shape0 = frames[0].shape[:2]
            mismo_tamano = len(frames) == 1 or all(f.shape[:2] == shape0 for f in frames)
            if mismo_tamano:
                imgs = [self._letterbox(image=f) for f in frames]
                arr = np.ascontiguousarray(np.stack(imgs)[..., ::-1].transpose(0, 3, 1, 2))
                with torch.inference_mode():
                    tensor = torch.from_numpy(arr).to(self._torch_device, dtype=torch.float32)
                    tensor.div_(255.0)
                    preds = self._fast_net(tensor)
                    dets = nms.non_max_suppression(
                        preds,
                        conf_thres=self.conf_threshold,
                        iou_thres=self.iou_threshold,
                        classes=[PERSON_CLASS_ID],
                    )
                    salida: List[List[Detection]] = []
                    in_shape = tensor.shape[2:]
                    for i, d in enumerate(dets):
                        if len(d):
                            d[:, :4] = ops.scale_boxes(in_shape, d[:, :4], frames[i].shape)
                            d_cpu = d.cpu()
                            salida.append(
                                self._filtrar_cajas(d_cpu[:, :4].tolist(), d_cpu[:, 4].tolist())
                            )
                        else:
                            salida.append([])
                    return salida

        results = self.model.predict(
            source=list(frames),
            classes=[PERSON_CLASS_ID],
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )
        salida = []
        for res in results:
            if res.boxes is None or len(res.boxes) == 0:
                salida.append([])
                continue
            salida.append(
                self._filtrar_cajas(res.boxes.xyxy.cpu().tolist(), res.boxes.conf.cpu().tolist())
            )
        return salida

    def detect_frame(self, frame: np.ndarray) -> List[Detection]:
        """Detecta personas en un solo frame (numpy array BGR, como los da OpenCV).

        Returns:
            Lista de Detection ordenada como la entrega el modelo.
        """
        return self.detect_batch([frame])[0]

    def resumen(self) -> dict:
        """Estadisticas de la corrida, utiles para comparar configuraciones."""
        return {
            "modelo": getattr(self.model, "model_name", "yolov8"),
            "perfil": self.perfil,
            "conf_threshold": self.conf_threshold,
            "iou_threshold": self.iou_threshold,
            "imgsz": self.imgsz,
            "total_detectadas": self.total_detectadas,
            "descartadas_por_area": self.total_descartadas_por_area,
        }
