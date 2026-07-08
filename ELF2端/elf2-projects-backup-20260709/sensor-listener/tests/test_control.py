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
