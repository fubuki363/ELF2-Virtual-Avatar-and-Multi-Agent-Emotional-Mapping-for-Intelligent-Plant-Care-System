# drivers/humidifier.py — 加湿器 PWM 驱动 (1kHz via MOS)
from machine import FPIOA, PWM
from config import PWM_HUMID_IO, PWM_HUMID_CH, PWM_HUMID_FREQ


class Humidifier:
    """加湿器, PWM3, IO47, 1kHz, N-MOS 低边开关"""

    def __init__(self, fpioa):
        fpioa.set_function(PWM_HUMID_IO, FPIOA.PWM3)
        self.pwm = PWM(PWM_HUMID_CH, freq=PWM_HUMID_FREQ, duty=0)

    def set(self, pct):
        self.pwm.duty(min(100, max(0, pct)))
