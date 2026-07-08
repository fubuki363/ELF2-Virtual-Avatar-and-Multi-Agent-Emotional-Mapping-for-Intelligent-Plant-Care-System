import csv
import io
import pathlib
import re
import sys
import tempfile
from datetime import datetime, timedelta
from unittest import mock

import pytest

from sensor_listener.display import (
    CsvWriter,
    DisplayManager,
    format_display_line,
    format_verbose_line,
)
from sensor_listener.protocol import (
    SensorProtocol,
    parse_sensor_data,
    detect_packet_loss,
)

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
        with mock.patch("sensor_listener.display.datetime", wraps=datetime) as mock_dt:
            mock_dt.now.return_value = jan1
            writer.write_row(make_data(), drop_count=0, error_count=0)

        file1 = writer.current_file
        assert "2026-01-01" in str(file1)

        # Write second row on the next day
        jan2 = datetime(2026, 1, 2, 0, 1, 0)
        with mock.patch("sensor_listener.display.datetime", wraps=datetime) as mock_dt:
            mock_dt.now.return_value = jan2
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

        with mock.patch("sensor_listener.display.datetime", wraps=datetime) as mock_dt:
            mock_dt.now.return_value = today
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

    def test_write_row_oserror_does_not_crash(self, tmp_log_dir):
        """C1: CSV write failure prints to stderr, continues without raising."""
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=60)

        # Pre-set internal state so _open_file is not triggered inside write_row
        writer._current_date = datetime.now().strftime("%Y-%m-%d")
        writer._file_handle = mock.MagicMock()
        writer._csv_writer = mock.MagicMock()
        writer._csv_writer.writerow.side_effect = OSError("disk full")

        with mock.patch("sys.stderr", new=io.StringIO()) as fake_stderr:
            # Must not raise
            writer.write_row(make_data(), drop_count=0, error_count=0)
            stderr_output = fake_stderr.getvalue()

        assert "CSV write failure" in stderr_output

    def test_cleanup_old_files_permission_error_graceful(self, tmp_log_dir):
        """C2: Retention cleanup PermissionError prints warning to stderr, does not abort."""
        writer = CsvWriter(log_dir=str(tmp_log_dir), retention_days=2)

        today = datetime(2026, 7, 8)
        old_file = tmp_log_dir / "2026-07-04.csv"
        old_file.write_text("dummy")

        with mock.patch("sensor_listener.display.datetime", wraps=datetime) as mock_dt:
            mock_dt.now.return_value = today
            with mock.patch.object(pathlib.Path, "unlink", side_effect=PermissionError("access denied")):
                with mock.patch("sys.stderr", new=io.StringIO()) as fake_stderr:
                    # Must not raise
                    writer.cleanup_old_files()
                    stderr_output = fake_stderr.getvalue()

        assert "Warning" in stderr_output
        assert "2026-07-04" in stderr_output


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


# ── DisplayManager tests ─────────────────────────────────

class TestDisplayManager:
    def test_refresh_writes_single_line(self):
        dm = DisplayManager(verbose=False, use_color=False)
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            dm.refresh(data)
            output = fake_out.getvalue()

        assert "\r" in output
        assert "\033[K" in output
        assert "26.3°C" in output

    def test_refresh_verbose_writes_two_lines(self):
        dm = DisplayManager(verbose=True, use_color=False)
        data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 1234567}

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            dm.refresh(data, addr=("192.168.1.42", 12345), byte_count=102)
            output = fake_out.getvalue()

        assert "192.168.1.42" in output
        assert "102" in output
        # Two lines: one verbose, one sensor
        assert output.count("\n") >= 1

    def test_show_waiting_prints_startup_message(self):
        dm = DisplayManager(verbose=False, use_color=False)

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            dm.show_waiting("0.0.0.0", 8259)
            output = fake_out.getvalue()

        assert "8259" in output
        assert "等待" in output

    def test_show_shutdown_prints_statistics(self):
        dm = DisplayManager(verbose=False, use_color=False)

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            dm.show_shutdown(
                runtime_seconds=13320.0,
                total_packets=13320,
                drop_count=5,
                error_count=0,
                csv_bytes=3_200_000,
            )
            output = fake_out.getvalue()

        assert "13320" in output
        assert "5" in output
        assert "3.05 MB" in output  # 3_200_000 bytes ≈ 3.05 MiB


# ── SensorProtocol tests ─────────────────────────────────


class TestSensorProtocol:
    def make_protocol(self, verbose=False):
        """Create a SensorProtocol with real DisplayManager and a CsvWriter pointed at a temp dir."""
        dm = DisplayManager(verbose=verbose, use_color=False)
        dm._first_data = False  # suppress clear-line on first refresh
        with tempfile.TemporaryDirectory() as d:
            csv_writer = CsvWriter(log_dir=d, retention_days=60)
            try:
                proto = SensorProtocol(display=dm, csv_writer=csv_writer)
                yield proto, dm, csv_writer
            finally:
                csv_writer.close()

    def test_full_packet_increments_counter_and_refreshes(self):
        gen = self.make_protocol()
        proto, dm, csv_writer = next(gen)

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            raw = b'{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1000}'
            proto.datagram_received(raw, ("192.168.1.42", 12345))
            output = fake_out.getvalue()

        assert proto.total_packets == 1
        assert proto.error_count == 0
        assert "26.3" in output

    def test_malformed_json_increments_error_counter(self):
        gen = self.make_protocol()
        proto, dm, csv_writer = next(gen)

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            proto.datagram_received(b"garbage", ("192.168.1.42", 12345))
            output = fake_out.getvalue()

        assert proto.total_packets == 0
        assert proto.error_count == 1
        assert "ERROR" in output

    def test_empty_packet_ignored(self):
        gen = self.make_protocol()
        proto, dm, csv_writer = next(gen)

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
            proto.datagram_received(b"", ("192.168.1.42", 12345))
            output = fake_out.getvalue()

        assert proto.total_packets == 0
        assert proto.error_count == 0
        assert output == ""

    def test_packet_loss_detection(self):
        gen = self.make_protocol()
        proto, dm, csv_writer = next(gen)

        with mock.patch("sys.stdout", new=io.StringIO()) as fake_out:
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

            output = fake_out.getvalue()
            assert "丢包 1" in output

    def test_csv_row_written(self):
        gen = self.make_protocol()
        proto, dm, csv_writer = next(gen)

        with mock.patch("sys.stdout", new=io.StringIO()):
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
