# UDP Sensor Listener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python asyncio application that listens on UDP port 8259, parses JSON sensor data from ESP32-C3, displays readings in-terminal with ANSI refresh, and logs to daily CSV files with 60-day retention.

**Architecture:** Single-file asyncio app (~200 lines). `SensorProtocol` (DatagramProtocol subclass) receives UDP packets, parses JSON, updates shared state, then calls `DisplayManager.refresh()` and `CsvWriter.write_row()`. All three components share one event loop, no threads, no locks.

**Tech Stack:** Python 3, standard library only (asyncio, json, csv, argparse, datetime, pathlib, sys, signal)

## Global Constraints

- Python standard library only — no pip dependencies
- Single file: `udp_sensor_listener.py`
- Tests: `test_udp_sensor_listener.py`
- CSV directory: `./sensor_logs/`, 60-day retention, daily rotation
- UDP bind: `0.0.0.0:8259`
- ANSI color support, disable with `--no-color`
- CCS811 warmup: missing `eco2`/`tvoc` keys → display `预热`, CSV field empty
- null sensor values: display `--`, CSV field empty
- Packet loss: `ts` gap > 2000ms → yellow `⚠ 丢包 N`
- Ctrl+C: graceful shutdown with statistics summary
- Zero-byte and >4KB packets silently ignored

---

### Task 1: CsvWriter Class

**Files:**
- Create: `udp_sensor_listener.py`
- Create: `test_udp_sensor_listener.py`

**Interfaces:**
- Produces: `class CsvWriter` with:
  - `__init__(self, log_dir: str = "./sensor_logs", retention_days: int = 60)`
  - `write_row(self, data: dict, drop_count: int, error_count: int) -> None`
  - `cleanup_old_files(self) -> None`
  - `close(self) -> None`
  - Property: `current_file: pathlib.Path | None`
  - Property: `total_bytes_written: int`

- [ ] **Step 1: Write the failing test for CsvWriter**

In `test_udp_sensor_listener.py`:

