import asyncio
import os
import ssl
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

MQTT_BROKER = "p8c59112.ala.cn-hangzhou.emqxsl.cn"
MQTT_PORT = 8883
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "rpi_user")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "your_mqtt_password_here")
MQTT_CA_CRT = os.path.join(os.path.dirname(__file__), "..", "emqxsl-ca.crt")

TOPIC_SUB = "rpi5/cloud/command"
TOPIC_PUB = "rpi5/cloud/data"

SENSOR_KEY_MAP = {
    "/sensor.state.get": "all",
    "/sensor.temperature.get": "t",
    "/sensor.humidity.get": "h",
    "/sensor.CO2.get": "eco2",
    "/sensor.air_quality.get": "tvoc",
    "/sensor.illumination_intensity.get": "light",
    "/sensor.soil_moisture.get": "soil",
    "/sys.cpu.temp": None,
    "/sys.mem.info": None,
    "/sys.disk.info": None,
    "/sys.os.uptime": None,
    "/sys.power.reboot": None,
}


class MqttBridge:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.tls_set(ca_certs=MQTT_CA_CRT, tls_version=ssl.PROTOCOL_TLSv1_2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"[MQTT] 已连接 EMQX Cloud，订阅 {TOPIC_SUB}")
            client.subscribe(TOPIC_SUB)
        else:
            print(f"[MQTT] 连接失败，状态码: {reason_code}")

    def _on_message(self, client, userdata, msg):
        if msg.topic != TOPIC_SUB:
            return

        import hardware_control

        command = msg.payload.decode("utf-8").strip()
        print(f"[MQTT] <- PC 下发指令: {command}")

        sensor_key = SENSOR_KEY_MAP.get(command)

        if sensor_key is None:
            reply = f"指令 {command} 暂不支持"
        elif sensor_key == "all":
            cache = hardware_control.sensor_cache
            reply = (
                f"温度: {cache.get('t', '--')}C, "
                f"湿度: {cache.get('h', '--')}%, "
                f"光照: {cache.get('light', '--')} lux, "
                f"CO2: {cache.get('eco2', '--')} ppm, "
                f"TVOC: {cache.get('tvoc', '--')} ppb, "
                f"土壤: {cache.get('soil', '--')}"
            )
        else:
            value = hardware_control.sensor_cache.get(sensor_key)
            if value is None:
                reply = f"{sensor_key} 传感器未就绪"
            else:
                reply = f"{sensor_key} = {value}"

        self.client.publish(TOPIC_PUB, reply)
        print(f"[MQTT] -> PC 回复: {reply}")

    def start(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()


async def run():
    bridge = MqttBridge()
    bridge.start()
    print("[MQTT] 桥接服务已启动")
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        bridge.stop()
        raise
