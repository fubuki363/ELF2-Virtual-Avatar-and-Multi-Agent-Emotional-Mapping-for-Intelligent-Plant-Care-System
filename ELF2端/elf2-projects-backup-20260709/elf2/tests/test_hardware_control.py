import asyncio
import json
import pytest
from shared_types import CommandEvent


@pytest.mark.asyncio
async def test_sensor_parse(monkeypatch):
    import hardware_control
    import database as db_module
    monkeypatch.setattr(db_module, "save_sensor", lambda data: None)
    proto = hardware_control.SensorProtocol()
    full_data = json.dumps({"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1234567}).encode()
    proto.datagram_received(full_data, ("192.168.1.100", 8259))
    assert hardware_control.sensor_cache["t"] == 26.3
    assert hardware_control.sensor_cache["eco2"] == 450
    assert hardware_control.esp32_ip == "192.168.1.100"
    partial_data = json.dumps({"t": 26.5, "h": 55.0, "light": 330.0, "gas": 0.82, "soil": 2100, "ts": 1235567}).encode()
    proto.datagram_received(partial_data, ("192.168.1.100", 8259))
    assert hardware_control.sensor_cache["eco2"] is None
    assert hardware_control.sensor_cache["tvoc"] is None


def test_offline_detection(monkeypatch):
    import hardware_control
    import time
    monkeypatch.setattr(hardware_control, "_last_sensor_ts", time.time())
    assert hardware_control.is_esp32_online() is True
    monkeypatch.setattr(hardware_control, "_last_sensor_ts", time.time() - 5.0)
    assert hardware_control.is_esp32_online() is False


@pytest.mark.asyncio
async def test_command_dropped_when_offline():
    import hardware_control
    hardware_control.esp32_ip = None
    cmd_queue = asyncio.Queue()
    await cmd_queue.put(CommandEvent(commands=[{"d": "fan", "v": 80}], source="voice"))
    assert hardware_control.esp32_ip is None