```python
import csv
import json
import pathlib
import tempfile
import time
from datetime import datetime, timedelta
from unittest import mock

import pytest

from udp_sensor_listener import CsvWriter

# ── helpers ──────────────────────────────────────────────

@pytest.fixture
def tmp_log_dir():
    with tempfile.TemporaryDirectory() as d:
        yield pathlib.Path(d)


def make_data(**overrides):
    """Return a sensor data dict with defaults for all 7 fields."""
    defaults = {
        "t": 26.3, "h": 54.8, "light": 320.5,
        "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200,
        "ts": 1234567,
    }
    defaults.update(overrides)
    return defaults


# ── CsvWriter tests ──────────────────────────────────────

class TestCsvWriter:
    def test_creates_log_directory_on_first_write(self, tmp_log_dir):
        log_dir = tmp_log_dir / "sensor_logs"
        writer = CsvWriter(log_dir=str(log_dir), retention_days=60)

        writer.write_row(make_data(), drop_count=0, error_count=0)

        assert log_dir.exists()
        assert writer.current_file is not None

    def test_writes_csv_header_and_row(self, tmp_log_dir):
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=60)
        data = make_data()

        writer.write_row(data, drop_count=0, error_count=0)

        with open(writer.current_file, "r", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["t"] == "26.3"
        assert row["h"] == "54.8"
        assert row["light"] == "320.5"
        assert row["eco2"] == "450"
        assert row["tvoc"] == "12"
        assert row["gas"] == "0.85"
        assert row["soil"] == "2200"
        assert row["esp32_ts"] == "1234567"
        assert row["drop_count"] == "0"
        assert row["error_count"] == "0"
        assert "timestamp" in row  # ISO 8601

    def test_null_fields_written_as_empty(self, tmp_log_dir):
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=60)
        data = make_data(t=None, h=None)

        writer.write_row(data, drop_count=0, error_count=0)

        with open(writer.current_file, "r", newline="") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["t"] == ""
        assert row["h"] == ""

    def test_missing_eco2_tvoc_written_as_empty(self, tmp_log_dir):
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=60)
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        writer.write_row(data, drop_count=3, error_count=1)

        with open(writer.current_file, "r", newline="") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert row["eco2"] == ""
        assert row["tvoc"] == ""

    def test_rolls_over_at_midnight(self, tmp_log_dir):
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=60)

        # Write first row with a known date
        jan1 = datetime(2026, 1, 1, 23, 59, 0)
        with mock.patch("udp_sensor_listener.datetime.now") as mock_now:
            mock_now.return_value = jan1
            writer.write_row(make_data(), drop_count=0, error_count=0)

        file1 = writer.current_file
        assert "2026-01-01" in str(file1)

        # Write second row on the next day
        jan2 = datetime(2026, 1, 2, 0, 1, 0)
        with mock.patch("udp_sensor_listener.datetime.now") as mock_now:
            mock_now.return_value = jan2
            writer.write_row(make_data(), drop_count=0, error_count=0)

        file2 = writer.current_file
        assert "2026-01-02" in str(file2)
        assert file1 != file2

    def test_cleanup_removes_old_files(self, tmp_log_dir):
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=2)

        # Create files for dates 3, 2, and 1 days ago
        today = datetime(2026, 7, 8)
        old_dates = [
            today - timedelta(days=3),  # should be deleted
            today - timedelta(days=2),  # should be deleted (boundary)
            today - timedelta(days=1),  # should be kept
        ]
        for d in old_dates:
            f = tmp_log_dir / f"{d.strftime('%Y-%m-%d')}.csv"
            f.write_text("dummy")

        with mock.patch("udp_sensor_listener.datetime.now") as mock_now:
            mock_now.return_value = today
            writer.cleanup_old_files()

        remaining = sorted(tmp_log_dir.glob("*.csv"))
        assert len(remaining) == 1
        assert "2026-07-07" in str(remaining[0])

    def test_total_bytes_written_tracks_size(self, tmp_log_dir):
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=60)

        writer.write_row(make_data(), drop_count=0, error_count=0)
        first_size = writer.total_bytes_written
        assert first_size > 0

        writer.write_row(make_data(), drop_count=0, error_count=0)
        assert writer.total_bytes_written > first_size
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_udp_sensor_listener.py::TestCsvWriter -v`
Expected: All fail — `ModuleNotFoundError: No module named 'udp_sensor_listener'`

- [ ] **Step 3: Write minimal CsvWriter implementation**

In `udp_sensor_listener.py`:

