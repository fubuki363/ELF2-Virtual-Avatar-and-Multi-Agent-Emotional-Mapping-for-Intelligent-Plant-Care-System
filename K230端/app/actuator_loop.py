# actuator_loop.py — Thread-3: LED 50fps 帧刷新 + PWM duty 更新
import time
from machine import FPIOA

from config import LED_FRAME_INTERVAL_MS
from drivers.fan import Fan
from drivers.heater import Heater
from drivers.pump import Pump
from drivers.humidifier import Humidifier
from drivers.ws2812b import WS2812B


def actuator_loop_thread(state):
    """Thread-3: 每 20ms 刷新 LED 效果帧 + 读共享状态更新 PWM"""

    # 初始化 FPIOA + 所有执行器 (上电默认关闭)
    fpioa = FPIOA()
    fan = Fan(fpioa)
    heater = Heater(fpioa)
    pump = Pump(fpioa)
    humidifier = Humidifier(fpioa)
    led = WS2812B(fpioa)

    pwms = [fan, heater, pump, humidifier]
    led.set_mode("effect", "rainbow", 128)

    print("[Actuator] Started (50fps LED + PWM)")
    print("[Actuator] LED mode=%s effect=%s brightness=%d" % (led.mode, led.effect, led.brightness))

    # 记录上次 PWM 值以跳过无变化更新
    last_duty = [0, 0, 0, 0]
    frame_count = 0

    while True:
        frame_start = time.ticks_ms()

        # 读 PWM 状态 + 更新 (仅在变化时写 PWM)
        state.lock_actuator.acquire()
        duty = list(state.actuator_duty)
        state.lock_actuator.release()

        for i in range(4):
            if duty[i] != last_duty[i]:
                pwms[i].set(duty[i])
                last_duty[i] = duty[i]

        # 读 LED 状态 + tick
        state.lock_led.acquire()
        led_mode = state.led_mode
        led_effect = state.led_effect
        led_brightness = state.led_brightness
        need_update = state.led_need_update
        if need_update:
            state.led_need_update = False
        state.lock_led.release()

        if need_update:
            led.set_mode(led_mode, led_effect, led_brightness)

        led.tick()

        # DEBUG: 前 3 帧打印确认 tick 运行
        if frame_count < 3:
            print("[Actuator] Frame %d: tick OK, mode=%s, effect=%s" % (frame_count, led.mode, led.effect))
        frame_count += 1

        # 帧率控制
        elapsed = time.ticks_diff(time.ticks_ms(), frame_start)
        sleep_ms = max(0, LED_FRAME_INTERVAL_MS - elapsed)
        if sleep_ms > 0:
            time.sleep_ms(sleep_ms)
