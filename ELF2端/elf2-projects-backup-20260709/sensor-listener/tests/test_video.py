"""Tests for YOLO detector dedup logic."""
import pytest
from unittest import mock
import numpy as np
from sensor_listener.video.yolo_detector import YoloDetector


class TestYoloDetector:
    def test_should_infer_initially_true(self):
        detector = YoloDetector(interval=10.0)
        assert detector.should_infer() is True

    def test_should_infer_false_immediately_after(self):
        detector = YoloDetector(interval=10.0)
        with mock.patch.object(detector, '_load_model') as mock_load:
            mock_model = mock.MagicMock()
            mock_model.names = {0: "leaf", 1: "flower"}
            mock_model.return_value = mock_model
            mock_results = mock.MagicMock()
            mock_results.xyxy = [mock.MagicMock()]
            mock_model.return_value = mock_results
            mock_load.return_value = mock_model
            detector._model = mock_model
            detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        assert detector.should_infer() is False

    def test_is_new_growth_first_detection(self):
        detector = YoloDetector()
        detections = [{"class": "leaf", "confidence": 0.9, "bbox": [10, 10, 50, 50]}]
        # First detection shouldn't trigger (needs 3 consecutive)
        assert detector.is_new_growth(detections) is None
        # Second
        assert detector.is_new_growth(detections) is None
        # Third — triggers
        result = detector.is_new_growth(detections)
        assert result is not None
        assert result["class"] == "leaf"

    def test_is_new_growth_cooldown(self):
        detector = YoloDetector()
        detections = [{"class": "flower", "confidence": 0.8, "bbox": [0, 0, 100, 100]}]
        # 3 consecutive to trigger
        for _ in range(3):
            detector.is_new_growth(detections)
        # Should be suppressed by cooldown
        result = detector.is_new_growth(detections)
        assert result is None

    def test_save_screenshot_creates_file(self, tmp_path):
        detector = YoloDetector(capture_dir=str(tmp_path))
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        detections = [{"class": "leaf", "confidence": 0.95, "bbox": [100, 100, 300, 300]}]
        path = detector.save_screenshot(frame, detections)
        assert path.endswith(".jpg")
        import os
        assert os.path.exists(path)
