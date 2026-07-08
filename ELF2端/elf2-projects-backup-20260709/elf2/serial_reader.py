import asyncio
import serial_asyncio
from shared_types import VoiceEvent
import time

SERIAL_PORT = "/dev/ttyS9"
BAUDRATE = 9600
RECONNECT_DELAY = 3
MAX_RECONNECT_DELAY = 30


async def run(queue: asyncio.Queue):
    reconnect_delay = RECONNECT_DELAY
    while True:
        try:
            reader, _ = await serial_asyncio.open_serial_connection(
                url=SERIAL_PORT, baudrate=BAUDRATE
            )
            print(f"[串口] 已连接 {SERIAL_PORT} @ {BAUDRATE}bps")
            reconnect_delay = RECONNECT_DELAY
            buffer = ""
            while True:
                data = await reader.read(256)
                if not data:
                    raise ConnectionError("串口无数据，可能断开")
                buffer += data.decode("gbk", errors="ignore")
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    text = line.strip()
                    if text:
                        event = VoiceEvent(text=text, timestamp=time.time())
                        await queue.put(event)
                        print(f"[串口] <- {text}")
        except Exception as e:
            print(f"[串口] 错误: {e}，{reconnect_delay}秒后重连...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)
