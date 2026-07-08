# drivers/sht35.py — SHT35 温湿度传感器 (I2C)
import time


class SHT35:
    """SHT35 I2C 温湿度传感器驱动"""

    def __init__(self, i2c, addr=0x44):
        self.i2c = i2c
        self.addr = addr

    @staticmethod
    def _crc8(data):
        """CRC-8 校验: 多项式 0x31, 初始值 0xFF"""
        crc = 0xFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x31
                else:
                    crc <<= 1
                crc &= 0xFF
        return crc

    def read(self):
        """读取温湿度，返回 (temp_c, humi_rh)。失败返回 (None, None)。"""
        try:
            # 启动单次测量: 高重复性 + 时钟拉伸
            self.i2c.writeto(self.addr, bytes([0x2C, 0x06]))
            time.sleep_ms(20)

            # 读 6 字节: T_msb, T_lsb, T_crc, H_msb, H_lsb, H_crc
            data = self.i2c.readfrom(self.addr, 6)

            # CRC 校验
            if self._crc8(data[0:2]) != data[2]:
                print("[SHT35] Temperature CRC failed")
                return (None, None)
            if self._crc8(data[3:5]) != data[5]:
                print("[SHT35] Humidity CRC failed")
                return (None, None)

            t_raw = (data[0] << 8) | data[1]
            h_raw = (data[3] << 8) | data[4]
            temp = -45.0 + 175.0 * t_raw / 65535.0
            humi = 100.0 * h_raw / 65535.0
            return (round(temp, 1), round(humi, 1))

        except OSError as e:
            print(f"[SHT35] I2C error: {e}")
            return (None, None)
