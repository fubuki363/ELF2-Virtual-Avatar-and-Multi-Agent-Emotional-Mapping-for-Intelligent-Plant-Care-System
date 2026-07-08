# Phase A: Core Refactoring + Intelligent Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor single-file UDP listener into a multi-module package and add intelligent analysis, auto-control, and LLM advisory.

**Architecture:** 7-module package (`sensor_listener/`). Existing 437-line `udp_sensor_listener.py` split into `display.py`, `protocol.py`, `main.py`. New modules `analysis.py`, `control.py`, `llm_advisor.py`. All wired through `main.py`.

**Tech Stack:** Python 3.10+, asyncio, standard library + openai SDK (DeepSeek compatible)

## Global Constraints

- Python 3.10+ (match ELF2 environment: Python 3.10.12)
- All new modules are pure Python, no C extensions
- Existing `udp_sensor_listener.py` and `test_udp_sensor_listener.py` will be replaced by the package
- 37 existing tests must be adapted to work with new package structure
- Display format unchanged unless specified
- ANSI color rules unchanged: dim gray (null/missing), yellow (warning), red (error), cyan (LLM action), green (plant detection)
- Single-line ANSI refresh extended to multi-line (5 lines: sensor, analysis, divider, control status, events)
- `--no-color` disables all ANSI
- DeepSeek API: 通过环境变量 `DEEPSEEK_API_KEY` 配置，model `deepseek-chat`, timeout 3s
- K230 control via UDP:8260, JSON array format `[{"d":"fan","v":80}]`
- K230 IP learned from incoming UDP packet source address

---

### Task 1: Package Scaffold + Extract display.py

**Files:**
- Create: `sensor_listener/__init__.py`
- Create: `sensor_listener/display.py`
- Modify: `test_udp_sensor_listener.py` → rename tests, update imports

**Interfaces:**
- Produces: `from sensor_listener.display import CsvWriter, DisplayManager, format_display_line, format_verbose_line`
- All classes and functions keep identical signatures to existing code
- ANSI constants (`DIM`, `YELLOW`, `RED`, `RESET`) move to `display.py`

- [ ] **Step 1: Create package directory and __init__.py**

```bash
mkdir -p sensor_listener
```

In `sensor_listener/__init__.py`:
```python
# sensor_listener — Smart Greenhouse Controller
```

- [ ] **Step 2: Extract display.py**

Copy from `udp_sensor_listener.py` lines 1-305 (everything before `SensorProtocol`) into `sensor_listener/display.py`.

Remove the module-level docstring from the top, replace with:
```python
"""Terminal display, CSV logging, and sensor data formatting."""
```

Keep exactly: imports (csv, pathlib, sys, datetime), CsvWriter class, MAX_PACKET_SIZE, PACKET_LOSS_THRESHOLD_MS, parse_sensor_data, detect_packet_loss, ANSI constants, format_verbose_line, format_display_line, DisplayManager.

Wait — parse_sensor_data and detect_packet_loss go to protocol.py in Task 2. For now, leave them in display.py and we'll move them in Task 2.

- [ ] **Step 3: Update test imports**

In `test_udp_sensor_listener.py`, update all imports from `udp_sensor_listener` to `sensor_listener.display`:

```python
from sensor_listener.display import (
    CsvWriter,
    parse_sensor_data,
    detect_packet_loss,
    format_display_line,
    format_verbose_line,
    DisplayManager,
)
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest test_udp_sensor_listener.py -v`
Expected: All 37 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sensor_listener/ test_udp_sensor_listener.py
git commit -m "refactor: extract display.py from udp_sensor_listener"
```

---

### Task 2: Extract protocol.py + Create main.py

**Files:**
- Create: `sensor_listener/protocol.py`
- Create: `sensor_listener/main.py`
- Modify: `sensor_listener/display.py` — remove SensorProtocol, main(), parse_sensor_data, detect_packet_loss
- Modify: `test_udp_sensor_listener.py` — update imports for moved functions
- Delete: `udp_sensor_listener.py` (after verifying everything works)

**Interfaces:**
- Produces: `from sensor_listener.protocol import SensorProtocol, parse_sensor_data, detect_packet_loss, MAX_PACKET_SIZE, PACKET_LOSS_THRESHOLD_MS`
- Produces: `from sensor_listener.main import main` (async entry point)
- Consumes from Task 1: `from sensor_listener.display import CsvWriter, DisplayManager`

- [ ] **Step 1: Move parse_sensor_data + detect_packet_loss + MAX_PACKET_SIZE + PACKET_LOSS_THRESHOLD_MS to protocol.py**

In `sensor_listener/protocol.py`:
```python
"""UDP sensor protocol — JSON parsing, packet loss detection, and asyncio listener."""
import json
import sys
import asyncio

MAX_PACKET_SIZE = 4096
PACKET_LOSS_THRESHOLD_MS = 2000


