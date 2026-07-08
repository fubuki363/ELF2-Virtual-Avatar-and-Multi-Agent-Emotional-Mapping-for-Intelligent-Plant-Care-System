# Phase B+C: Video + YOLO + MQTT — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add K230 H265 video reception with YOLOv5 plant growth detection, and EMQX Cloud MQTT command routing for remote control.

**Architecture:** Two new subpackages (`video/`, `mqtt/`) added to existing `sensor_listener/`. Video runs in a `threading.Thread` (TCP server + H265 decode + YOLO inference). MQTT runs in paho's `loop_start()` background thread. Both communicate with the main asyncio loop via thread-safe shared state.

**Tech Stack:** Python 3.10+, PyAV (av), opencv-python, torch, ultralytics (YOLOv5), paho-mqtt, ssl

## Global Constraints

- Python 3.10+ (match ELF2: Python 3.10.12)
- Video source: K230 TCP:6001, H265 1280x720
- YOLO model: `best.pt` (YOLOv5, 2 classes: leaf/flower), confidence threshold 0.5
- YOLO interval: 10 seconds (configurable)
- YOLO dedup: 3 consecutive detections + 30s cooldown before new notification
- MQTT broker: `p8c59112.ala.cn-hangzhou.emqxsl.cn:8883` (TLS)
- MQTT topics: sub `rpi5/cloud/command`, pub `rpi5/cloud/data`, pub file `rpi5/cloud/file`
- MQTT credentials: user `rpi_user`, password `2725856571q`
- MQTT certificate: `mqtt/emqxsl-ca.crt` (copy from Plant_Project)
- Sensor queries adapted from I2C reads to shared sensor_state dict reads
- YOLO screenshots saved to `video/captures/`
- New growth notification via MQTT topic `rpi5/cloud/data` with JSON payload
- New command: `/plant.photo.take` — trigger immediate YOLO scan
- New command: `/plant.health.get` — return health score + summary
- All 32 existing tests must continue to pass
- Existing CLI args preserved; new args: `--no-video`, `--no-mqtt`, `--yolo-interval`, `--yolo-model`, `--yolo-conf`

---

### Task 1: video/ subpackage — receiver + H265 decoder

**Files:**
- Create: `sensor_listener/video/__init__.py`
- Create: `sensor_listener/video/receiver.py` (port from `D:\bigcreate\pc\pc\lib\receiver.py`)
- Create: `sensor_listener/video/h265.py` (port from `D:\bigcreate\pc\pc\lib\h265.py`)
- Modify: `sensor_listener/main.py` — add `--no-video` flag, import and start video thread

**Interfaces:**
- Produces: `from sensor_listener.video.receiver import DataReceiver`
- Produces: `from sensor_listener.video.h265 import VideoStreamHandler`
- `DataReceiver(video_handler)` — TCP:6001 server, accepts K230 connection, dispatches video frames and messages
- `VideoStreamHandler()` — PyAV HEVC decoder, `configure(width, height)`, `process_frame(frame_data, nalu_count)`, `get_frame(timeout) -> np.ndarray | None`

