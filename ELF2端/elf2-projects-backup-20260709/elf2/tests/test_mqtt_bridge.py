import pytest


def test_sensor_key_map():
    from mqtt_bridge import SENSOR_KEY_MAP
    assert SENSOR_KEY_MAP["/sensor.temperature.get"] == "t"
    assert SENSOR_KEY_MAP["/sensor.humidity.get"] == "h"
    assert SENSOR_KEY_MAP["/sensor.CO2.get"] == "eco2"
    assert SENSOR_KEY_MAP["/sensor.soil_moisture.get"] == "soil"
    assert SENSOR_KEY_MAP["/sensor.state.get"] == "all"
    assert SENSOR_KEY_MAP["/sys.cpu.temp"] is None


def test_sensor_reply_format(monkeypatch):
    import mqtt_bridge
    import hardware_control

    # 阻止 MqttBridge.__init__ 里的 TLS 配置
    monkeypatch.setattr(mqtt_bridge.mqtt.Client, "tls_set", lambda self, **kw: None)
    monkeypatch.setattr(mqtt_bridge.mqtt.Client, "username_pw_set", lambda self, *a, **kw: None)

    # 直接设置真实 hardware_control 模块的 sensor_cache
    hardware_control.sensor_cache = {
        "t": 26.3, "h": 54.8, "light": 320.5,
        "eco2": 450, "tvoc": 12, "soil": 2200
    }

    bridge = mqtt_bridge.MqttBridge()

    class FakeClient:
        def __init__(self):
            self.published = None
        def publish(self, topic, payload):
            self.published = (topic, payload)

    bridge.client = FakeClient()

    class FakeMsg:
        topic = "rpi5/cloud/command"
        payload = b"/sensor.temperature.get"

    bridge._on_message(None, None, FakeMsg())
    assert bridge.client.published is not None
    topic, payload = bridge.client.published
    assert topic == "rpi5/cloud/data"
    assert "26.3" in payload
