# drivers/bh1750.py — BH1750 光照传感器 (I2C)
import time


class BH1750:
    """BH1750 环境光传感器驱动"""

    def __init__(self, i2c, addr=0x23):
        self.i2c = i2c
        self.addr = addr

    def begin(self):
        """上电 + 设置连续高分辨率模式"""
        try:
            self.i2c.writeto(self.addr, bytes([0x01]))  # Power ON
            time.sleep_ms(10)
            self.i2c.writeto(self.addr, bytes([0x10]))  # Continuous High Res
            time.sleep_ms(180)
            print("[BH1750] Initialized OK")
        except OSError as e:
            print(f"[BH1750] Init error: {e}")

    def read(self):
        """读取光照度 (lux)。失败返回 None。"""
        try:
            data = self.i2c.readfrom(self.addr, 2)
            raw = (data[0] << 8) | data[1]
            lux = round(raw / 1.2, 1)
            return lux
        except OSError as e:
            print(f"[BH1750] Read error: {e}")
            return None