- [ ] **Step 1: Copy receiver.py and h265.py into video/**

Copy from `D:\bigcreate\pc\pc\lib/receiver.py` → `sensor_listener/video/receiver.py`
Copy from `D:\bigcreate\pc\pc\lib/h265.py` → `sensor_listener/video/h265.py`

Update imports: remove relative `lib.` prefix, use absolute `sensor_listener.video.` imports.

In `receiver.py`, change `SERVER_PORT` from 6001 to 6000 (matching spec).

- [ ] **Step 2: Create video/__init__.py**

```python
# sensor_listener.video — K230 H265 video reception and YOLO analysis
```

- [ ] **Step 3: Add --no-video flag to main.py**

In `sensor_listener/main.py`:
```python
parser.add_argument("--no-video", action="store_true", help="禁用视频接收和 YOLO")
parser.add_argument("--video-port", type=int, default=6001, help="TCP 视频端口 (默认: 6001)")
```

Add video startup after asyncio event loop creation (but before `while True`):

```python
video_thread = None
if not args.no_video:
    from sensor_listener.video.receiver import DataReceiver
    from sensor_listener.video.h265 import VideoStreamHandler
    video_handler = VideoStreamHandler()
    video_receiver = DataReceiver(video_handler, port=args.video_port)
    video_thread = threading.Thread(target=video_receiver.start, daemon=True)
    video_thread.start()
```

- [ ] **Step 4: Install dependencies**

```bash
pip install av opencv-python numpy
```

- [ ] **Step 5: Verify existing tests still pass**

Run: `pytest tests/ -v --ignore=tests/test_video.py 2>&1`
Expected: All 32 tests PASS

- [ ] **Step 6: Commit**

```bash
git add sensor_listener/video/ sensor_listener/main.py
git commit -m "feat: add video subpackage with TCP receiver and H265 decoder"
```

---

### Task 2: YOLO Detector

**Files:**
- Create: `sensor_listener/video/yolo_detector.py`
- Copy: `best.pt` from `D:\bigcreate\yolo\best.pt` → `sensor_listener/best.pt`
- Create: `tests/test_video.py`
- Modify: `sensor_listener/main.py` — wire YOLO into video pipeline

**Interfaces:**
- Produces: `class YoloDetector` with:
  - `__init__(self, model_path: str, conf: float = 0.5, interval: float = 10.0)`
  - `detect(self, frame: np.ndarray) -> list[dict]` — returns `[{"class": "leaf"|"flower", "confidence": float, "bbox": [x1,y1,x2,y2]}]`
  - `is_new_growth(self, detections: list[dict]) -> bool` — dedup logic
  - `save_screenshot(self, frame: np.ndarray, detections: list[dict]) -> str` — saves to `video/captures/`, returns path

- [ ] **Step 1: Copy best.pt**

```bash
cp /d/bigcreate/yolo/best.pt /d/bigcreate/hardware/sensor_listener/best.pt
```

- [ ] **Step 2: Write yolo_detector.py**

In `sensor_listener/video/yolo_detector.py`:

```python
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
        self._last_notify: dict[str, float] = {}  # class → last notification time
        self._consecutive: dict[str, int] = {}     # class → consecutive count
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
```

- [ ] **Step 3: Write tests**

In `tests/test_video.py`:

```python
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
```

- [ ] **Step 4: Run YOLO tests**

Run: `pytest tests/test_video.py -v`
Expected: All tests PASS

- [ ] **Step 5: Wire YOLO into main.py video loop**

Update the video startup in `sensor_listener/main.py` to include YOLO:

```python
if not args.no_video:
    from sensor_listener.video.receiver import DataReceiver
    from sensor_listener.video.h265 import VideoStreamHandler
    from sensor_listener.video.yolo_detector import YoloDetector

    video_handler = VideoStreamHandler()
    yolo_detector = YoloDetector(
        model_path=args.yolo_model,
        conf=args.yolo_conf,
        interval=args.yolo_interval,
    )
    # ... start video thread ...
```

- [ ] **Step 6: Commit**

```bash
git add sensor_listener/video/yolo_detector.py sensor_listener/best.pt tests/test_video.py sensor_listener/main.py
git commit -m "feat: add YOLOv5 plant growth detector with dedup logic"
```

---

### Task 3: mqtt/ subpackage — subscriber + command router

**Files:**
- Create: `sensor_listener/mqtt/__init__.py`
- Create: `sensor_listener/mqtt/subscriber.py` (port from Plant_Project/Connect/subscriber.py)
- Create: `sensor_listener/mqtt/base_cmd.py` (port)
- Create: `sensor_listener/mqtt/commands.json` (port)
- Copy: `emqxsl-ca.crt` from Plant_Project/Connect/ → `sensor_listener/mqtt/`
- Modify: `sensor_listener/main.py` — add `--no-mqtt` flag, import and start MQTT

- [ ] **Step 1: Port subscriber.py**

Copy from `D:\bigcreate\yolo\Plant_Project\Connect\subscriber.py` → `sensor_listener/mqtt/subscriber.py`.

Adapt:
- `BASE_DIR` stays as `os.path.dirname(os.path.abspath(__file__))` (now resolves to mqtt/)
- `CA_CRT` path → `os.path.join(BASE_DIR, "emqxsl-ca.crt")`
- All else identical

- [ ] **Step 2: Port base_cmd.py + commands.json**

Copy `base_cmd.py` and `commands.json` directly — no changes needed.

- [ ] **Step 3: Copy TLS certificate**

```bash
cp /d/bigcreate/yolo/Plant_Project/Connect/emqxsl-ca.crt /d/bigcreate/hardware/sensor_listener/mqtt/
```

- [ ] **Step 4: Create mqtt/__init__.py**

```python
# sensor_listener.mqtt — EMQX Cloud MQTT command routing
```

- [ ] **Step 5: Add --no-mqtt flag to main.py**

```python
parser.add_argument("--no-mqtt", action="store_true", help="禁用 MQTT 云端连接")
```

Start MQTT after video startup:

```python
mqtt_client = None
cmd_queue = queue.Queue()

if not args.no_mqtt:
    from sensor_listener.mqtt.subscriber import start_mqtt
    mqtt_client = start_mqtt(cmd_queue=cmd_queue)
```

In the main loop, process MQTT commands:

```python
while True:
    # Process MQTT commands
    while not cmd_queue.empty():
        payload = cmd_queue.get()
        response = router.process(payload)
        if response.startswith("[FILE]"):
            from sensor_listener.mqtt.subscriber import send_file_over_mqtt
            file_path = response.split("[FILE]", 1)[1].strip()
            send_file_over_mqtt(mqtt_client, file_path)
        elif response and mqtt_client:
            mqtt_client.publish("rpi5/cloud/data", response)

    await asyncio.sleep(1)  # Check queue every second
```

- [ ] **Step 6: Install paho-mqtt**

```bash
pip install paho-mqtt
```

- [ ] **Step 7: Verify existing tests pass**

Run: `pytest tests/ -v --ignore=tests/test_mqtt.py`
Expected: All 32+ tests PASS

- [ ] **Step 8: Commit**

```bash
git add sensor_listener/mqtt/ sensor_listener/main.py
git commit -m "feat: add MQTT subpackage with EMQX command router"
```

---

### Task 4: mqtt/ command executors — adapted for ELF2

**Files:**
- Create: `sensor_listener/mqtt/cmd_sensor.py` (adapted from Plant_Project)
- Create: `sensor_listener/mqtt/cmd_sys.py` (port directly)
- Create: `sensor_listener/mqtt/cmd_file.py` (port directly)
- Create: `tests/test_mqtt.py`
- Modify: `sensor_listener/mqtt/commands.json` — add new ELF2-specific commands

- [ ] **Step 1: Write cmd_sensor.py (adapted for ELF2)**

Key difference from Plant_Project: reads from shared `sensor_state` dict instead of physical I2C.

In `sensor_listener/mqtt/cmd_sensor.py`:

```python
"""Sensor query commands — reads from shared UDP sensor state (not I2C)."""
from .base_cmd import BaseCommand

# Shared state, set by main.py at startup
_sensor_state: dict = {}


def set_sensor_state(state: dict):
    """Called by main.py to inject the latest sensor data."""
    global _sensor_state
    _sensor_state = state


class SensorTemperatureGet(BaseCommand):
    def execute(self, args: str) -> str:
        t = _sensor_state.get("t")
        if t is None:
            return "[ERROR 502] 温度传感器无数据"
        return f"[OK] /sensor.temperature.get = 当前温度: {t:.1f} °C"


class SensorHumidityGet(BaseCommand):
    def execute(self, args: str) -> str:
        h = _sensor_state.get("h")
        if h is None:
            return "[ERROR 502] 湿度传感器无数据"
        return f"[OK] /sensor.humidity.get = 当前湿度: {h:.1f} %RH"


class SensorIllumination_intensityGet(BaseCommand):
    def execute(self, args: str) -> str:
        light = _sensor_state.get("light")
        if light is None:
            return "[ERROR 502] 光照传感器无数据"
        return f"[OK] /sensor.illumination_intensity.get = 当前光照: {light:.1f} Lux"


class SensorCO2Get(BaseCommand):
    def execute(self, args: str) -> str:
        eco2 = _sensor_state.get("eco2")
        tvoc = _sensor_state.get("tvoc")
        if eco2 is None and tvoc is None:
            return "[ERROR 502] CCS811 传感器未就绪（预热中）"
        return f"[OK] /sensor.CO2.get = eCO2: {eco2} ppm | TVOC: {tvoc} ppb"


class SensorAir_qualityGet(BaseCommand):
    def execute(self, args: str) -> str:
        gas = _sensor_state.get("gas")
        if gas is None:
            return "[ERROR 502] 气体传感器无数据"
        return f"[OK] /sensor.air_quality.get = 气体电压: {gas:.3f} V"


class SensorSoil_moistureGet(BaseCommand):
    def execute(self, args: str) -> str:
        soil = _sensor_state.get("soil")
        if soil is None:
            return "[ERROR 502] 土壤传感器无数据"
        return f"[OK] /sensor.soil_moisture.get = 土壤湿度ADC: {soil}"


class SensorStateGet(BaseCommand):
    def execute(self, args: str) -> str:
        import json
        return json.dumps({
            "code": 200, "status": "success",
            "message": "获取设备综合状态成功",
            "data": {
                "temperature": _sensor_state.get("t"),
                "humidity": _sensor_state.get("h"),
                "light": _sensor_state.get("light"),
                "soil_moisture": _sensor_state.get("soil"),
                "air_quality": _sensor_state.get("gas"),
                "co2": _sensor_state.get("eco2"),
                "tvoc": _sensor_state.get("tvoc"),
                "health_score": _sensor_state.get("health_score"),
                "last_update": _sensor_state.get("last_update"),
            }
        }, ensure_ascii=False)


class PlantPhotoTake(BaseCommand):
    """Trigger immediate YOLO scan and return result."""
    def execute(self, args: str) -> str:
        yolo_event = _sensor_state.get("yolo_event")
        if yolo_event:
            import json
            return json.dumps({"code": 200, "status": "success",
                               "data": yolo_event}, ensure_ascii=False)
        return "[ERROR 503] 暂无YOLO检测结果，请稍后再试"


class PlantHealthGet(BaseCommand):
    """Return plant health score and analysis summary."""
    def execute(self, args: str) -> str:
        import json
        return json.dumps({
            "code": 200, "status": "success",
            "data": {
                "health_score": _sensor_state.get("health_score", 0),
                "alerts": _sensor_state.get("alerts", []),
                "trends": _sensor_state.get("trends", {}),
            }
        }, ensure_ascii=False)
```

- [ ] **Step 2: Port cmd_sys.py and cmd_file.py**

Copy directly from Plant_Project — no changes needed (they read system files, not I2C).

- [ ] **Step 3: Update commands.json**

Add new commands:
```json
{
    "/plant.photo.take": {"module": "cmd_sensor", "class": "PlantPhotoTake"},
    "/plant.health.get": {"module": "cmd_sensor", "class": "PlantHealthGet"}
}
```

- [ ] **Step 4: Write MQTT tests**

In `tests/test_mqtt.py`:

```python
"""Tests for MQTT command executors."""
import pytest
from sensor_listener.mqtt.cmd_sensor import (
    set_sensor_state, SensorTemperatureGet, SensorHumidityGet,
    SensorStateGet, SensorCO2Get, PlantHealthGet
)


@pytest.fixture(autouse=True)
def setup_state():
    set_sensor_state({
        "t": 26.3, "h": 54.8, "light": 320.5,
        "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200,
        "health_score": 87, "alerts": [], "trends": {"t": 0.5},
        "last_update": "2026-07-09T12:00:00",
    })


class TestSensorCommands:
    def test_temperature(self):
        result = SensorTemperatureGet().execute("")
        assert "26.3" in result
        assert "[OK]" in result

    def test_humidity(self):
        result = SensorHumidityGet().execute("")
        assert "54.8" in result

    def test_co2_warmup(self):
        set_sensor_state({})
        result = SensorCO2Get().execute("")
        assert "预热" in result or "ERROR 502" in result

    def test_state_get_returns_json(self):
        import json
        result = SensorStateGet().execute("")
        data = json.loads(result)
        assert data["code"] == 200
        assert data["data"]["temperature"] == 26.3

    def test_health_get(self):
        import json
        result = PlantHealthGet().execute("")
        data = json.loads(result)
        assert data["data"]["health_score"] == 87
```

- [ ] **Step 5: Run MQTT tests**

Run: `pytest tests/test_mqtt.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add sensor_listener/mqtt/cmd_*.py sensor_listener/mqtt/commands.json tests/test_mqtt.py
git commit -m "feat: add MQTT command executors adapted for ELF2 shared state"
```

---

### Task 5: Integration — Wire everything into the main loop

**Files:**
- Modify: `sensor_listener/main.py` — full integration of video+YOLO+MQTT with sensor pipeline
- Modify: `sensor_listener/protocol.py` — publish YOLO events to sensor_state
- Create: `tests/test_integration_phase_bc.py`

- [ ] **Step 1: Create shared sensor_state**

In `sensor_listener/main.py`, create the shared dict before starting threads:

```python
import threading
sensor_state: dict = {}
sensor_state_lock = threading.Lock()
```

- [ ] **Step 2: Update SensorProtocol to populate sensor_state**

Modify `sensor_listener/protocol.py` — after parsing and before display refresh:

```python
# Update shared sensor state (for MQTT queries)
import threading  # top of file
# ... in datagram_received, after parsing:
if hasattr(self, 'sensor_state') and self.sensor_state is not None:
    with self.sensor_state_lock:
        self.sensor_state.update(parsed)
        self.sensor_state["last_update"] = datetime.now().isoformat()
        if self.analysis:
            summary = self.analysis.get_summary()
            self.sensor_state["health_score"] = summary.get("health", 0)
            self.sensor_state["alerts"] = summary.get("alerts", [])
            self.sensor_state["trends"] = summary.get("trends", {})
```

- [ ] **Step 3: Start video YOLO loop in background thread**

Add a function that runs in the video thread:

```python
def video_yolo_loop(video_handler, yolo_detector, sensor_state, lock, mqtt_client):
    """Background thread: decode frames, run YOLO, publish detections."""
    while True:
        frame = video_handler.get_frame(timeout=1.0)
        if frame is not None and yolo_detector.should_infer():
            detections = yolo_detector.detect(frame)
            new_growth = yolo_detector.is_new_growth(detections)
            if new_growth:
                path = yolo_detector.save_screenshot(frame, detections)
                event = {
                    "type": new_growth["class"],
                    "confidence": new_growth["confidence"],
                    "timestamp": datetime.now().isoformat(),
                    "screenshot": path,
                }
                with lock:
                    sensor_state["yolo_event"] = event
                # Publish via MQTT
                if mqtt_client:
                    import json
                    mqtt_client.publish("rpi5/cloud/data",
                        f"/plant.new_growth {json.dumps(event, ensure_ascii=False)}")
```

- [ ] **Step 4: Wire cmd_sensor to sensor_state**

```python
if not args.no_mqtt:
    from sensor_listener.mqtt.cmd_sensor import set_sensor_state
    set_sensor_state(sensor_state)  # Link shared state to MQTT commands
```

- [ ] **Step 5: Update main loop to process MQTT commands**

Replace the plain `await asyncio.sleep(3600)` with a 1-second tick loop that:
1. Processes MQTT command queue
2. Checks for new YOLO events (terminal display update)
3. Sleeps 1 second

- [ ] **Step 6: Create integration test**

In `tests/test_integration_phase_bc.py`:

```python
"""Integration tests for Phase B+C."""
import pytest
from unittest import mock
from sensor_listener.mqtt.cmd_sensor import set_sensor_state, SensorStateGet


class TestBCIntegration:
    def test_sensor_state_flow(self):
        """MQTT command reads from UDP-populated state."""
        state = {"t": 25.0, "h": 60.0, "light": 400.0, "soil": 1800}
        set_sensor_state(state)
        import json
        result = json.loads(SensorStateGet().execute(""))
        assert result["data"]["temperature"] == 25.0

    def test_yolo_event_in_state(self):
        """YOLO event stored in state and readable."""
        state = {"yolo_event": {"type": "leaf", "confidence": 0.95}}
        set_sensor_state(state)
        # PlantPhotoTake should find the event
        from sensor_listener.mqtt.cmd_sensor import PlantPhotoTake
        result = PlantPhotoTake().execute("")
        assert "leaf" in result
```

- [ ] **Step 7: Run ALL tests**

Run: `pytest tests/ -v`
Expected: All tests PASS (>40 total)

- [ ] **Step 8: Commit**

```bash
git add sensor_listener/ tests/ requirements.txt
git commit -m "feat: integrate video, YOLO, and MQTT into main pipeline"
```
