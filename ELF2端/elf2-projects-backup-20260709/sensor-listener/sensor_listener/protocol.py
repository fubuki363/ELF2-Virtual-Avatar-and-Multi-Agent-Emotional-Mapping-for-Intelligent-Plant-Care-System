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


class SensorProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol that parses ESP32/K230 sensor JSON and drives display + CSV."""

    def __init__(self, display, csv_writer, analysis_engine=None, control_engine=None,
                 k230_port: int = 8260):
        from sensor_listener.display import DisplayManager
        self.display: DisplayManager = display
        self.csv_writer = csv_writer
        self.analysis = analysis_engine
        self.control = control_engine
        self.k230_port: int = k230_port
        self.total_packets: int = 0
        self.drop_count: int = 0
        self.error_count: int = 0
        self._last_ts: int | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._llm_task_in_flight: bool = False

    def connection_made(self, transport):
        self._transport = transport

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

        # Drive analysis engine
        if self.analysis:
            self.analysis.feed(parsed)

        # Drive control engine
        if self.control:
            if not self.control._k230_addr:
                self.control.update_k230_addr((addr[0], self.k230_port))
            summary = self.analysis.get_summary() if self.analysis else {}
            cmds = self.control.evaluate(parsed, summary)

            # Send commands via UDP
            if cmds and self._transport and self.control._k230_addr:
                import json as _json
                cmd_bytes = _json.dumps(cmds).encode("utf-8")
                self._transport.sendto(cmd_bytes, self.control._k230_addr)

            # Schedule async LLM consultation if advisor is wired
            if self.control._llm_advisor is not None and not self._llm_task_in_flight:
                self._llm_task_in_flight = True
                asyncio.ensure_future(self._consult_llm())

        # Gather analysis + control status for display
        analysis_summary = self.analysis.get_summary() if self.analysis else None
        control_status = self.control.get_status() if self.control else None

        self.display.refresh(
            parsed,
            drop_count=self.drop_count,
            error_count=self.error_count,
            addr=addr,
            byte_count=len(data),
            analysis_summary=analysis_summary,
            control_status=control_status,
        )
        self.csv_writer.write_row(parsed, drop_count=self.drop_count, error_count=self.error_count)

    async def _consult_llm(self) -> None:
        """Async helper: consult LLM advisor with recent data, then inject result into control engine."""
        try:
            advisor = self.control._llm_advisor if self.control else None
            if advisor is None:
                return

            analysis_summary = self.analysis.get_summary() if self.analysis else {}
            data_history = self.analysis.get_recent_data(60) if self.analysis else []

            # Determine trigger type from analysis summary
            trigger_reason = "sensor_update"
            alerts = analysis_summary.get("alerts", [])
            if alerts:
                trigger_reason = alerts[0]
            elif analysis_summary.get("health", 100) < 60:
                trigger_reason = "健康指数偏低"

            if not advisor.should_consult(
                "health_low" if analysis_summary.get("health", 100) < 60 else "sensor_update",
                data_history,
            ):
                return

            decision = await advisor.consult(trigger_reason, data_history, analysis_summary)
            if decision is not None and self.control:
                self.control.set_llm_override(decision.commands)
        finally:
            self._llm_task_in_flight = False

    def error_received(self, exc: Exception) -> None:
        sys.stderr.write(f"[WARN] UDP 传输错误: {exc}\n")
