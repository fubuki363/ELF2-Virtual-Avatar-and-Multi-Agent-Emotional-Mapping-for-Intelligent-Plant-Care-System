import asyncio
import json
import threading
import time
from shared_types import CommandEvent
import database

UDP_LISTEN_PORT = 8259
ESP32_CMD_PORT = 8260
ESP32_OFFLINE_TIMEOUT = 3.0
SENSOR_DB_INTERVAL = 60

sensor_cache: dict = {}
esp32_ip: str | None = None
_last_sensor_ts: float = 0.0


def is_esp32_online() -> bool:
    return (time.time() - _last_sensor_ts) < ESP32_OFFLINE_TIMEOUT


class SensorProtocol(asyncio.DatagramProtocol):

    def __init__(self):
        self.transport = None
        self._last_db_save = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        global esp32_ip, _last_sensor_ts
        esp32_ip = addr[0]
        _last_sensor_ts = time.time()

        try:
            payload = json.loads(data.decode("utf-8"))
            sensor_cache.update({
                "t": payload["t"],
                "h": payload["h"],
                "light": payload["light"],
                "eco2": payload.get("eco2"),
                "tvoc": payload.get("tvoc"),
                "gas": payload["gas"],
                "soil": payload["soil"],
                "ts": payload["ts"],
            })

            prev_ts = sensor_cache.get("_prev_ts", 0)
            gap = payload["ts"] - prev_ts
            if prev_ts and gap > 1000:
                print(f"[传感器] 丢包检测: ts 跳跃 {gap}ms")
            sensor_cache["_prev_ts"] = payload["ts"]

            now = time.time()
            if now - self._last_db_save >= SENSOR_DB_INTERVAL:
                self._last_db_save = now
                payload_copy = payload.copy()
                threading.Thread(
                    target=database.save_sensor, args=(payload_copy,), daemon=True
                ).start()

        except (json.JSONDecodeError, KeyError) as e:
            print(f"[传感器] 解析失败: {e}")


async def run(cmd_queue: asyncio.Queue):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        SensorProtocol, local_addr=("0.0.0.0", UDP_LISTEN_PORT)
    )
    print(f"[传感器] 监听 UDP :{UDP_LISTEN_PORT}")

    try:
        while True:
            try:
                cmd_event: CommandEvent = await asyncio.wait_for(
                    cmd_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if not esp32_ip:
                print("[硬件] ESP32 尚未上线，丢弃指令")
                continue

            payload = json.dumps(cmd_event.commands, ensure_ascii=False)
            transport.sendto(payload.encode("utf-8"), (esp32_ip, ESP32_CMD_PORT))
            print(f"[硬件] -> ESP32 {esp32_ip}:{ESP32_CMD_PORT}: {payload}")
            await asyncio.sleep(0.8)

    finally:
        transport.close()
