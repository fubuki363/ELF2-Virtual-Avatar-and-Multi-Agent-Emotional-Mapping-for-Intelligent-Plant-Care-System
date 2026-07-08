# shared_state.py — 线程安全共享状态
import _thread


class SharedState:
    """4 线程间共享状态，通过 _thread.allocate_lock() 保护"""

    def __init__(self):
        # === 执行器 PWM 状态 ===
        self.lock_actuator = _thread.allocate_lock()
        self.actuator_duty = [0, 0, 0, 0]  # [fan, heater, pump, humidifier] 0-100

        # === LED 状态 ===
        self.lock_led = _thread.allocate_lock()
        self.led_mode = "effect"        # "effect" | "white" | "off"
        self.led_effect = "rainbow"     # 当前 effect 名称
        self.led_brightness = 128       # 全局亮度 0-255
        self.led_need_update = True     # True → actuator_loop 重绘静态帧