```python
"""UDP sensor listener — receives ESP32-C3 JSON packets, displays in-terminal, logs to CSV."""
import csv
import pathlib
from datetime import datetime


class CsvWriter:
    """Writes sensor data rows to daily-rotated CSV files with retention cleanup."""

    CSV_HEADER = [
        "timestamp", "t", "h", "light", "eco2", "tvoc",
        "gas", "soil", "esp32_ts", "drop_count", "error_count",
    ]

    def __init__(self, log_dir: str = "./sensor_logs", retention_days: int = 60):
        self._log_dir = pathlib.Path(log_dir)
        self._retention_days = retention_days
        self._current_file: pathlib.Path | None = None
        self._current_date: str | None = None
        self._file_handle = None
        self._csv_writer = None
        self.total_bytes_written: int = 0

    def _get_filename(self) -> pathlib.Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._log_dir / f"{today}.csv"

    def _open_file(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        filename = self._get_filename()
        date_str = datetime.now().strftime("%Y-%m-%d")

        is_new = not filename.exists()
        self._file_handle = open(filename, "a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._file_handle)

        if is_new or filename.stat().st_size == 0:
            self._csv_writer.writerow(self.CSV_HEADER)
            self._file_handle.flush()

        self._current_file = filename
        self._current_date = date_str
        self.total_bytes_written = filename.stat().st_size

    def write_row(self, data: dict, drop_count: int, error_count: int) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._current_date != today or self._file_handle is None:
            if self._file_handle:
                self._file_handle.close()
            self._open_file()

        timestamp = datetime.now().isoformat()
        row = [
            timestamp,
            data.get("t", ""),
            data.get("h", ""),
            data.get("light", ""),
            data.get("eco2", ""),
            data.get("tvoc", ""),
            data.get("gas", ""),
            data.get("soil", ""),
            data.get("ts", ""),
            drop_count,
            error_count,
        ]
        self._csv_writer.writerow(row)
        self._file_handle.flush()
        self.total_bytes_written = self._current_file.stat().st_size

    def cleanup_old_files(self) -> None:
        if not self._log_dir.exists():
            return
        cutoff = datetime.now() - __import__("datetime").timedelta(days=self._retention_days - 1)
        for f in self._log_dir.glob("*.csv"):
            try:
                file_date = datetime.strptime(f.stem, "%Y-%m-%d")
                if file_date < cutoff:
                    f.unlink()
            except ValueError:
                pass  # skip files that don't match the naming pattern

    def close(self) -> None:
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_udp_sensor_listener.py::TestCsvWriter -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Fix the `timedelta` import**

In `udp_sensor_listener.py`, update the import section to:

```python
from datetime import datetime, timedelta
```

And in `cleanup_old_files`, change `__import__("datetime").timedelta(days=self._retention_days - 1)` to `timedelta(days=self._retention_days - 1)`.

Run tests again: `pytest test_udp_sensor_listener.py::TestCsvWriter -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add udp_sensor_listener.py test_udp_sensor_listener.py
git commit -m "feat: add CsvWriter with daily rotation and retention cleanup"
```

---

### Task 2: Field Parsing and Packet Loss Detection

**Files:**
- Modify: `udp_sensor_listener.py` — add `parse_sensor_data()` and `detect_packet_loss()`
- Modify: `test_udp_sensor_listener.py` — add tests

**Interfaces:**
- Consumes: nothing from Task 1
- Produces:
  - `parse_sensor_data(raw_data: bytes) -> dict | None` — returns parsed dict on success, None on failure
  - `Parsed dict keys: t, h, light, eco2, tvoc, gas, soil, ts`. Missing keys absent from dict. null JSON values become Python None in dict.
  - `detect_packet_loss(current_ts: int | None, previous_ts: int | None) -> bool` — True when gap > 2000ms

- [ ] **Step 1: Write failing tests for parse_sensor_data and detect_packet_loss**

Append to `test_udp_sensor_listener.py`:

```python
from udp_sensor_listener import parse_sensor_data, detect_packet_loss


class TestParseSensorData:
    def test_full_packet_all_fields(self):
        raw = b'{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1234567}'

        result = parse_sensor_data(raw)

        assert result is not None
        assert result["t"] == 26.3
        assert result["h"] == 54.8
        assert result["light"] == 320.5
        assert result["eco2"] == 450
        assert result["tvoc"] == 12
        assert result["gas"] == 0.85
        assert result["soil"] == 2200
        assert result["ts"] == 1234567

    def test_ccs811_warmup_missing_eco2_tvoc(self):
        raw = b'{"t":26.3,"h":54.8,"light":320.5,"gas":0.85,"soil":2200,"ts":1234567}'

        result = parse_sensor_data(raw)

        assert result is not None
        assert result["t"] == 26.3
        assert "eco2" not in result
        assert "tvoc" not in result

    def test_null_fields_preserved_as_none(self):
        raw = b'{"t":null,"h":null,"light":320.5,"gas":0.85,"soil":2200,"ts":1234567}'

        result = parse_sensor_data(raw)

        assert result is not None
        assert result["t"] is None
        assert result["h"] is None
        assert result["light"] == 320.5

    def test_malformed_json_returns_none(self):
        raw = b'not json at all'

        result = parse_sensor_data(raw)

        assert result is None

    def test_empty_packet_returns_none(self):
        result = parse_sensor_data(b"")
        assert result is None

    def test_oversized_packet_returns_none(self):
        result = parse_sensor_data(b"x" * 5000)
        assert result is None


