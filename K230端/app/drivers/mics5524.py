# drivers/mics5524.py — Mics5524 还原性气体传感器 (ADC)
from machine import ADC


class Mics5524:
    """Mics5524 气体传感器 (ADC 读取，分压补偿)"""

    def __init__(self, adc_ch=0, divider=1.5):
        """
        adc_ch: ADC 通道号 (0 = ADC0, Header Pin 32)
        divider: 分压补偿系数 (10k+20k)/20k = 1.5
        """
        self.adc = ADC(adc_ch)
        self.divider = divider

    def read(self):
        """读取气体电压值，已补偿分压还原为 0-5V 原始值。失败返回 None。"""
        try:
            voltage_3v3 = self.adc.read_uv() / 1_000_000.0  # 微伏 → 伏
            voltage_5v = round(voltage_3v3 * self.divider, 3)
            return voltage_5v
        except Exception as e:
            print(f"[Mics5524] Read error: {e}")
            return None
