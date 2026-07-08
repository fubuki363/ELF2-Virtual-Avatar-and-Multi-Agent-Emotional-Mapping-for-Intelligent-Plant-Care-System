# drivers/ccs811.py — CCS811 VOC / eCO2 传感器 (I2C)
import time

# 寄存器地址
CCS811_STATUS = 0x00
CCS811_MEAS_MODE = 0x01
CCS811_ALG_RESULT_DATA = 0x02
CCS811_HW_ID = 0x20
CCS811_APP_START = 0xF4

# 状态位
CCS811_STATUS_ERROR = 0x01
CCS811_STATUS_DATA_READY = 0x08


class CCS811:
    """CCS811 VOC / eCO2 I2C 传感器驱动"""

    def __init__(self, i2c, addr=0x5A):
        self.i2c = i2c
        self.addr = addr
        self._started = False

    def begin(self):
        """初始化传感器: HW_ID 校验 → APP_START → 测量模式。返回 bool。"""
        try:
            # 检查硬件 ID
            hw_id = self.i2c.readfrom_mem(self.addr, CCS811_HW_ID, 1)[0]
            if hw_id != 0x81:
                print("[CCS811] Wrong HW_ID: 0x%02x, expected 0x81" % hw_id)
                return False

            # APP_START (发送空写)
            self.i2c.writeto_mem(self.addr, CCS811_APP_START, b'')
            time.sleep_ms(100)

            # 设置测量模式: 驱动模式 1 (1s 周期)
            self.i2c.writeto_mem(self.addr, CCS811_MEAS_MODE, bytes([0x10]))
            self._started = True
            print("[CCS811] Initialized OK")
            return True

        except OSError as e:
            print(f"[CCS811] Init error: {e}")
            return False

    def is_ready(self):
        """检查是否有新数据就绪 (无错误)。"""
        if not self._started:
            return False
        try:
            status = self.i2c.readfrom_mem(self.addr, CCS811_STATUS, 1)[0]
            return bool(status & CCS811_STATUS_DATA_READY) and not bool(status & CCS811_STATUS_ERROR)
        except OSError:
            return False

    def read(self):
        """读取 eco2(ppm) 和 tvoc(ppb)。未就绪返回 (None, None)。"""
        if not self.is_ready():
            return (None, None)

        try:
            data = self.i2c.readfrom_mem(self.addr, CCS811_ALG_RESULT_DATA, 4)
            eco2 = (data[0] << 8) | data[1]
            tvoc = (data[2] << 8) | data[3]
            return (eco2, tvoc)
        except OSError as e:
            print(f"[CCS811] Read error: {e}")
            return (None, None)