class TestDetectPacketLoss:
    def test_normal_interval_no_loss(self):
        assert detect_packet_loss(current_ts=2000, previous_ts=1000) is False

    def test_gap_exceeds_threshold(self):
        assert detect_packet_loss(current_ts=4000, previous_ts=1000) is True

    def test_exactly_threshold_no_loss(self):
        assert detect_packet_loss(current_ts=3000, previous_ts=1000) is False

    def test_first_packet_no_previous(self):
        assert detect_packet_loss(current_ts=1000, previous_ts=None) is False

    def test_none_current_no_loss(self):
        assert detect_packet_loss(current_ts=None, previous_ts=1000) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_udp_sensor_listener.py::TestParseSensorData test_udp_sensor_listener.py::TestDetectPacketLoss -v`
Expected: All fail — `ImportError: cannot import name 'parse_sensor_data'`

- [ ] **Step 3: Write parse_sensor_data and detect_packet_loss**

Append to `udp_sensor_listener.py`:

```python
import json

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_udp_sensor_listener.py::TestParseSensorData test_udp_sensor_listener.py::TestDetectPacketLoss -v`
Expected: All 11 tests PASS (8 from Task 1 + 3 from Task 2 parse + 5 from Task 2 loss)

- [ ] **Step 5: Commit**

```bash
git add udp_sensor_listener.py test_udp_sensor_listener.py
git commit -m "feat: add JSON parsing and packet loss detection"
```

---

### Task 3: Display Formatter

**Files:**
- Modify: `udp_sensor_listener.py` — add `format_display_line()`
- Modify: `test_udp_sensor_listener.py` — add tests

**Interfaces:**
- Consumes: nothing from earlier tasks (pure function, takes parsed dict as input)
- Produces:
  - `format_display_line(data: dict, *, drop_count: int = 0, error_count: int = 0, use_color: bool = True) -> str`
  - Returns the ANSI-formatted status line string (without `\r` prefix — caller handles that)
  - `format_verbose_line(addr: tuple[str, int], byte_count: int, use_color: bool = True) -> str` — for `--verbose` mode

- [ ] **Step 1: Write failing tests for display formatter**

Append to `test_udp_sensor_listener.py`:

```python
import re
from udp_sensor_listener import format_display_line, format_verbose_line


def strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences for clean assertions."""
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestFormatDisplayLine:
    def test_full_normal_line(self):
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data)
        clean = strip_ansi(line)

        assert "26.3°C" in clean
        assert "54.8%" in clean
        assert "320.5 lx" in clean
        assert "450 ppm" in clean
        assert "12 ppb" in clean
        assert "0.85 V" in clean
        assert "2200" in clean

    def test_missing_eco2_tvoc_shows_yure(self):
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data)
        clean = strip_ansi(line)

        assert "预热" in clean

    def test_null_fields_show_dash(self):
        data = {"t": None, "h": None, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data)
        clean = strip_ansi(line)

        assert "--" in clean
        # Make sure the formatted values use dashes:
        assert "°C" not in clean  # No number before °C means it won't appear

    def test_packet_loss_warning_when_drop_count_positive(self):
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data, drop_count=3)
        clean = strip_ansi(line)

        assert "丢包 3" in clean

    def test_no_color_mode_no_ansi_escapes(self):
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data, use_color=False)

        assert "\033" not in line

    def test_color_mode_includes_ansi(self):
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data, use_color=True, drop_count=1)

        # Packet loss warning is yellow
        assert "\033[33m" in line

    def test_includes_timestamp_prefix(self):
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        line = format_display_line(data)
        clean = strip_ansi(line)

        # Should start with [HH:MM:SS]
        assert re.match(r"\[\d{2}:\d{2}:\d{2}\]", clean)


class TestFormatVerboseLine:
    def test_verbose_line_shows_ip_and_bytes(self):
        line = format_verbose_line(("192.168.1.42", 12345), 102)
        clean = strip_ansi(line)

        assert "192.168.1.42" in clean
        assert "12345" in clean
        assert "102" in clean
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_udp_sensor_listener.py::TestFormatDisplayLine test_udp_sensor_listener.py::TestFormatVerboseLine -v`
Expected: All fail — `ImportError: cannot import name 'format_display_line'`

- [ ] **Step 3: Write format_display_line and format_verbose_line**

Append to `udp_sensor_listener.py`:

```python
from datetime import datetime

# ── ANSI codes ───────────────────────────────────────────
DIM = "\033[2m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def _fmt_val(value, unit: str, *, is_ccs811: bool = False) -> str:
    """Format a single sensor value for display.

    - None → dim gray '--'
    - missing key (ccs811 warmup) → dim gray '预热'
    - normal → 'value unit'
    """
    if value is None:
        return f"{DIM}--{RESET}"
    if is_ccs811 and value == "预热":
        return f"{DIM}预热{RESET}"
    if isinstance(value, float):
        return f"{value:.1f} {unit}"
    return f"{value} {unit}"


def format_display_line(
    data: dict,
    *,
    drop_count: int = 0,
    error_count: int = 0,
    use_color: bool = True,
) -> str:
    """Build the single-line sensor status string with optional ANSI color."""

    dim_on = DIM if use_color else ""
    yellow_on = YELLOW if use_color else ""
    red_on = RED if use_color else ""
    reset = RESET if use_color else ""

    timestamp = datetime.now().strftime("%H:%M:%S")

    parts = [f"[{timestamp}]"]

    # Temperature
    t_val = data.get("t")
    if t_val is None:
        parts.append(f"温度: {dim_on}--{reset}")
    else:
        parts.append(f"温度: {t_val:.1f}°C")

    # Humidity
    h_val = data.get("h")
    if h_val is None:
        parts.append(f"湿度: {dim_on}--{reset}")
    else:
        parts.append(f"湿度: {h_val:.1f}%")

    # Light
    light_val = data.get("light")
    if light_val is None:
        parts.append(f"光照: {dim_on}--{reset}")
    else:
        parts.append(f"光照: {light_val:.1f} lx")

    # eCO2
    if "eco2" not in data:
        parts.append(f"eCO2: {dim_on}预热{reset}")
    elif data["eco2"] is None:
        parts.append(f"eCO2: {dim_on}--{reset}")
    else:
        parts.append(f"eCO2: {data['eco2']} ppm")

    # TVOC
    if "tvoc" not in data:
        parts.append(f"TVOC: {dim_on}预热{reset}")
    elif data["tvoc"] is None:
        parts.append(f"TVOC: {dim_on}--{reset}")
    else:
        parts.append(f"TVOC: {data['tvoc']} ppb")

    # Gas
    gas_val = data.get("gas")
    if gas_val is None:
        parts.append(f"气体: {dim_on}--{reset}")
    else:
        parts.append(f"气体: {gas_val:.2f} V")

    # Soil
    soil_val = data.get("soil")
    if soil_val is None:
        parts.append(f"土壤: {dim_on}--{reset}")
    else:
        parts.append(f"土壤: {soil_val}")

    # Packet loss warning
    if drop_count > 0:
        parts.append(f"{yellow_on}⚠ 丢包 {drop_count}{reset}")

    # Error indicator
    if error_count > 0:
        parts.append(f"{red_on}✗ 解析错误 {error_count}{reset}")

    return "  ".join(parts)


def format_verbose_line(addr: tuple, byte_count: int, use_color: bool = True) -> str:
    """Build the verbose second line showing source IP, port, and byte count."""
    dim_on = DIM if use_color else ""
    reset = RESET if use_color else ""
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"{dim_on}[{timestamp}] 来自 {addr[0]}:{addr[1]}  {byte_count} 字节{reset}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_udp_sensor_listener.py -v`
Expected: All tests PASS (8 CsvWriter + 6 parse + 5 loss + 7 display + 1 verbose = 27)

- [ ] **Step 5: Commit**

```bash
git add udp_sensor_listener.py test_udp_sensor_listener.py
git commit -m "feat: add terminal display formatter with ANSI color support"
```

---

### Task 4: DisplayManager Class

**Files:**
- Modify: `udp_sensor_listener.py` — add `DisplayManager`
- Modify: `test_udp_sensor_listener.py` — add tests

**Interfaces:**
- Consumes: `format_display_line()`, `format_verbose_line()` from Task 3
- Produces:
  - `class DisplayManager` with:
    - `__init__(self, verbose: bool = False, use_color: bool = True)`
    - `refresh(self, data: dict, *, drop_count: int = 0, error_count: int = 0, addr: tuple | None = None, byte_count: int = 0) -> None`
    - `show_waiting(self, bind_addr: str, port: int) -> None`
    - `show_shutdown(self, runtime_seconds: float, total_packets: int, drop_count: int, error_count: int, csv_bytes: int) -> None`

- [ ] **Step 1: Write failing tests for DisplayManager**

Append to `test_udp_sensor_listener.py`:

```python
import io
import sys
from udp_sensor_listener import DisplayManager


class TestDisplayManager:
    @pytest.fixture
    def capture_stdout(self):
        """Capture sys.stdout for assertion."""
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        yield buf
        sys.stdout = old

    def test_refresh_writes_single_line(self, capture_stdout):
        dm = DisplayManager(verbose=False, use_color=False)
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        dm.refresh(data)
        output = capture_stdout.getvalue()

        assert "\r" in output
        assert "\033[K" in output
        assert "26.3°C" in output

    def test_refresh_verbose_writes_two_lines(self, capture_stdout):
        dm = DisplayManager(verbose=True, use_color=False)
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        dm.refresh(data, addr=("192.168.1.42", 12345), byte_count=102)
        output = capture_stdout.getvalue()

        assert "192.168.1.42" in output
        assert "102" in output
        # Two lines: one verbose, one sensor
        assert output.count("\n") >= 1

    def test_show_waiting_prints_startup_message(self, capture_stdout):
        dm = DisplayManager(verbose=False, use_color=False)

        dm.show_waiting("0.0.0.0", 8259)
        output = capture_stdout.getvalue()

        assert "8259" in output
        assert "等待" in output

    def test_show_shutdown_prints_statistics(self, capture_stdout):
        dm = DisplayManager(verbose=False, use_color=False)

        dm.show_shutdown(
            runtime_seconds=13320.0,
            total_packets=13320,
            drop_count=5,
            error_count=0,
            csv_bytes=3_200_000,
        )
        output = capture_stdout.getvalue()

        assert "13320" in output
        assert "5" in output
        assert "3.05 MB" in output  # 3_200_000 bytes ≈ 3.05 MiB
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_udp_sensor_listener.py::TestDisplayManager -v`
Expected: All fail — `ImportError: cannot import name 'DisplayManager'`

- [ ] **Step 3: Write DisplayManager**

Append to `udp_sensor_listener.py`:

```python
import sys


class DisplayManager:
    """Manages terminal output with ANSI in-place refresh."""

    def __init__(self, verbose: bool = False, use_color: bool = True):
        self._verbose = verbose
        self._use_color = use_color
        self._first_data = True

    def refresh(
        self,
        data: dict,
        *,
        drop_count: int = 0,
        error_count: int = 0,
        addr: tuple | None = None,
        byte_count: int = 0,
    ) -> None:
        """Refresh the terminal display with latest sensor data."""
        if self._first_data:
            # Clear the "waiting" message
            sys.stdout.write("\r\033[K")
            self._first_data = False

        lines = []
        if self._verbose and addr:
            lines.append(format_verbose_line(addr, byte_count, use_color=self._use_color))

        lines.append(
            format_display_line(
                data,
                drop_count=drop_count,
                error_count=error_count,
                use_color=self._use_color,
            )
        )

        # Build the complete output: return to start of first line, write each line
        if len(lines) == 2:
            # Two-line mode: verbose line + sensor line
            sys.stdout.write(f"\r\033[K{lines[0]}\n")
            sys.stdout.write(f"\033[K{lines[1]}")
            # Move cursor back up so next refresh overwrites the verbose line
            sys.stdout.write("\033[A")
        else:
            sys.stdout.write(f"\r\033[K{lines[0]}")

        sys.stdout.flush()

    def show_waiting(self, bind_addr: str, port: int) -> None:
        """Print the initial waiting message."""
        print(f"监听 {bind_addr}:{port}，等待数据...", flush=True)

    def show_shutdown(
        self,
        runtime_seconds: float,
        total_packets: int,
        drop_count: int,
        error_count: int,
        csv_bytes: int,
    ) -> None:
        """Print exit statistics after Ctrl+C."""
        # Move down from the refresh line so we don't overwrite it
        print()
        print("已退出。")

        hours = int(runtime_seconds // 3600)
        minutes = int((runtime_seconds % 3600) // 60)
        duration = f"{hours}h {minutes}min" if hours else f"{minutes}min"

        def fmt_bytes(b: int) -> str:
            if b >= 1_048_576:
                return f"{b / 1_048_576:.2f} MB"
            elif b >= 1024:
                return f"{b / 1024:.1f} KB"
            return f"{b} B"

        print(
            f"运行时间: {duration}  |  "
            f"总包数: {total_packets}  |  "
            f"丢包: {drop_count}  |  "
            f"解析错误: {error_count}  |  "
            f"CSV: {fmt_bytes(csv_bytes)}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_udp_sensor_listener.py -v`
Expected: All 31 tests PASS

- [ ] **Step 5: Commit**

```bash
git add udp_sensor_listener.py test_udp_sensor_listener.py
git commit -m "feat: add DisplayManager with ANSI in-place terminal refresh"
```

---

### Task 5: SensorProtocol (UDP Listener) and Main Integration

**Files:**
- Modify: `udp_sensor_listener.py` — add `SensorProtocol` and `main()`
- Modify: `test_udp_sensor_listener.py` — add integration tests

**Interfaces:**
- Consumes: `CsvWriter` from Task 1, `parse_sensor_data()` and `detect_packet_loss()` from Task 2, `DisplayManager` from Task 4
- Produces:
  - `class SensorProtocol(asyncio.DatagramProtocol)` with:
    - `__init__(self, display: DisplayManager, csv_writer: CsvWriter)`
    - `datagram_received(self, data: bytes, addr: tuple) -> None`
    - Properties: `total_packets: int`, `drop_count: int`, `error_count: int`
  - `async def main() -> None` — full entry point with argparse + signal handling

- [ ] **Step 1: Write failing integration tests**

Append to `test_udp_sensor_listener.py`:

```python
import asyncio
from udp_sensor_listener import SensorProtocol


class TestSensorProtocol:
    @pytest.fixture
    def capture_stdout(self):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        yield buf
        sys.stdout = old

    def make_protocol(self, capture_stdout, verbose=False):
        """Create a SensorProtocol with real DisplayManager and a CsvWriter pointed at a temp dir."""
        dm = DisplayManager(verbose=verbose, use_color=False)
        dm._first_data = False  # suppress clear-line on first refresh
        with tempfile.TemporaryDirectory() as d:
            csv_writer = CsvWriter(log_dir=d, retention_days=60)
            proto = SensorProtocol(display=dm, csv_writer=csv_writer)
            yield proto, dm, csv_writer

    def test_full_packet_increments_counter_and_refreshes(self, capture_stdout):
        gen = self.make_protocol(capture_stdout)
        proto, dm, csv_writer = next(gen)

        raw = b'{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1000}'
        proto.datagram_received(raw, ("192.168.1.42", 12345))

        assert proto.total_packets == 1
        assert proto.error_count == 0
        output = capture_stdout.getvalue()
        assert "26.3°C" in output

    def test_malformed_json_increments_error_counter(self, capture_stdout):
        gen = self.make_protocol(capture_stdout)
        proto, dm, csv_writer = next(gen)

        proto.datagram_received(b"garbage", ("192.168.1.42", 12345))

        assert proto.total_packets == 0
        assert proto.error_count == 1

    def test_empty_packet_ignored(self, capture_stdout):
        gen = self.make_protocol(capture_stdout)
        proto, dm, csv_writer = next(gen)

        proto.datagram_received(b"", ("192.168.1.42", 12345))

        assert proto.total_packets == 0
        assert proto.error_count == 0

    def test_packet_loss_detection(self, capture_stdout):
        gen = self.make_protocol(capture_stdout)
        proto, dm, csv_writer = next(gen)

        # First packet
        proto.datagram_received(
            b'{"t":26.3,"h":54.8,"light":320.5,"gas":0.85,"soil":2200,"ts":1000}',
            ("192.168.1.42", 12345),
        )
        assert proto.drop_count == 0

        # Second packet with gap > 2000ms
        proto.datagram_received(
            b'{"t":26.3,"h":54.8,"light":320.5,"gas":0.85,"soil":2200,"ts":4000}',
            ("192.168.1.42", 12345),
        )
        assert proto.drop_count == 1

        output = capture_stdout.getvalue()
        assert "丢包 1" in output

    def test_csv_row_written(self, capture_stdout):
        gen = self.make_protocol(capture_stdout)
        proto, dm, csv_writer = next(gen)

        proto.datagram_received(
            b'{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1000}',
            ("192.168.1.42", 12345),
        )

        assert csv_writer.current_file is not None
        with open(csv_writer.current_file, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["t"] == "26.3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_udp_sensor_listener.py::TestSensorProtocol -v`
Expected: All fail — `ImportError: cannot import name 'SensorProtocol'`

- [ ] **Step 3: Write SensorProtocol**

Append to `udp_sensor_listener.py`:

```python
import asyncio
import argparse
import signal


class SensorProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol that parses ESP32 sensor JSON and drives display + CSV."""

    def __init__(self, display: DisplayManager, csv_writer: CsvWriter):
        self.display = display
        self.csv_writer = csv_writer
        self.total_packets: int = 0
        self.drop_count: int = 0
        self.error_count: int = 0
        self._last_ts: int | None = None

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        parsed = parse_sensor_data(data)

        if parsed is None:
            self.error_count += 1
            # Print error on its own line without disrupting the refresh display
            preview = data[:80].decode("utf-8", errors="replace")
            sys.stdout.write(f"\r\033[K\033[31m[ERROR] JSON 解析失败: {preview!r}\033[0m\n")
            sys.stdout.flush()
            return

        self.total_packets += 1

        # Packet loss detection
        current_ts = parsed.get("ts")
        if detect_packet_loss(current_ts, self._last_ts):
            self.drop_count += 1
        self._last_ts = current_ts

        # Drive display and CSV
        self.display.refresh(
            parsed,
            drop_count=self.drop_count,
            error_count=self.error_count,
            addr=addr,
            byte_count=len(data),
        )
        self.csv_writer.write_row(parsed, drop_count=self.drop_count, error_count=self.error_count)

    def error_received(self, exc: Exception) -> None:
        # Called by asyncio on transport-level errors; log and ignore
        sys.stderr.write(f"[WARN] UDP 传输错误: {exc}\n")
