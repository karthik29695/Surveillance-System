import cv2
import numpy as np
from typing import List, Dict, Any
from app.core.config import settings

class YOLODetector:
    def __init__(self):
        self.model = None
        self.target_classes = settings.TARGET_CLASSES
        self.confidence = settings.YOLO_CONFIDENCE
        self._load_model()

    def _load_model(self):
        try:
            from ultralytics import YOLO
            self.model = YOLO(settings.YOLO_MODEL)
            self.model.to(settings.YOLO_DEVICE)
            print(f"[YOLODetector] Loaded: {settings.YOLO_MODEL}")
        except Exception as e:
            print(f"[YOLODetector] Warning: {e}")

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        if self.model is None:
            return []
        results = self.model(frame, conf=self.confidence, verbose=False)
        detections = []
        for r in results:
            for box in r.boxes:
                cls_name = r.names[int(box.cls)]
                if cls_name not in self.target_classes:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append({
                    "class": cls_name,
                    "confidence": float(box.conf),
                    "bbox": {"x": int(x1), "y": int(y1), "w": int(x2 - x1), "h": int(y2 - y1)},
                })
        return detections

    def annotate_frame(self, frame: np.ndarray, detections: List[Dict]) -> np.ndarray:
        annotated = frame.copy()
        for det in detections:
            b = det["bbox"]
            label = f"{det['class']} {det['confidence']:.2f}"
            cv2.rectangle(annotated, (b["x"], b["y"]), (b["x"]+b["w"], b["y"]+b["h"]), (0, 255, 0), 2)
            cv2.putText(annotated, label, (b["x"], b["y"]-8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return annotated
