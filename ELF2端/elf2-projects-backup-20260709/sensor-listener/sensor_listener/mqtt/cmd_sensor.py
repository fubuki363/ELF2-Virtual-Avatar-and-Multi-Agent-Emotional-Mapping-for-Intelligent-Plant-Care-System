"""Sensor query commands — reads from shared UDP sensor state (not I2C)."""
from sensor_listener.mqtt.base_cmd import BaseCommand

# Shared state, set by main.py at startup
_sensor_state: dict = {}


def set_sensor_state(state: dict):
    """Called by main.py to inject the latest sensor data."""
    global _sensor_state
    _sensor_state = state


class SensorTemperatureGet(BaseCommand):
    def execute(self, args: str) -> str:
        t = _sensor_state.get("t")
        if t is None:
            return "[ERROR 502] 温度传感器无数据"
        return f"[OK] /sensor.temperature.get = 当前温度: {t:.1f} °C"


class SensorHumidityGet(BaseCommand):
    def execute(self, args: str) -> str:
        h = _sensor_state.get("h")
        if h is None:
            return "[ERROR 502] 湿度传感器无数据"
        return f"[OK] /sensor.humidity.get = 当前湿度: {h:.1f} %RH"


class SensorIllumination_intensityGet(BaseCommand):
    def execute(self, args: str) -> str:
        light = _sensor_state.get("light")
        if light is None:
            return "[ERROR 502] 光照传感器无数据"
        return f"[OK] /sensor.illumination_intensity.get = 当前光照: {light:.1f} Lux"


class SensorCO2Get(BaseCommand):
    def execute(self, args: str) -> str:
        eco2 = _sensor_state.get("eco2")
        tvoc = _sensor_state.get("tvoc")
        if eco2 is None and tvoc is None:
            return "[ERROR 502] CCS811 传感器未就绪（预热中）"
        return f"[OK] /sensor.CO2.get = eCO2: {eco2} ppm | TVOC: {tvoc} ppb"


class SensorAir_qualityGet(BaseCommand):
    def execute(self, args: str) -> str:
        gas = _sensor_state.get("gas")
        if gas is None:
            return "[ERROR 502] 气体传感器无数据"
        return f"[OK] /sensor.air_quality.get = 气体电压: {gas:.3f} V"


class SensorSoil_moistureGet(BaseCommand):
    def execute(self, args: str) -> str:
        soil = _sensor_state.get("soil")
        if soil is None:
            return "[ERROR 502] 土壤传感器无数据"
        return f"[OK] /sensor.soil_moisture.get = 土壤湿度ADC: {soil}"


class SensorStateGet(BaseCommand):
    def execute(self, args: str) -> str:
        import json
        return json.dumps({
            "code": 200, "status": "success",
            "message": "获取设备综合状态成功",
            "data": {
                "temperature": _sensor_state.get("t"),
                "humidity": _sensor_state.get("h"),
                "light": _sensor_state.get("light"),
                "soil_moisture": _sensor_state.get("soil"),
                "air_quality": _sensor_state.get("gas"),
                "co2": _sensor_state.get("eco2"),
                "tvoc": _sensor_state.get("tvoc"),
                "health_score": _sensor_state.get("health_score"),
                "last_update": _sensor_state.get("last_update"),
            }
        }, ensure_ascii=False)


class PlantPhotoTake(BaseCommand):
    """Trigger immediate YOLO scan and return result."""
    def execute(self, args: str) -> str:
        yolo_event = _sensor_state.get("yolo_event")
        if yolo_event:
            import json
            return json.dumps({"code": 200, "status": "success",
                               "data": yolo_event}, ensure_ascii=False)
        return "[ERROR 503] 暂无YOLO检测结果，请稍后再试"


class PlantHealthGet(BaseCommand):
    """Return plant health score and analysis summary."""
    def execute(self, args: str) -> str:
        import json
        return json.dumps({
            "code": 200, "status": "success",
            "data": {
                "health_score": _sensor_state.get("health_score", 0),
                "alerts": _sensor_state.get("alerts", []),
                "trends": _sensor_state.get("trends", {}),
            }
        }, ensure_ascii=False)