```

- [ ] **Step 4: Run protocol tests**

Run: `pytest test_udp_sensor_listener.py::TestSensorProtocol -v`
Expected: 5 tests PASS

- [ ] **Step 5: Write main() function**

Append to `udp_sensor_listener.py`:

```python
async def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESP32-C3 UDP 传感器数据监听器"
    )
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

    # Startup cleanup
    csv_writer.cleanup_old_files()

    display.show_waiting(args.bind, args.port)

    loop = asyncio.get_running_loop()
    transport: asyncio.DatagramTransport | None = None
    protocol: SensorProtocol | None = None
    start_time: float | None = None

    async def shutdown() -> None:
        """Graceful shutdown handler."""
        nonlocal transport, protocol
        if transport:
            transport.close()
        csv_writer.close()

        if start_time is not None:
            elapsed = loop.time() - start_time
        else:
            elapsed = 0.0

        display.show_shutdown(
            runtime_seconds=elapsed,
            total_packets=protocol.total_packets if protocol else 0,
            drop_count=protocol.drop_count if protocol else 0,
            error_count=protocol.error_count if protocol else 0,
            csv_bytes=csv_writer.total_bytes_written,
        )

    # Wire up Ctrl+C
    try:
        protocol = SensorProtocol(display=display, csv_writer=csv_writer)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=(args.bind, args.port),
        )
        start_time = loop.time()

        # Run forever until interrupted
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
        pass  # handled in main()'s finally block
```

- [ ] **Step 6: Run all tests**

Run: `pytest test_udp_sensor_listener.py -v`
Expected: All 36 tests PASS

- [ ] **Step 7: Manual smoke test**

In one terminal, start the listener:
```bash
python udp_sensor_listener.py
```

In another terminal, simulate an ESP32 packet:
```bash
echo '{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1234567}' | nc -u -w1 localhost 8259
```

Expected: the listener terminal shows the sensor line and updates on each packet.

- [ ] **Step 8: Commit**

```bash
git add udp_sensor_listener.py test_udp_sensor_listener.py
git commit -m "feat: add SensorProtocol UDP listener and CLI main entry point"
```
