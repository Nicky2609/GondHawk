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

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from ultralytics import YOLO

# En el dataset COCO (con el que viene entrenado YOLO por defecto),
# la clase 0 es "person". Filtramos solo esa clase.
PERSON_CLASS_ID = 0


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
        conf_threshold: float = 0.4,
        iou_threshold: float = 0.5,
        device: Optional[str] = None,
    ):
        """
        Args:
            model_path: pesos de YOLO. "yolov8n.pt" se descarga automaticamente
                la primera vez (modelo liviano, bueno para prototipo/CPU).
            conf_threshold: confianza minima para aceptar una deteccion.
            iou_threshold: umbral de IoU para el Non-Max Suppression interno.
            device: "cpu", "cuda", "cuda:0", etc. None deja que Ultralytics elija.
        """
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.device = device

    def detect_frame(self, frame: np.ndarray) -> List[Detection]:
        """Detecta personas en un solo frame (numpy array BGR, como los da OpenCV).

        Returns:
            Lista de Detection ordenada como la entrega el modelo.
        """
        results = self.model.predict(
            source=frame,
            classes=[PERSON_CLASS_ID],
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )[0]

        detections: List[Detection] = []
        if results.boxes is None:
            return detections

        for box in results.boxes:
            xyxy = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            detections.append(Detection(bbox=xyxy, confidence=conf))

        return detections
