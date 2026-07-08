# config.py — K230 全局配置常量

# === WiFi ===
# ⚠️ 安全提示：请复制 config.example.py 为 config.py 并填入真实值
# 切勿将含真实密码的 config.py 提交到 Git！
WIFI_SSID = "your_wifi_ssid"
WIFI_PASSWORD = "your_wifi_password"

# === ELF2 上位机 ===
ELF2_HOSTNAME = "elf2-desktop"
ELF2_STATIC_IP = "10.17.67.79"  # mDNS 不可用时的静态 IP 回退
ELF2_SENSOR_PORT = 8259    # 上行: 传感器 UDP JSON
ELF2_CMD_PORT = 8260       # 下行: 控制命令 UDP JSON
ELF2_VIDEO_PORT = 6001     # 视频流 TCP

# === I2C 总线 (传感器) ===
I2C_BUS = 2
I2C_SCL = 11   # K230 IO11 → Header Pin 5
I2C_SDA = 12   # K230 IO12 → Header Pin 3
I2C_FREQ = 100000

# === I2C 传感器地址 ===
SHT35_ADDR = 0x44
CCS811_ADDR = 0x5A
BH1750_ADDR = 0x23

# === ADC 传感器 ===
ADC_GAS_CH = 0     # ADC0, Header Pin 32 → Mics5524
ADC_SOIL_CH = 1    # ADC1, Header Pin 36 → HW390

# === PWM 执行器 (IO#, PWM channel, Header Pin) ===
PWM_FAN_IO = 42          # IO42 → Header Pin 13
PWM_FAN_CH = 0
PWM_FAN_FREQ = 25000     # 25kHz (PC 风扇标准)

PWM_HEATER_IO = 43       # IO43 → Header Pin 15
PWM_HEATER_CH = 1
PWM_HEATER_FREQ = 1000   # 1kHz

PWM_PUMP_IO = 46         # IO46 → Header Pin 16
PWM_PUMP_CH = 2
PWM_PUMP_FREQ = 1000

PWM_HUMID_IO = 47        # IO47 → Header Pin 18
PWM_HUMID_CH = 3
PWM_HUMID_FREQ = 1000

# === WS2812B LED ===
LED_SPI_BUS = 0
LED_SPI_MOSI_IO = 16     # IO16 → Header Pin 19
LED_SPI_CLK_IO = 15      # IO15 → Header Pin 23
LED_SPI_BAUDRATE = 3200000  # 3.2MHz (WS2812B 时序: 每 bit=312.5ns)
LED_COUNT = 60
LED_COLOR_ORDER = "GRB"  # WS2812B 色序

# === 采样间隔 ===
SAMPLE_INTERVAL_MS = 1000
LED_FRAME_INTERVAL_MS = 20   # 50fps

# === Mics5524 分压补偿 ===
MICS5524_DIVIDER_RATIO = 1.5  # (10k+20k) / 20k

# === 视频流 ===
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 90