def parse_sensor_data(raw_data: bytes) -> dict | None:
    """Parse a JSON UDP packet into a sensor data dict.
    Returns None for empty/oversized/malformed packets.
    Missing keys are absent from the returned dict.
    JSON null values become Python None.
    """
    if not raw_data or len(raw_data) > MAX_PACKET_SIZE:
        return None
    try:
        return json.loads(raw_data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def detect_packet_loss(current_ts: int | None, previous_ts: int | None) -> bool:
    """Return True if the gap between two timestamps indicates a dropped packet."""
    if current_ts is None or previous_ts is None:
        return False
    return (current_ts - previous_ts) > PACKET_LOSS_THRESHOLD_MS
```

Remove these from `sensor_listener/display.py`.

- [ ] **Step 2: Move SensorProtocol to protocol.py**

Append to `sensor_listener/protocol.py`:

```python
class SensorProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol that parses ESP32/K230 sensor JSON and drives display + CSV."""

    def __init__(self, display, csv_writer):
        from sensor_listener.display import DisplayManager
        self.display: DisplayManager = display
        self.csv_writer = csv_writer
        self.total_packets: int = 0
        self.drop_count: int = 0
        self.error_count: int = 0
        self._last_ts: int | None = None

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if not data or len(data) > MAX_PACKET_SIZE:
            return

        parsed = parse_sensor_data(data)

        if parsed is None:
            self.error_count += 1
            preview = data[:80].decode("utf-8", errors="replace")
            sys.stdout.write(f"\r\033[K\033[31m[ERROR] JSON 解析失败: {preview!r}\033[0m\n")
            sys.stdout.flush()
            return

        self.total_packets += 1

        current_ts = parsed.get("ts")
        if detect_packet_loss(current_ts, self._last_ts):
            self.drop_count += 1
        self._last_ts = current_ts

        self.display.refresh(
            parsed,
            drop_count=self.drop_count,
            error_count=self.error_count,
            addr=addr,
            byte_count=len(data),
        )
        self.csv_writer.write_row(parsed, drop_count=self.drop_count, error_count=self.error_count)

    def error_received(self, exc: Exception) -> None:
        sys.stderr.write(f"[WARN] UDP 传输错误: {exc}\n")
```

Remove `SensorProtocol` from `sensor_listener/display.py`.

- [ ] **Step 3: Create main.py**

```python
"""CLI entry point and asyncio startup for the smart greenhouse controller."""
import argparse
import asyncio
import sys

from sensor_listener.display import CsvWriter, DisplayManager
from sensor_listener.protocol import SensorProtocol


async def main() -> None:
    parser = argparse.ArgumentParser(description="ESP32-C3 UDP 传感器数据监听器")
    parser.add_argument("--port", type=int, default=8259, help="UDP 监听端口 (默认: 8259)")
    parser.add_argument("--bind", type=str, default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--log-dir", type=str, default="./sensor_logs", help="CSV 存储目录")
    parser.add_argument("--retention-days", type=int, default=60, help="CSV 保留天数 (默认: 60)")
    parser.add_argument("--no-color", action="store_true", help="关闭 ANSI 颜色")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示来源 IP 和字节数")
    args = parser.parse_args()

    use_color = not args.no_color

    display = DisplayManager(verbose=args.verbose, use_color=use_color)
    csv_writer = CsvWriter(log_dir=args.log_dir, retention_days=args.retention_days)
    csv_writer.cleanup_old_files()
    display.show_waiting(args.bind, args.port)

    loop = asyncio.get_running_loop()
    transport = None
    protocol = None
    start_time = None

    async def shutdown() -> None:
        nonlocal transport, protocol
        if transport:
            transport.close()
        csv_writer.close()

        elapsed = loop.time() - start_time if start_time else 0.0
        display.show_shutdown(
            runtime_seconds=elapsed,
            total_packets=protocol.total_packets if protocol else 0,
            drop_count=protocol.drop_count if protocol else 0,
            error_count=protocol.error_count if protocol else 0,
            csv_bytes=csv_writer.total_bytes_written,
        )

    try:
        protocol = SensorProtocol(display=display, csv_writer=csv_writer)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=(args.bind, args.port),
        )
        start_time = loop.time()

        while True:
            await asyncio.sleep(3600)

    except asyncio.CancelledError:
        pass
    except OSError as e:
        print(f"无法绑定 {args.bind}:{args.port}: {e}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        await shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 4: Update display.py — remove main() and __main__ block**

Remove the `async def main()` function and the `if __name__ == "__main__":` block from `sensor_listener/display.py`.

- [ ] **Step 5: Update test imports for moved functions**

In `test_udp_sensor_listener.py`, update imports:
```python
from sensor_listener.display import CsvWriter, DisplayManager, format_display_line, format_verbose_line
from sensor_listener.protocol import SensorProtocol, parse_sensor_data, detect_packet_loss
```

- [ ] **Step 6: Run all tests**

Run: `pytest test_udp_sensor_listener.py -v`
Expected: All 37 tests PASS

- [ ] **Step 7: Verify the new entry point works**

```bash
timeout 3 python -m sensor_listener.main --port 8259 2>&1 || true
```
Expected: "监听 0.0.0.0:8259，等待数据..." then timeout

- [ ] **Step 8: Delete old file and commit**

```bash
rm udp_sensor_listener.py
git add sensor_listener/ test_udp_sensor_listener.py
git rm udp_sensor_listener.py
git commit -m "refactor: extract protocol.py and main.py, remove old single file"
```

---

### Task 3: AnalysisEngine — Health Score + Trend Detection

**Files:**
- Create: `sensor_listener/analysis.py`
- Create: `tests/test_analysis.py`

**Interfaces:**
- Produces: `class AnalysisEngine` with methods:
  - `feed(data: dict) -> None` — ingest one sensor reading
  - `health_score(data: dict) -> int` — compute 0-100 plant health score
  - `trends() -> dict[str, float]` — per-sensor rate of change over 300s window
  - `get_summary() -> dict` — returns `{"health": int, "trends": dict, "alerts": list[str]}`

- [ ] **Step 1: Write failing tests for health_score and trend detection**

In `tests/test_analysis.py`:

```python
"""Tests for AnalysisEngine."""
import pytest
from sensor_listener.analysis import AnalysisEngine


def make_data(**overrides):
    defaults = {"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1000}
    defaults.update(overrides)
    return defaults


class TestHealthScore:
    def test_perfect_score(self):
        engine = AnalysisEngine()
        data = make_data(t=23.0, h=65.0, light=500, soil=1750)
        score = engine.health_score(data)
        assert score >= 90  # All in ideal range

    def test_poor_score(self):
        engine = AnalysisEngine()
        data = make_data(t=45.0, h=10.0, light=0, soil=4000)
        score = engine.health_score(data)
        assert score < 40

    def test_null_fields_excluded(self):
        engine = AnalysisEngine()
        data = make_data(t=None, h=None)
        data.pop("eco2", None)
        data.pop("tvoc", None)
        score = engine.health_score(data)
        assert 0 <= score <= 100  # Should not crash


class TestTrendDetection:
    def test_rising_temperature(self):
        engine = AnalysisEngine()
        # Feed 5 minutes of rising temperature
        for i in range(300):
            engine.feed(make_data(t=20.0 + i * 0.02, ts=i * 1000))
        trends = engine.trends()
        assert trends["t"] > 0  # Positive trend

    def test_stable_humidity(self):
        engine = AnalysisEngine()
        for i in range(300):
            engine.feed(make_data(h=55.0, ts=i * 1000))
        trends = engine.trends()
        assert abs(trends["h"]) < 0.5  # Near zero trend

    def test_trend_with_gaps(self):
        engine = AnalysisEngine()
        # Feed only 10 data points with gaps
        for i in range(10):
            engine.feed(make_data(ts=i * 5000))
        trends = engine.trends()
        assert isinstance(trends, dict)  # Should handle sparse data

    def test_get_summary(self):
        engine = AnalysisEngine()
        engine.feed(make_data())
        summary = engine.get_summary()
        assert "health" in summary
        assert "trends" in summary
        assert "alerts" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sensor_listener.analysis'`

- [ ] **Step 3: Write AnalysisEngine (health_score + trends)**

In `sensor_listener/analysis.py`:

```python
"""Plant health analysis — health score, trend detection, adaptive baseline, event logging."""
from collections import deque
from datetime import datetime


class AnalysisEngine:
    """Computes plant health metrics from sensor data streams."""

    # Ideal ranges: (min, optimal, max)
    IDEAL = {
        "t": (18, 23, 28),        # °C
        "h": (50, 65, 80),        # %
        "light": (200, 500, 800), # lux
        "soil": (1000, 1750, 2500), # raw ADC
    }

    TREND_WINDOW = 300  # seconds of sliding window for trend detection

    def __init__(self):
        self._window: deque[tuple[float, dict]] = deque()  # (timestamp, data)
        self._scores: deque[int] = deque(maxlen=100)

    def health_score(self, data: dict) -> int:
        """Compute plant health score 0-100 from sensor data. Each sensor contributes up to 25 points."""
        total = 0
        count = 0

        for key, (lo, opt, hi) in self.IDEAL.items():
            val = data.get(key)
            if val is None:
                continue
            count += 1
            # Score decreases linearly with distance from optimal
            if lo <= val <= hi:
                dist = abs(val - opt)
                span = (hi - lo) / 2
                score = max(0, 25 - (dist / span) * 25)
            elif val < lo:
                score = max(0, 25 - ((lo - val) / lo) * 50)
            else:
                score = max(0, 25 - ((val - hi) / hi) * 50)
            total += score

        if count == 0:
            return 0
        # Scale to 100
        return min(100, int((total / (count * 25)) * 100))

    def feed(self, data: dict) -> None:
        """Ingest one sensor reading for trend analysis."""
        now = datetime.now().timestamp()
        self._window.append((now, dict(data)))

        # Purge old entries beyond TREND_WINDOW
        cutoff = now - self.TREND_WINDOW
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

        score = self.health_score(data)
        self._scores.append(score)

    def trends(self) -> dict[str, float]:
        """Return per-sensor rate of change over the window (units/second)."""
        if len(self._window) < 2:
            return {}

        first_ts, first_data = self._window[0]
        last_ts, last_data = self._window[-1]
        dt = last_ts - first_ts
        if dt <= 0:
            return {}

        trends = {}
        for key in ["t", "h", "light", "soil", "gas"]:
            v1 = first_data.get(key)
            v2 = last_data.get(key)
            if v1 is not None and v2 is not None:
                trends[key] = (v2 - v1) / dt
        return trends

    def get_summary(self) -> dict:
        """Return analysis summary: health score, trends, and alerts."""
        current_score = self._scores[-1] if self._scores else 0
        trend_data = self.trends()
        alerts = []

        # Health-based alerts
        if current_score < 40:
            alerts.append("🔴 植物健康严重恶化")
        elif current_score < 60:
            alerts.append("🟡 植物健康偏低，请注意")

        # Trend-based alerts
        t_rate = trend_data.get("t", 0) * 300  # scale to per-5min
        if t_rate > 3:
            alerts.append(f"🌡 温度快速上升 +{t_rate:.1f}°C/5min")
        elif t_rate < -3:
            alerts.append(f"🌡 温度快速下降 {t_rate:.1f}°C/5min")

        soil_rate = trend_data.get("soil", 0) * 300
        if soil_rate > 200:
            alerts.append("🏜 土壤正在快速变干")

        return {
            "health": current_score,
            "trends": {k: v * 300 for k, v in trend_data.items()},  # per-5min rates
            "alerts": alerts,
        }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_analysis.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sensor_listener/analysis.py tests/test_analysis.py
git commit -m "feat: add AnalysisEngine with health score and trend detection"
```

---

### Task 4: AdaptiveBaseline + DecisionLogger

**Files:**
- Modify: `sensor_listener/analysis.py` — add AdaptiveBaseline and DecisionLogger
- Modify: `tests/test_analysis.py` — add tests

**Interfaces:**
- Produces: `class AdaptiveBaseline` — learn normal sensor ranges, detect anomalies
- Produces: `class DecisionLogger` — ring buffer of control decisions, flush to JSON

- [ ] **Step 1: Write failing tests**

Append to `tests/test_analysis.py`:

```python
import json
from sensor_listener.analysis import AdaptiveBaseline, DecisionLogger


class TestAdaptiveBaseline:
    def test_baseline_initial_empty(self):
        base = AdaptiveBaseline(window_hours=24)
        result = base.check({"t": 26.3})
        assert result["t"]["status"] == "unknown"  # Not enough data yet

    def test_baseline_detects_anomaly(self):
        base = AdaptiveBaseline(window_hours=24)
        # Feed "normal" data
        for _ in range(100):
            base.feed(make_data(t=24.0, h=60.0, soil=1800))
        result = base.check(make_data(t=35.0, h=60.0, soil=1800))
        assert result["t"]["status"] == "anomaly"

    def test_baseline_normal(self):
        base = AdaptiveBaseline(window_hours=24)
        for _ in range(100):
            base.feed(make_data(t=24.0, h=60.0, soil=1800))
        result = base.check(make_data(t=24.5, h=59.0, soil=1780))
        assert result["t"]["status"] == "normal"


class TestDecisionLogger:
    def test_log_and_flush(self, tmp_path):
        logger = DecisionLogger(max_entries=10, flush_path=str(tmp_path / "decisions.json"))
        logger.log("开风扇 80%", "温度 31.2°C > 阈值 30°C")
        logger.log("开水泵 30%", "土壤 3100 > 阈值 2500, LLM确认")

        entries = logger.get_recent(5)
        assert len(entries) == 2
        assert "风扇" in entries[0]["action"]

        logger.flush()
        saved = json.loads((tmp_path / "decisions.json").read_text())
        assert len(saved) == 2

    def test_ring_buffer_wraps(self, tmp_path):
        logger = DecisionLogger(max_entries=3, flush_path=str(tmp_path / "decisions.json"))
        for i in range(5):
            logger.log(f"action_{i}", f"trigger_{i}")
        entries = logger.get_recent(10)
        assert len(entries) == 3
        assert entries[0]["action"] == "action_2"  # Oldest kept
        assert entries[-1]["action"] == "action_4"  # Newest
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/test_analysis.py::TestAdaptiveBaseline tests/test_analysis.py::TestDecisionLogger -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write AdaptiveBaseline**

Append to `sensor_listener/analysis.py`:

```python
import json as _json
from collections import defaultdict
from pathlib import Path


class AdaptiveBaseline:
    """Learn normal sensor ranges over a time window and detect anomalies."""

    def __init__(self, window_hours: int = 24):
        self._window_hours = window_hours
        self._history: deque[tuple[float, dict]] = deque()
        self._min_samples = 30

    def feed(self, data: dict) -> None:
        """Ingest a reading for baseline learning."""
        now = datetime.now().timestamp()
        self._history.append((now, {k: v for k, v in data.items() if v is not None}))
        cutoff = now - self._window_hours * 3600
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def check(self, data: dict) -> dict[str, dict]:
        """Compare current values against learned baseline. Returns per-key status."""
        if len(self._history) < self._min_samples:
            return {k: {"status": "unknown", "value": v} for k, v in data.items() if v is not None}

        # Compute mean and std for each key from history
        stats = defaultdict(list)
        for _, hist_data in self._history:
            for k, v in hist_data.items():
                stats[k].append(v)

        baselines = {}
        for k, values in stats.items():
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            std = variance ** 0.5 if variance > 0 else 0.01

            current = data.get(k)
            if current is None:
                baselines[k] = {"status": "unknown", "value": None}
            elif abs(current - mean) > 2 * std:
                baselines[k] = {
                    "status": "anomaly",
                    "value": current,
                    "mean": round(mean, 1),
                    "std": round(std, 1),
                }
            else:
                baselines[k] = {
                    "status": "normal",
                    "value": current,
                    "mean": round(mean, 1),
                    "std": round(std, 1),
                }
        return baselines


class DecisionLogger:
    """Ring buffer of control decisions, flushable to JSON file."""

    def __init__(self, max_entries: int = 100, flush_path: str | None = None):
        self._entries: deque[dict] = deque(maxlen=max_entries)
        self._flush_path = Path(flush_path) if flush_path else None

    def log(self, action: str, trigger: str) -> None:
        """Record a control decision."""
        self._entries.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "trigger": trigger,
        })

    def get_recent(self, n: int = 10) -> list[dict]:
        """Get most recent N entries."""
        entries = list(self._entries)
        return entries[-n:] if n < len(entries) else entries

    def flush(self) -> None:
        """Write all entries to JSON file."""
        if self._flush_path:
            self._flush_path.parent.mkdir(parents=True, exist_ok=True)
            self._flush_path.write_text(_json.dumps(list(self._entries), ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run all analysis tests**

Run: `pytest tests/test_analysis.py -v`
Expected: All 11 tests PASS (6 from Task 3 + 5 new)

- [ ] **Step 5: Commit**

```bash
git add sensor_listener/analysis.py tests/test_analysis.py
git commit -m "feat: add AdaptiveBaseline and DecisionLogger to AnalysisEngine"
```

---

### Task 5: ControlEngine

**Files:**
- Create: `sensor_listener/control.py`
- Create: `tests/test_control.py`

**Interfaces:**
- Produces: `class ControlEngine` with:
  - `__init__(self, k230_addr: tuple[str, int] | None = None)`
  - `update_k230_addr(self, addr: tuple[str, int]) -> None` — learned from incoming UDP
  - `evaluate(self, data: dict, analysis_summary: dict) -> list[dict]` — returns list of command dicts to send
  - `set_llm_override(self, commands: list[dict]) -> None` — LLM advisor injects decisions
  - `get_status(self) -> dict` — current device states for display

- [ ] **Step 1: Write failing tests**

In `tests/test_control.py`:

```python
"""Tests for ControlEngine."""
from sensor_listener.control import ControlEngine


def make_data(**overrides):
    defaults = {"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1000}
    defaults.update(overrides)
    return defaults


class TestControlEngine:
    def test_no_commands_when_normal(self):
        engine = ControlEngine()
        cmds = engine.evaluate(make_data(), {"health": 90, "trends": {}, "alerts": []})
        assert cmds == []  # Nothing to do when everything is fine

    def test_overheat_triggers_fan(self):
        engine = ControlEngine()
        engine.update_k230_addr(("192.168.1.100", 8260))
        cmds = engine.evaluate(make_data(t=32.0), {"health": 50, "trends": {}, "alerts": []})
        assert any(c["d"] == "fan" for c in cmds)
        fan_cmd = [c for c in cmds if c["d"] == "fan"][0]
        assert fan_cmd["v"] > 0

    def test_dry_soil_triggers_pump(self):
        engine = ControlEngine()
        cmds = engine.evaluate(make_data(soil=3000), {"health": 60, "trends": {}, "alerts": []})
        assert any(c["d"] == "pump" for c in cmds)

    def test_dim_light_triggers_led(self):
        engine = ControlEngine()
        cmds = engine.evaluate(make_data(light=30), {"health": 70, "trends": {}, "alerts": []})
        assert any(c["d"] == "led" for c in cmds)

    def test_low_humidity_triggers_humidifier(self):
        engine = ControlEngine()
        cmds = engine.evaluate(make_data(h=40), {"health": 65, "trends": {}, "alerts": []})
        assert any(c["d"] == "humidifier" for c in cmds)

    def test_anti_flutter_prevents_rapid_toggle(self):
        engine = ControlEngine()
        engine.update_k230_addr(("192.168.1.100", 8260))
        # First call triggers fan
        cmds1 = engine.evaluate(make_data(t=32.0), {"health": 50, "trends": {}, "alerts": []})
        assert len(cmds1) > 0
        # Immediate second call should be suppressed
        cmds2 = engine.evaluate(make_data(t=32.0), {"health": 50, "trends": {}, "alerts": []})
        assert cmds2 == []  # Anti-flutter suppression

    def test_p0_emergency_no_anti_flutter(self):
        engine = ControlEngine()
        engine.update_k230_addr(("192.168.1.100", 8260))
        cmds1 = engine.evaluate(make_data(t=36.0), {"health": 20, "trends": {}, "alerts": ["critical"]})
        assert any(c["d"] == "fan" and c["v"] == 100 for c in cmds1)
        # P0 should fire every time, no anti-flutter
        cmds2 = engine.evaluate(make_data(t=36.0), {"health": 20, "trends": {}, "alerts": ["critical"]})
        assert any(c["d"] == "fan" and c["v"] == 100 for c in cmds2)

    def test_llm_override_sets_commands(self):
        engine = ControlEngine()
        engine.set_llm_override([{"d": "fan", "v": 60}, {"d": "led", "mode": "effect", "effect": "rainbow", "brightness": 128}])
        cmds = engine.evaluate(make_data(), {"health": 80, "trends": {}, "alerts": []})
        assert len(cmds) == 2

    def test_get_status(self):
        engine = ControlEngine()
        engine.update_k230_addr(("192.168.1.100", 8260))
        engine.evaluate(make_data(t=32.0), {"health": 50, "trends": {}, "alerts": []})
        status = engine.get_status()
        assert "fan" in status
        assert status["fan"] > 0

    def test_safety_limits(self):
        engine = ControlEngine()
        engine.set_llm_override([
            {"d": "pump", "v": 100},     # LLM tried to set pump to 100%
            {"d": "heater", "v": 100},    # LLM tried to set heater to 100%
            {"d": "humidifier", "v": 100}, # LLM tried to set humidifier to 100%
        ])
        cmds = engine.evaluate(make_data(), {"health": 80, "trends": {}, "alerts": []})
        pump_cmd = [c for c in cmds if c["d"] == "pump"][0]
        assert pump_cmd["v"] <= 50   # Pump capped at 50%
        heater_cmd = [c for c in cmds if c["d"] == "heater"][0]
        assert heater_cmd["v"] <= 80  # Heater capped at 80%
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/test_control.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write ControlEngine**

In `sensor_listener/control.py`:

```python
"""Auto-control engine — local rules + K230 UDP command dispatch."""
import time


# ── Safety limits (hard caps, LLM cannot override) ─────
SAFETY_LIMITS = {
    "pump": 50,
    "heater": 80,
    "humidifier": 80,
    "fan": 100,
    "led_brightness": 200,
}

# ── Local rules ─────────────────────────────────────────
# (condition_key, threshold, operator, device, value_fn)
LOCAL_RULES = [
    # Priority 0: safety
    {"key": "t", "threshold": 35, "op": ">", "device": "fan", "value": 100, "priority": 0,
     "reason": "过热保护: 温度 {val}°C > 35°C"},
    # Priority 1: high
    {"key": "t", "threshold": 30, "op": ">", "device": "fan", "value": lambda v: min(100, 50 + int((v - 30) * 10)),
     "priority": 1, "reason": "散热: 温度 {val}°C > 30°C"},
    {"key": "soil", "threshold": 2500, "op": ">", "device": "pump", "value": 30, "priority": 1,
     "reason": "土壤偏干: {val} > 2500"},
    # Priority 2: medium
    {"key": "light", "threshold": 50, "op": "<", "device": "led",
     "value": {"mode": "white", "brightness": 150}, "priority": 2,
     "reason": "补光: 光照 {val} lux < 50 lux"},
    {"key": "h", "threshold": 45, "op": "<", "device": "humidifier", "value": 50, "priority": 2,
     "reason": "空气偏干: 湿度 {val}% < 45%"},
    # Priority 3: low
    {"key": "soil", "threshold": 800, "op": "<", "device": "pump", "value": 0, "priority": 3,
     "reason": "土壤已湿: {val} < 800, 停止浇水"},
]

ANTI_FLUTTER_SECONDS = 30


class ControlEngine:
    """Evaluates sensor data against local rules, produces K230 UDP commands."""

    def __init__(self, k230_addr: tuple | None = None):
        self._k230_addr = k230_addr
        self._last_cmd_time: dict[str, float] = {}   # device → last command timestamp
        self._device_state: dict[str, object] = {}    # device → current value
        self._llm_override: list[dict] | None = None  # LLM-injected commands
        self._last_reasons: list[str] = []

    def update_k230_addr(self, addr: tuple) -> None:
        self._k230_addr = addr

    def set_llm_override(self, commands: list[dict]) -> None:
        """LLM advisor injects decision commands. Cleared after one evaluate() call."""
        self._llm_override = commands

    def evaluate(self, data: dict, analysis_summary: dict) -> list[dict]:
        """Evaluate sensor data and return list of K230 command dicts to send."""

        # If LLM override is active, use it (with safety filtering)
        if self._llm_override is not None:
            cmds = self._apply_safety(self._llm_override)
            self._llm_override = None
            self._last_reasons = ["LLM 建议"]
            for c in cmds:
                self._device_state[c.get("d", c.get("device", "unknown"))] = c.get("v", c.get("brightness", "?"))
                self._last_cmd_time[c.get("d", c.get("device", ""))] = time.time()
            return self._to_k230_format(cmds)

        commands = []
        reasons = []

        for rule in sorted(LOCAL_RULES, key=lambda r: r["priority"]):
            key = rule["key"]
            val = data.get(key)
            if val is None:
                continue

            threshold = rule["threshold"]
            triggered = False
            if rule["op"] == ">" and val > threshold:
                triggered = True
            elif rule["op"] == "<" and val < threshold:
                triggered = True

            if not triggered:
                continue

            # Anti-flutter check (skip for P0)
            if rule["priority"] > 0:
                last = self._last_cmd_time.get(rule["device"], 0)
                if time.time() - last < ANTI_FLUTTER_SECONDS:
                    continue

            # Compute value
            value = rule["value"]
            if callable(value):
                value = value(val)

            commands.append({"device": rule["device"], "value": value})
            reason = rule["reason"].format(val=val)
            reasons.append(reason)
            self._last_cmd_time[rule["device"]] = time.time()

        # Update state tracking
        for c in commands:
            dev = c["device"]
            val = c["value"]
            if isinstance(val, dict):
                self._device_state[dev] = val.get("brightness", val)
            else:
                self._device_state[dev] = val

        self._last_reasons = reasons
        return self._to_k230_format(commands)

    def _apply_safety(self, commands: list[dict]) -> list[dict]:
        """Apply hard safety limits to commands."""
        safe = []
        for c in commands:
            d = c.get("d", "")
            if d in SAFETY_LIMITS and "v" in c:
                c = dict(c)
                c["v"] = min(c["v"], SAFETY_LIMITS[d])
            # LED brightness cap
            if d == "led" and "brightness" in c:
                c = dict(c)
                c["brightness"] = min(c["brightness"], SAFETY_LIMITS["led_brightness"])
            safe.append(c)
        return safe

    def _to_k230_format(self, commands: list[dict]) -> list[dict]:
        """Convert internal commands to K230 JSON format."""
        result = []
        for c in commands:
            dev = c["device"]
            val = c["value"]
            if dev == "led" and isinstance(val, dict):
                result.append({"d": "led", **val})
            else:
                result.append({"d": dev, "v": val})
        return result

    def get_status(self) -> dict:
        """Return current device states for display."""
        return dict(self._device_state)

    def get_last_reasons(self) -> list[str]:
        return list(self._last_reasons)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_control.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sensor_listener/control.py tests/test_control.py
git commit -m "feat: add ControlEngine with local rules and K230 UDP dispatch"
```

---

### Task 6: LLMAdvisor

**Files:**
- Create: `sensor_listener/llm_advisor.py`
- Create: `tests/test_llm_advisor.py`

**Interfaces:**
- Produces: `class LLMAdvisor` with:
  - `__init__(self, api_key: str, model: str = "deepseek-chat")`
  - `async consult(self, trigger_reason: str, data_history: list[dict], analysis_summary: dict) -> LLMDecision | None`
  - `LLMDecision = namedtuple("LLMDecision", ["commands", "reason", "confidence"])`
  - Returns None on timeout/error (fallback)

- [ ] **Step 1: Write failing tests**

In `tests/test_llm_advisor.py`:

```python
"""Tests for LLMAdvisor."""
import pytest
from unittest import mock
from sensor_listener.llm_advisor import LLMAdvisor


def make_data(**overrides):
    defaults = {"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1000}
    defaults.update(overrides)
    return defaults


class TestLLMAdvisor:
    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        advisor = LLMAdvisor(api_key="test-key")
        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = TimeoutError()
            result = await advisor.consult(
                "soil > 2500",
                [make_data(soil=2600, ts=1000), make_data(soil=2700, ts=2000)],
                {"health": 60, "trends": {}, "alerts": []},
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_decision_on_success(self):
        advisor = LLMAdvisor(api_key="test-key")
        mock_response = mock.MagicMock()
        mock_response.choices = [
            mock.MagicMock(
                message=mock.MagicMock(
                    content='{"actions":[{"d":"fan","v":60},{"d":"pump","v":30}],"reason":"温度偏高且土壤偏干","confidence":0.85}'
                )
            )
        ]

        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create = mock.AsyncMock(return_value=mock_response)
            result = await advisor.consult(
                "温度上升",
                [make_data(t=31.0, ts=1000), make_data(t=32.0, ts=2000)],
                {"health": 55, "trends": {"t": 0.02}, "alerts": ["温度偏高"]},
            )

        assert result is not None
        assert len(result.commands) == 2
        assert result.reason == "温度偏高且土壤偏干"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_handles_malformed_json_response(self):
        advisor = LLMAdvisor(api_key="test-key")
        mock_response = mock.MagicMock()
        mock_response.choices = [mock.MagicMock(message=mock.MagicMock(content="not valid json"))]

        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create = mock.AsyncMock(return_value=mock_response)
            result = await advisor.consult("测试", [make_data()], {"health": 80, "trends": {}, "alerts": []})

        assert result is None  # Should fallback on parse error

    @pytest.mark.asyncio
    async def test_consecutive_failures_pause(self):
        advisor = LLMAdvisor(api_key="test-key", max_failures=3, pause_seconds=0.1)

        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = TimeoutError()

            # 3 failures
            for _ in range(3):
                result = await advisor.consult("test", [make_data()], {"health": 80, "trends": {}, "alerts": []})
                assert result is None

            # 4th should be paused
            result = await advisor.consult("test", [make_data()], {"health": 80, "trends": {}, "alerts": []})
            assert result is None  # Paused, not even called

    def test_trigger_condition_dry_soil(self):
        advisor = LLMAdvisor(api_key="test-key")
        history = [make_data(soil=s, ts=i*1000) for i, s in enumerate(range(2500, 2600))]
        # Soil > 2500 for more than 10 seconds
        assert advisor.should_consult("soil_dry", history) is True

    def test_trigger_condition_rapid_heat(self):
        advisor = LLMAdvisor(api_key="test-key")
        history = [make_data(t=25.0 + i*0.02, ts=i*1000) for i in range(300)]  # +6°C over 5 minutes
        assert advisor.should_consult("temp_rising", history) is True
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/test_llm_advisor.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Write LLMAdvisor**

In `sensor_listener/llm_advisor.py`:

```python
"""LLM advisor — DeepSeek API integration for intelligent greenhouse decisions."""
import asyncio
import json
import time
from collections import namedtuple

LLMDecision = namedtuple("LLMDecision", ["commands", "reason", "confidence"])

SYSTEM_PROMPT = """你是一个智能温室控制器。根据传感器数据给出设备调节建议。

可用设备:
- fan(0-100): 散热风扇，占空比百分比
- heater(0-100): 加热片，占空比百分比
- pump(0-100): 水泵/浇水，占空比百分比
- humidifier(0-100): 加湿器，占空比百分比
- led(mode:"effect"|"white", effect:"rainbow"|"breathing"|"off", brightness:0-255): LED灯带

规则:
- 温度 18-28°C 理想，>30°C 开风扇，<18°C 开加热
- 土壤湿度 1000-2500 (ADC, 越低越湿)，>2500 考虑浇水
- 光照 <50 lux 时考虑补光
- 环境湿度 50-80% 理想
- 输出必须是 JSON: {"actions":[{"d":"fan","v":80}],"reason":"简短中文理由","confidence":0.0-1.0}
- 不确定时宁可保守，confidence 设低
- 只调整有问题的设备，正常的不要动"""


class LLMAdvisor:
    """Calls DeepSeek API on sensor threshold events for intelligent control decisions."""

    def __init__(self, api_key: str, model: str = "deepseek-chat",
                 max_failures: int = 3, pause_seconds: float = 300.0):
        self._api_key = api_key
        self._model = model
        self._max_failures = max_failures
        self._pause_seconds = pause_seconds
        self._failure_count = 0
        self._paused_until: float = 0.0
        self._client = None  # Lazy init

    def _ensure_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url="https://api.deepseek.com/v1",
            )
        return self._client

    def should_consult(self, trigger_type: str, data_history: list[dict]) -> bool:
        """Check if trigger conditions warrant LLM consultation."""
        if self._is_paused():
            return False
        if len(data_history) < 2:
            return False

        if trigger_type == "soil_dry":
            # Soil > 2500 for last 10 readings
            return all(d.get("soil", 0) > 2500 for d in data_history[-10:])
        elif trigger_type == "temp_rising":
            # Temperature rose > 3°C over the window
            if len(data_history) < 30:
                return False
            first_t = data_history[0].get("t")
            last_t = data_history[-1].get("t")
            if first_t is None or last_t is None:
                return False
            return (last_t - first_t) > 3.0
        elif trigger_type == "health_low":
            # Health score sustained below 60 — checked by AnalysisEngine
            return True
        return False

    async def consult(
        self, trigger_reason: str, data_history: list[dict], analysis_summary: dict
    ) -> LLMDecision | None:
        """Consult DeepSeek for control recommendations. Returns None on failure."""

        if self._is_paused():
            return None

        client = self._ensure_client()

        # Build user prompt from sensor history
        latest = data_history[-1] if data_history else {}
        history_text = "\n".join(
            f"t={d.get('t','?')}°C h={d.get('h','?')}% soil={d.get('soil','?')} "
            f"light={d.get('light','?')}lux eco2={d.get('eco2','?')}ppm"
            for d in data_history[-5:]  # Last 5 readings
        )

        user_prompt = f"""触发原因: {trigger_reason}

最近传感器数据:
{history_text}

分析摘要: 健康指数 {analysis_summary.get('health', '?')}/100
趋势: {analysis_summary.get('trends', {})}
告警: {analysis_summary.get('alerts', [])}

请给出设备调节建议（JSON格式）。"""

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=300,
                ),
                timeout=3.0,
            )

            content = response.choices[0].message.content
            # Extract JSON from response (may have markdown fences)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = json.loads(content)

            commands = result.get("actions", [])
            reason = result.get("reason", "LLM 建议")
            confidence = result.get("confidence", 0.5)

            self._failure_count = 0  # Reset on success
            return LLMDecision(commands=commands, reason=reason, confidence=confidence)

        except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
            self._failure_count += 1
            if self._failure_count >= self._max_failures:
                self._paused_until = time.time() + self._pause_seconds
                import sys
                print(f"[LLM] 连续失败 {self._failure_count} 次，暂停 {self._pause_seconds} 秒", file=sys.stderr)
            else:
                import sys
                print(f"[LLM] 调用失败 ({self._failure_count}/{self._max_failures}): {e}", file=sys.stderr)
            return None

    def _is_paused(self) -> bool:
        if self._paused_until > time.time():
            return True
        if self._paused_until > 0 and self._paused_until <= time.time():
            self._paused_until = 0.0
            self._failure_count = 0  # Resume
        return False
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_llm_advisor.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sensor_listener/llm_advisor.py tests/test_llm_advisor.py
git commit -m "feat: add LLMAdvisor with DeepSeek API integration"
```

---

### Task 7: Integration — Wire Everything in main.py

**Files:**
- Modify: `sensor_listener/main.py` — integrate AnalysisEngine, ControlEngine, LLMAdvisor
- Modify: `sensor_listener/display.py` — update DisplayManager.refresh() for multi-line display
- Modify: `sensor_listener/protocol.py` — hook control + analysis into datagram_received
- Create: `tests/test_integration.py`

**Interfaces This Task Wires Together:**
- SensorProtocol → AnalysisEngine.feed(data)
- SensorProtocol → ControlEngine.evaluate(data, summary)
- ControlEngine → commands sent via transport.sendto()
- LLM trigger checks in the main evaluation loop

- [ ] **Step 1: Write integration test**

In `tests/test_integration.py`:

```python
"""Integration tests for the full pipeline."""
import pytest
import tempfile
import pathlib
from unittest import mock
from sensor_listener.display import CsvWriter, DisplayManager
from sensor_listener.protocol import SensorProtocol
from sensor_listener.analysis import AnalysisEngine
from sensor_listener.control import ControlEngine


class TestFullPipeline:
    def test_sensor_to_analysis_to_control(self):
        """End-to-end: UDP data → analysis → control commands."""
        dm = DisplayManager(verbose=False, use_color=False)
        dm._first_data = False
        with tempfile.TemporaryDirectory() as d:
            csv_writer = CsvWriter(log_dir=d, retention_days=60)
            proto = SensorProtocol(display=dm, csv_writer=csv_writer)

            analysis = AnalysisEngine()
            control = ControlEngine()
            control.update_k230_addr(("192.168.1.100", 8260))

            # Simulate receiving a hot/dry packet
            raw = b'{"t":33.0,"h":40.0,"light":320,"soil":3000,"ts":1000}'
            proto.datagram_received(raw, ("192.168.1.100", 12345))

            # Run analysis
            parsed = {"t": 33.0, "h": 40.0, "light": 320, "soil": 3000, "ts": 1000}
            analysis.feed(parsed)
            summary = analysis.get_summary()

            # Run control
            cmds = control.evaluate(parsed, summary)

            # High temp + dry soil should trigger fan + pump
            devices = {c["d"] for c in cmds}
            assert "fan" in devices
            assert "pump" in devices

    def test_csv_still_works(self):
        """After all refactoring, CSV writing must still work."""
        dm = DisplayManager(verbose=False, use_color=False)
        dm._first_data = False
        with tempfile.TemporaryDirectory() as d:
            csv_writer = CsvWriter(log_dir=d, retention_days=60)
            proto = SensorProtocol(display=dm, csv_writer=csv_writer)

            raw = b'{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1000}'
            proto.datagram_received(raw, ("192.168.1.100", 12345))

            with open(csv_writer.current_file, "r") as f:
                import csv
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["t"] == "26.3"
```

- [ ] **Step 2: Run to verify fail or pass**

Run: `pytest tests/test_integration.py -v`
Expected: Tests PASS (interfaces already align from previous tasks)

- [ ] **Step 3: Update SensorProtocol to drive analysis + control**

Modify `sensor_listener/protocol.py` — add optional analysis and control hooks:

```python
class SensorProtocol(asyncio.DatagramProtocol):
    def __init__(self, display, csv_writer, analysis_engine=None, control_engine=None):
        self.display = display
        self.csv_writer = csv_writer
        self.analysis = analysis_engine
        self.control = control_engine
        self.total_packets: int = 0
        self.drop_count: int = 0
        self.error_count: int = 0
        self._last_ts: int | None = None
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        # ... (existing logic unchanged) ...

        # After display refresh + CSV write:

        # Drive analysis engine
        if self.analysis:
            self.analysis.feed(parsed)

        # Drive control engine
        if self.control:
            if not self.control._k230_addr:
                self.control.update_k230_addr((addr[0], 8260))
            summary = self.analysis.get_summary() if self.analysis else {}
            cmds = self.control.evaluate(parsed, summary)

            # Send commands via UDP
            if cmds and self._transport and self.control._k230_addr:
                import json
                cmd_bytes = json.dumps(cmds).encode("utf-8")
                self._transport.sendto(cmd_bytes, self.control._k230_addr)
```

- [ ] **Step 4: Update DisplayManager for multi-line output**

Modify `sensor_listener/display.py` — `DisplayManager.refresh()` accepts optional extra lines:

```python
def refresh(self, data, *, drop_count=0, error_count=0, addr=None, byte_count=0,
            analysis_summary=None, control_status=None, events=None):
    """Refresh the terminal display with sensor + analysis + control info."""
    # ... existing single/verbose line logic ...

    # Append extra lines if provided
    if analysis_summary:
        health = analysis_summary.get("health", 0)
        bar_len = 20
        filled = int(health / 100 * bar_len)
        bar = "█" * filled + "▏" * (bar_len - filled)
        health_label = "良好" if health >= 80 else "注意" if health >= 60 else "警告"
        sys.stdout.write(f"\n\033[K  健康指数: {health}  {bar}  {health_label}")

        trends = analysis_summary.get("trends", {})
        if trends:
            trend_parts = []
            for key, rate in trends.items():
                names = {"t": "温度", "h": "湿度", "light": "光照", "soil": "土壤"}
                arrow = "↗" if rate > 0.1 else "↘" if rate < -0.1 else "→"
                trend_parts.append(f"{names.get(key, key)} {arrow} {rate:+.1f}/5min")
            sys.stdout.write(f"\n\033[K  趋势: {'  '.join(trend_parts)}")

    if control_status:
        status_parts = []
        for dev, val in control_status.items():
            icons = {"fan": "⚡", "pump": "🌊", "led": "💡", "humidifier": "💧", "heater": "🔥"}
            icon = icons.get(dev, "•")
            if isinstance(val, dict):
                status_parts.append(f"{icon} {dev} {val.get('brightness', val)}")
            else:
                status_parts.append(f"{icon} {dev} {val}%")
        sys.stdout.write(f"\n\033[K───\n\033[K  {' │ '.join(status_parts)}")

    if events:
        for evt in events[-2:]:  # Show last 2 events
            sys.stdout.write(f"\n\033[K  {evt}")
```

- [ ] **Step 5: Update main.py to wire everything**

Modify `sensor_listener/main.py`:

```python
async def main() -> None:
    parser = argparse.ArgumentParser(description="智能温室控制器")
    # ... existing args ...
    parser.add_argument("--no-analysis", action="store_true", help="禁用分析引擎")
    parser.add_argument("--no-control", action="store_true", help="禁用自动控制")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM")
    parser.add_argument("--llm-api-key", type=str, default=os.environ.get("DEEPSEEK_API_KEY", ""),
    parser.add_argument("--k230-port", type=int, default=8260, help="K230 控制端口")
    args = parser.parse_args()

    # ... existing setup ...

    # Conditionally create engines
    analysis_engine = None
    control_engine = None
    llm_advisor = None

    if not args.no_analysis:
        from sensor_listener.analysis import AnalysisEngine
        analysis_engine = AnalysisEngine()

    if not args.no_control:
        from sensor_listener.control import ControlEngine
        control_engine = ControlEngine()
        if not args.no_llm:
            from sensor_listener.llm_advisor import LLMAdvisor
            llm_advisor = LLMAdvisor(api_key=args.llm_api_key)

    # ... create protocol with engines ...
    protocol = SensorProtocol(
        display=display, csv_writer=csv_writer,
        analysis_engine=analysis_engine,
        control_engine=control_engine,
    )
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/ -v`
Expected: All 64+ tests PASS

- [ ] **Step 7: Commit**

```bash
git add sensor_listener/ tests/
git commit -m "feat: integrate analysis, control, and LLM into main pipeline"
```
