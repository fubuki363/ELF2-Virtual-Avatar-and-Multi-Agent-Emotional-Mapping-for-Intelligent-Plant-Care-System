"""UDP sensor listener — receives ESP32-C3 JSON packets, displays in-terminal, logs to CSV."""
import argparse
import asyncio
import csv
import json
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


# ── SensorProtocol (UDP listener) ─────────────────────────


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
        # Silently ignore empty and oversized packets (per spec)
        if not data or len(data) > MAX_PACKET_SIZE:
            return

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


# ── CLI entry point ───────────────────────────────────────


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
