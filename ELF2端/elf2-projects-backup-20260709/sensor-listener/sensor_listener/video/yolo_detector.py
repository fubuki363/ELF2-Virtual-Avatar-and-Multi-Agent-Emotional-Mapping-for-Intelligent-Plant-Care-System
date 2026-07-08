"""YOLOv5 plant growth detection — leaf and flower recognition."""
import time
import threading
from pathlib import Path
import numpy as np

DEDUP_COOLDOWN = 30.0  # seconds between notifications for same class
DEDUP_CONSECUTIVE = 3   # consecutive detections needed


class YoloDetector:
    """Runs YOLOv5 inference on video frames to detect new leaves and flowers."""

    def __init__(self, model_path: str = "best.pt", conf: float = 0.5,
                 interval: float = 10.0, capture_dir: str = "video/captures"):
        self._conf = conf
        self._interval = interval
        self._capture_dir = Path(capture_dir)
        self._capture_dir.mkdir(parents=True, exist_ok=True)
        self._last_inference = 0.0
        self._last_notify: dict[str, float] = {}  # class -> last notification time
        self._consecutive: dict[str, int] = {}     # class -> consecutive count
        self._model = None
        self._model_path = model_path
        self._lock = threading.Lock()

    def _load_model(self):
        """Lazy-load YOLOv5 model."""
        if self._model is None:
            import torch
            self._model = torch.hub.load('ultralytics/yolov5', 'custom',
                                         path=self._model_path, force_reload=False)
            self._model.conf = self._conf
        return self._model

    def should_infer(self) -> bool:
        """Check if enough time has passed since last inference."""
        return (time.time() - self._last_inference) >= self._interval

    def detect(self, frame: np.ndarray) -> list[dict]:
        """Run YOLO inference on a single frame. Returns list of detection dicts."""
        self._last_inference = time.time()
        try:
            model = self._load_model()
            results = model(frame)
            detections = []
            for *xyxy, conf, cls in results.xyxy[0]:
                class_name = model.names[int(cls)]
                detections.append({
                    "class": class_name,
                    "confidence": float(conf),
                    "bbox": [int(x) for x in xyxy],
                })
            return detections
        except Exception as e:
            import sys
            print(f"[YOLO] 推理失败: {e}", file=sys.stderr)
            return []

    def is_new_growth(self, detections: list[dict]) -> dict | None:
        """Check detections against dedup logic. Returns the first genuinely new
        detection, or None if all are suppressed."""
        now = time.time()
        for d in detections:
            cls = d["class"]
            # Track consecutive sightings
            self._consecutive[cls] = self._consecutive.get(cls, 0) + 1

            if self._consecutive[cls] < DEDUP_CONSECUTIVE:
                continue
            if (now - self._last_notify.get(cls, 0)) < DEDUP_COOLDOWN:
                continue

            self._last_notify[cls] = now
            return d  # First new detection wins

        # Reset consecutive counters for classes not seen
        seen = {d["class"] for d in detections}
        for cls in list(self._consecutive):
            if cls not in seen:
                self._consecutive[cls] = 0
        return None

    def save_screenshot(self, frame: np.ndarray, detections: list[dict]) -> str:
        """Save annotated frame to captures directory. Returns file path."""
        import cv2
        annotated = frame.copy()
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            color = (0, 255, 0) if d["class"] == "leaf" else (255, 0, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(annotated, f"{d['class']} {d['confidence']:.2f}",
                        (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._capture_dir / f"growth_{ts}.jpg"
        cv2.imwrite(str(path), annotated)
        return str(path)
