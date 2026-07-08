# drivers/pump.py — 水泵 PWM 驱动 (1kHz via MOS)
from machine import FPIOA, PWM
from config import PWM_PUMP_IO, PWM_PUMP_CH, PWM_PUMP_FREQ


class Pump:
    """水泵, PWM2, IO46, 1kHz, N-MOS 低边开关"""

    def __init__(self, fpioa):
        fpioa.set_function(PWM_PUMP_IO, FPIOA.PWM2)
        self.pwm = PWM(PWM_PUMP_CH, freq=PWM_PUMP_FREQ, duty=0)

    def set(self, pct):
        self.pwm.duty(min(100, max(0, pct)))
