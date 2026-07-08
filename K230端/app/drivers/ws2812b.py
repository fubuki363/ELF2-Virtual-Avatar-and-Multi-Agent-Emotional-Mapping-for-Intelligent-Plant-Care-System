# drivers/ws2812b.py — WS2812B LED 灯带驱动 (GPIO 位脉冲, 60 灯)
import time
import math
from machine import Pin, FPIOA
from config import LED_SPI_MOSI_IO, LED_COUNT


class WS2812B:
    """WS2812B 60 灯 GPIO 直驱, GRB 色序"""

    def __init__(self, fpioa, num_leds=LED_COUNT, brightness=128):
        # 配置 IO16 为 GPIO 输出
        fpioa.set_function(LED_SPI_MOSI_IO, FPIOA.GPIO16)
        self.pin = Pin(LED_SPI_MOSI_IO, Pin.OUT)
        self.pin.value(0)

        self.num_leds = num_leds
        self.brightness = brightness
        self.mode = "effect"
        self.effect = "rainbow"
        self._need_redraw = True
        print("[WS2812B] GPIO mode, pin=IO%d, %d LEDs" % (LED_SPI_MOSI_IO, num_leds))

    # ============================================================
    #  硬件层: GPIO 位脉冲 (NOP 校准)
    #  WS2812B 时序: 每 bit 约 1.25µs
    #    '0': H=0.4±0.15µs,  L=0.85±0.15µs
    #    '1': H=0.8±0.15µs,  L=0.45±0.15µs
    #  NOP 循环 @ K230 800MHz: 每轮约 30-50ns (Python 字节码解释执行)
    # ============================================================

    # 校准常量 (可根据实测微调)
    NOP_H1 = 35   # '1' HIGH  ~0.8µs
    NOP_L1 = 18   # '1' LOW   ~0.45µs
    NOP_H0 = 15   # '0' HIGH  ~0.4µs
    NOP_L0 = 35   # '0' LOW   ~0.85µs

    @staticmethod
    def _nop(n):
        """NOP 忙等 n 轮"""
        for _ in range(n):
            pass

    def _write_byte(self, b):
        """发送一个字节 MSB first"""
        for i in range(7, -1, -1):
            if (b >> i) & 1:
                self.pin.value(1)
                self._nop(self.NOP_H1)
                self.pin.value(0)
                self._nop(self.NOP_L1)
            else:
                self.pin.value(1)
                self._nop(self.NOP_H0)
                self.pin.value(0)
                self._nop(self.NOP_L0)

    def _show(self, grb_data):
        """发送完整帧 + reset"""
        for i in range(self.num_leds):
            g = grb_data[i * 3]
            r = grb_data[i * 3 + 1]
            b = grb_data[i * 3 + 2]
            self._write_byte(g)
            self._write_byte(r)
            self._write_byte(b)

        # Reset: ≥50µs LOW
        self.pin.value(0)
        time.sleep_us(60)

    # ============================================================
    #  效果层
    # ============================================================

    def _hsv_to_grb(self, hue, sat, val):
        region = hue // 43
        remainder = (hue - (region * 43)) * 6
        p = (val * (255 - sat)) // 255
        q = (val * (255 - (sat * remainder) // 255)) // 255
        t = (val * (255 - (sat * (255 - remainder)) // 255)) // 255
        if region == 0:   r, g, b = val, t, p
        elif region == 1: r, g, b = q, val, p
        elif region == 2: r, g, b = p, val, t
        elif region == 3: r, g, b = p, q, val
        elif region == 4: r, g, b = t, p, val
        else:             r, g, b = val, p, q
        return (g, r, b)

    def set_mode(self, mode, effect=None, brightness=None):
        self.mode = mode
        if effect is not None:
            self.effect = effect
        if brightness is not None:
            self.brightness = max(0, min(255, brightness))
        self._need_redraw = True

    def _draw_static(self, r, g, b):
        for _ in range(self.num_leds):
            self._write_byte(g)
            self._write_byte(r)
            self._write_byte(b)
        self.pin.value(0)
        time.sleep_us(60)
        self._need_redraw = False

    def tick(self):
        if self.mode == "white":
            if self._need_redraw:
                v = self.brightness
                self._draw_static(v, v, v)
            return
        if self.mode == "off" or self.effect == "off":
            if self._need_redraw:
                self._draw_static(0, 0, 0)
            return
        if self.effect == "rainbow":
            self._tick_rainbow()
        elif self.effect == "breathing":
            self._tick_breathing()
        self._need_redraw = False

    def _tick_rainbow(self):
        t = time.ticks_ms()
        hue_base = (t % 30000) / 30000.0 * 255
        grb = bytearray(self.num_leds * 3)
        for i in range(self.num_leds):
            hue = int(hue_base + i * 255 // self.num_leds) % 256
            g, r, b = self._hsv_to_grb(hue, 255, self.brightness)
            grb[i*3] = g; grb[i*3+1] = r; grb[i*3+2] = b
        self._show(grb)

    def _tick_breathing(self):
        t = time.ticks_ms()
        phase = (t % 3000) / 3000.0
        val = int((math.sin(phase * 2 * math.pi) + 1) / 2 * self.brightness)
        r = (0xFF * val) // 255
        g = (0xAA * val) // 255
        b = (0x66 * val) // 255
        grb = bytearray(self.num_leds * 3)
        for i in range(self.num_leds):
            grb[i*3] = g; grb[i*3+1] = r; grb[i*3+2] = b
        self._show(grb)
