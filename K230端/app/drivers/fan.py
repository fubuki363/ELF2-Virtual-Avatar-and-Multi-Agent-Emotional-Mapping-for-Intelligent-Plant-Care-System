# drivers/fan.py — 四线风扇 PWM 驱动 (25kHz)
from machine import FPIOA, PWM
from config import PWM_FAN_IO, PWM_FAN_CH, PWM_FAN_FREQ


class Fan:
    """四线风扇, PWM0, IO42, 25kHz"""

    def __init__(self, fpioa):
        fpioa.set_function(PWM_FAN_IO, FPIOA.PWM0)
        self.pwm = PWM(PWM_FAN_CH, freq=PWM_FAN_FREQ, duty=0)

    def set(self, pct):
        """设置占空比 0-100"""
        self.pwm.duty(min(100, max(0, pct)))
