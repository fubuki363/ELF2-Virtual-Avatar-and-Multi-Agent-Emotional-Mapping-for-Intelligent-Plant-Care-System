# drivers/hw390.py — HW390 土壤湿度传感器 (ADC)
from machine import ADC


class HW390:
    """HW390 土壤湿度传感器 (ADC 读取)"""

    def __init__(self, adc_ch=1):
        """
        adc_ch: ADC 通道号 (1 = ADC1, Header Pin 36)
        """
        self.adc = ADC(adc_ch)

    def read(self):
        """读取土壤湿度原始值 (0-4095)，越湿值越低。失败返回 None。"""
        try:
            raw = self.adc.read_u16() >> 4  # 16-bit → 12-bit (与 ESP32 一致)
            return raw
        except Exception as e:
            print(f"[HW390] Read error: {e}")
            return None
