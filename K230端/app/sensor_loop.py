# sensor_loop.py — Thread-1: 传感器采集 + UDP JSON 发送 (1Hz)
import time
import ujson
import socket
import sys
from machine import I2C

from config import (
    I2C_BUS, I2C_SCL, I2C_SDA, I2C_FREQ,
    SHT35_ADDR, CCS811_ADDR, BH1750_ADDR,
    ADC_GAS_CH, ADC_SOIL_CH,
    ELF2_SENSOR_PORT, SAMPLE_INTERVAL_MS,
    MICS5524_DIVIDER_RATIO
)
from drivers.sht35 import SHT35
from drivers.ccs811 import CCS811
from drivers.bh1750 import BH1750
from drivers.mics5524 import Mics5524
from drivers.hw390 import HW390


def sensor_loop_thread(state, elf2_ip):
    """Thread-1: 每秒采集全部传感器 -> JSON -> UDP -> ELF2:8259"""

    # 初始化 I2C 总线
    i2c = I2C(I2C_BUS, scl=I2C_SCL, sda=I2C_SDA, freq=I2C_FREQ)
    print("[SensorLoop] I2C bus %d (SCL=IO%d, SDA=IO%d)" % (I2C_BUS, I2C_SCL, I2C_SDA))

    # DEBUG: 扫描 I2C 总线
    try:
        devices = i2c.scan()
        hex_list = [hex(d) for d in devices]
        print("[SensorLoop] I2C scan: %s" % str(hex_list))
        if 0x44 not in devices:
            print("[SensorLoop] WARNING: SHT35 (0x44) not detected!")
        if 0x5A not in devices:
            print("[SensorLoop] WARNING: CCS811 (0x5A) not detected!")
        if 0x23 not in devices:
            print("[SensorLoop] WARNING: BH1750 (0x23) not detected!")
    except Exception as e:
        print("[SensorLoop] I2C scan failed:", e)

    # 初始化传感器驱动
    sht35 = SHT35(i2c, SHT35_ADDR)
    ccs811 = CCS811(i2c, CCS811_ADDR)
    bh1750 = BH1750(i2c, BH1750_ADDR)
    mics5524 = Mics5524(ADC_GAS_CH, MICS5524_DIVIDER_RATIO)
    hw390 = HW390(ADC_SOIL_CH)

    # 初始化 CCS811 (可能需要预热)
    if not ccs811.begin():
        print("[SensorLoop] WARNING: CCS811 init failed, eco2/tvoc will be unavailable")
    bh1750.begin()

    # 创建 UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print("[SensorLoop] Started, target: %s:%d" % (elf2_ip, ELF2_SENSOR_PORT))
    addr = (elf2_ip, ELF2_SENSOR_PORT)

    while True:
        loop_start = time.ticks_ms()

        try:
            # 读全部传感器
            temp, humi = sht35.read()
            eco2, tvoc = ccs811.read()
            lux = bh1750.read()
            gas_v = mics5524.read()
            soil = hw390.read()

            # 构造 JSON (动态字段 — CCS811 未就绪则不发送 eco2/tvoc)
            data = {}
            if temp is not None:
                data["t"] = temp
            if humi is not None:
                data["h"] = humi
            if lux is not None:
                data["light"] = lux
            if eco2 is not None:
                data["eco2"] = eco2
            if tvoc is not None:
                data["tvoc"] = tvoc
            if gas_v is not None:
                data["gas"] = gas_v
            if soil is not None:
                data["soil"] = soil

            data["ts"] = time.ticks_ms()

            # JSON 序列化 + UDP 发送 (跳过无效目标)
            json_str = ujson.dumps(data)
            if elf2_ip != "0.0.0.0":
                sock.sendto(json_str.encode(), addr)

            # DEBUG: 同时打印到终端
            ts_sec = data.get("ts", 0) // 1000
            print("[SENSOR #%ds] %s" % (ts_sec, json_str))

        except Exception as e:
            print("[SensorLoop] Error:", e)
            sys.print_exception(e)

        # 精确 1s 间隔
        elapsed = time.ticks_diff(time.ticks_ms(), loop_start)
        sleep_ms = max(0, SAMPLE_INTERVAL_MS - elapsed)
        if sleep_ms > 0:
            time.sleep_ms(sleep_ms)
