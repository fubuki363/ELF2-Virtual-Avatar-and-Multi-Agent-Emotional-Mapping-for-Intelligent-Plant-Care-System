# drivers/heater.py — 加热片 PWM 驱动 (1kHz via MOS)
from machine import FPIOA, PWM
from config import PWM_HEATER_IO, PWM_HEATER_CH, PWM_HEATER_FREQ


class Heater:
    """加热片, PWM1, IO43, 1kHz, N-MOS 低边开关"""

    def __init__(self, fpioa):
        fpioa.set_function(PWM_HEATER_IO, FPIOA.PWM1)
        self.pwm = PWM(PWM_HEATER_CH, freq=PWM_HEATER_FREQ, duty=0)

    def set(self, pct):
        self.pwm.duty(min(100, max(0, pct)))
