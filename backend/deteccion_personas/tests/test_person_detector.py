"""
Pruebas basicas del modulo de deteccion de personas.

No dependen de tener un video real: usan una imagen sintetica para
verificar que el pipeline corre sin errores y que la salida respeta
el formato acordado con el equipo (bbox, confidence, class).
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from person_detector import PersonDetector, Detection  # noqa: E402


def test_detection_to_dict_format():
    det = Detection(bbox=[10.234, 20.111, 50.9, 80.4], confidence=0.876543)
    d = det.to_dict()

    assert set(d.keys()) == {"bbox", "confidence", "class"}
    assert d["class"] == "person"
    assert isinstance(d["bbox"], list) and len(d["bbox"]) == 4
    assert d["confidence"] == 0.8765  # redondeado a 4 decimales


def test_detector_runs_on_blank_frame():
    # Frame negro de prueba: no tiene personas, pero el pipeline debe
    # correr sin lanzar excepciones y devolver una lista (vacia o no).
    detector = PersonDetector(conf_threshold=0.4)
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = detector.detect_frame(blank_frame)

    assert isinstance(detections, list)
    for det in detections:
        assert isinstance(det, Detection)
        assert len(det.bbox) == 4
        assert 0.0 <= det.confidence <= 1.0


if __name__ == "__main__":
    test_detection_to_dict_format()
    test_detector_runs_on_blank_frame()
    print("OK: todas las pruebas pasaron")
