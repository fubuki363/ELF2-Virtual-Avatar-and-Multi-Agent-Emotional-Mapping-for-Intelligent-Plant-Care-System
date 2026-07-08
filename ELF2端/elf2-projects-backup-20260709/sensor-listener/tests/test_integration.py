"""Integration tests for the full pipeline."""
import tempfile
import pathlib
from unittest import mock

from sensor_listener.display import CsvWriter, DisplayManager
from sensor_listener.protocol import SensorProtocol
from sensor_listener.analysis import AnalysisEngine
from sensor_listener.control import ControlEngine


class TestFullPipeline:
    def test_sensor_to_analysis_to_control(self):
        """End-to-end: UDP data -> analysis -> control commands."""
        dm = DisplayManager(verbose=False, use_color=False)
        dm._first_data = False

        analysis = AnalysisEngine()
        control = ControlEngine()
        control.update_k230_addr(("192.168.1.100", 8260))

        csv_dir = tempfile.mkdtemp()
        try:
            csv_writer = CsvWriter(log_dir=csv_dir, retention_days=60)

            proto = SensorProtocol(
                display=dm, csv_writer=csv_writer,
                analysis_engine=analysis, control_engine=control,
            )

            # Simulate receiving a hot/dry packet — this internally drives
            # analysis.feed() and control.evaluate() via the protocol
            raw = b'{"t":33.0,"h":40.0,"light":320,"soil":3000,"ts":1000}'
            proto.datagram_received(raw, ("192.168.1.100", 12345))

            # Verify analysis was fed by checking summary
            summary = analysis.get_summary()
            assert 0 <= summary["health"] <= 100

            # Verify control triggered devices (fan for heat, pump for dry soil)
            status = control.get_status()
            assert "fan" in status
            assert status["fan"] > 0
            assert "pump" in status
            assert status["pump"] > 0

            # Clean up file handles so directory can be removed on Windows
            csv_writer.close()
        finally:
            import shutil
            shutil.rmtree(csv_dir, ignore_errors=True)

    def test_csv_still_works(self):
        """After all refactoring, CSV writing must still work."""
        dm = DisplayManager(verbose=False, use_color=False)
        dm._first_data = False

        csv_dir = tempfile.mkdtemp()
        try:
            csv_writer = CsvWriter(log_dir=csv_dir, retention_days=60)
            proto = SensorProtocol(display=dm, csv_writer=csv_writer)

            raw = b'{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1000}'
            proto.datagram_received(raw, ("192.168.1.100", 12345))

            # Close CSV writer to flush and release file handle
            csv_writer.close()

            with open(csv_writer.current_file, "r") as f:
                import csv
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["t"] == "26.3"
        finally:
            import shutil
            shutil.rmtree(csv_dir, ignore_errors=True)

    def test_pipeline_without_engines_still_works(self):
        """Protocol must work without analysis/control engines (backward compat)."""
        dm = DisplayManager(verbose=False, use_color=False)
        dm._first_data = False

        csv_dir = tempfile.mkdtemp()
        try:
            csv_writer = CsvWriter(log_dir=csv_dir, retention_days=60)
            proto = SensorProtocol(display=dm, csv_writer=csv_writer)

            # Should not crash without engines
            raw = b'{"t":22.0,"h":55.0,"light":400,"soil":1800,"ts":1000}'
            proto.datagram_received(raw, ("192.168.1.100", 12345))

            assert proto.total_packets == 1
            assert proto._last_ts == 1000

            csv_writer.close()
        finally:
            import shutil
            shutil.rmtree(csv_dir, ignore_errors=True)

    def test_display_multi_line_with_analysis(self):
        """DisplayManager.refresh() renders analysis and control lines when provided."""
        import io
        dm = DisplayManager(verbose=False, use_color=False)
        dm._first_data = False

        data = {"t": 26.3, "h": 54.8, "light": 320, "soil": 2200}
        analysis_summary = {"health": 82, "trends": {"t": 0.5, "h": -0.2}}
        control_status = {"fan": 0, "pump": 0}

        captured = io.StringIO()
        try:
            import sys
            old_stdout = sys.stdout
            sys.stdout = captured

            dm.refresh(
                data, analysis_summary=analysis_summary,
                control_status=control_status,
            )

            output = captured.getvalue()
            # Should contain health info
            assert "82" in output or "健康" in output  # health indicator
            # Should contain trend info
            assert "趋势" in output  # trends label
            # Should contain control divider
            assert "───" in output  # divider
        finally:
            sys.stdout = old_stdout
