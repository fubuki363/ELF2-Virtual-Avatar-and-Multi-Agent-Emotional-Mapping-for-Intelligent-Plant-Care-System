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
