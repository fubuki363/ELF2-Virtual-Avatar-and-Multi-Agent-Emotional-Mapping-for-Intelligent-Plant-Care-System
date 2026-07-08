"""Terminal display, CSV logging, and sensor data formatting."""
import csv
import pathlib
import sys
from datetime import datetime, timedelta


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

    @property
    def current_file(self) -> pathlib.Path | None:
        return self._current_file

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
        try:
            self._csv_writer.writerow(row)
            self._file_handle.flush()
        except (OSError, IOError) as e:
            print(f"CSV write failure: {e}", file=sys.stderr)
            return
        self.total_bytes_written = self._current_file.stat().st_size

    def cleanup_old_files(self) -> None:
        if not self._log_dir.exists():
            return
        cutoff = datetime.now() - timedelta(days=self._retention_days - 1)
        for f in self._log_dir.glob("*.csv"):
            try:
                file_date = datetime.strptime(f.stem, "%Y-%m-%d")
                if file_date < cutoff:
                    f.unlink()
            except ValueError:
                pass  # skip files that don't match the naming pattern
            except (OSError, PermissionError) as e:
                print(f"Warning: failed to clean up {f}: {e}", file=sys.stderr)

    def close(self) -> None:
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


# ── ANSI codes ───────────────────────────────────────────
DIM = "\033[2m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def format_verbose_line(addr: tuple, byte_count: int, use_color: bool = True) -> str:
    """Build the verbose second line showing source IP, port, and byte count."""
    dim_on = DIM if use_color else ""
    reset = RESET if use_color else ""
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"{dim_on}[{timestamp}] 来自 {addr[0]}:{addr[1]}  {byte_count} 字节{reset}"


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
        analysis_summary: dict | None = None,
        control_status: dict | None = None,
        events: list[str] | None = None,
    ) -> None:
        """Refresh the terminal display with sensor + analysis + control info."""
        if self._first_data:
            # Clear the "waiting" message
            sys.stdout.write("\r\033[K")
            self._first_data = False

        # Count how many lines we produce so we can move cursor back
        extra_line_count = 0

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
        else:
            sys.stdout.write(f"\r\033[K{lines[0]}")

        # Append extra lines if provided
        if analysis_summary:
            health = analysis_summary.get("health", 0)
            bar_len = 20
            filled = int(health / 100 * bar_len)
            bar = "█" * filled + "▏" * (bar_len - filled)
            health_label = "良好" if health >= 80 else "注意" if health >= 60 else "警告"
            sys.stdout.write(f"\n\033[K  健康指数: {health}  {bar}  {health_label}")
            extra_line_count += 1

            trends = analysis_summary.get("trends", {})
            if trends:
                trend_parts = []
                for key, rate in trends.items():
                    names = {"t": "温度", "h": "湿度", "light": "光照", "soil": "土壤"}
                    arrow = "↗" if rate > 0.1 else "↘" if rate < -0.1 else "→"
                    trend_parts.append(f"{names.get(key, key)} {arrow} {rate:+.1f}/5min")
                sys.stdout.write(f"\n\033[K  趋势: {'  '.join(trend_parts)}")
                extra_line_count += 1

        if control_status:
            status_parts = []
            for dev, val in control_status.items():
                icons = {"fan": "⚡", "pump": "\U0001f30a", "led": "\U0001f4a1",
                         "humidifier": "\U0001f4a7", "heater": "\U0001f525"}
                icon = icons.get(dev, "•")
                if isinstance(val, dict):
                    status_parts.append(f"{icon} {dev} {val.get('brightness', val)}")
                else:
                    status_parts.append(f"{icon} {dev} {val}%")
            sys.stdout.write(f"\n\033[K───\n\033[K  {' │ '.join(status_parts)}")
            extra_line_count += 1

        if events:
            for evt in events[-2:]:  # Show last 2 events
                sys.stdout.write(f"\n\033[K  {evt}")
                extra_line_count += 1

        # Move cursor back up so next refresh overwrites all lines
        if len(lines) == 2 and extra_line_count > 0:
            # Need to move up: verbose line at top + extra lines
            # The cursor is after the last extra line; go up the extra lines + 1 (for the verbose line cursor fix)
            for _ in range(extra_line_count):
                sys.stdout.write("\033[A")
        elif extra_line_count > 0:
            # Single-line mode: cursor is after the last extra line; go up extra lines
            for _ in range(extra_line_count):
                sys.stdout.write("\033[A")

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
