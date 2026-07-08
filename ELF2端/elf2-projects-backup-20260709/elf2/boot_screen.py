#!/usr/bin/env python3
"""TJC3224T120_011 科技感开机欢迎界面 — ELF2 / RK3588"""
import serial
import time

PORT = "/dev/ttyUSB0"
BAUD = 115200
W, H = 320, 240

# TJC 串口指令都以 \xff\xff\xff 结尾
END = b'\xff\xff\xff'


def cmd(data: str):
    screen.write((data + "\xff\xff\xff").encode("ascii", errors="ignore"))


def fill(x, y, w, h, color):
    cmd(f"fill {x},{y},{w},{h},{color}")


def xstr(x, y, w, h, font, fg, bg, ax, ay, text):
    cmd(f"xstr {x},{y},{w},{h},{font},{fg},{bg},{ax},{ay},{text}")


# ==========================================
print(f"[Boot] 打开串口 {PORT} @ {BAUD}...")
screen = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(1.2)

# ── 阶段一：全黑 ──
cmd("cls 0")
time.sleep(0.15)

# ── 阶段二：四角扫描光效 ──
print("[Boot] 扫描线")
for t in range(0, 50, 3):
    fill(0, 0, t, 2, 2016)           # 左上横
    fill(0, 0, 2, t, 2016)           # 左上竖
    fill(W - t, 0, t, 2, 2016)       # 右上横
    fill(W - 2, 0, 2, t, 2016)       # 右上竖
    fill(0, H - 2, t, 2, 2016)       # 左下横
    fill(0, H - t, 2, t, 2016)       # 左下竖
    fill(W - t, H - 2, t, 2, 2016)   # 右下横
    fill(W - 2, H - t, 2, t, 2016)   # 右下竖
    time.sleep(0.012)

# 完整绿色边框
fill(0,   0,   W, 2, 2016)
fill(0,   0,   2, H, 2016)
fill(W-2, 0,   2, H, 2016)
fill(0,   H-2, W, 2, 2016)
time.sleep(0.3)

# 内框细线
fill(6, 6, W-12, 1, 8608)
fill(6, 6, 1, H-12, 8608)
fill(W-7, 6, 1, H-12, 8608)
fill(6, H-7, W-12, 1, 8608)
time.sleep(0.2)

# ── 阶段三：标题 ──
print("[Boot] 标题")
xstr(16, 14, 140, 18, 0, 2016, 0, 0, 0, "RK3588 // ELF2")
time.sleep(0.4)
xstr(10, 50, W-20, 50, 4, 65535, 0, 1, 1, "SYSTEM BOOT")
time.sleep(0.6)

# ── 阶段四：进度条 ──
print("[Boot] 进度条")
bar_y = H - 40
bar_x = 20
bar_w = W - 40
bar_h = 10
fill(bar_x, bar_y, bar_w, bar_h, 4256)

steps = [
    (20, "INIT MEMORY..."),
    (40, "LOAD KERNEL..."),
    (55, "START SENSORS..."),
    (70, "CONNECT MQTT..."),
    (85, "AI ENGINE ONLINE..."),
    (100, "OXALIS READY"),
]

for pct, label in steps:
    fill_w = int(bar_w * pct / 100)
    fill(bar_x, bar_y, fill_w, bar_h, 2016)
    xstr(bar_x, bar_y - 20, bar_w, 16, 0, 2016, 0, 0, 0, label)
    time.sleep(0.5 if pct < 100 else 0.8)

# ── 阶段五：信息行 ──
xstr(14, H-14, W-28, 14, 0, 8608, 0, 0, 0, "CPU:RK3588 | NPU:6T | MEM:8G | ELF2")
time.sleep(0.6)

# ── 阶段六：READY 闪烁 ──
for _ in range(4):
    xstr(W//2-45, 120, 90, 22, 4, 2016, 0, 1, 1, "> READY <")
    time.sleep(0.35)
    xstr(W//2-45, 120, 90, 22, 4, 0, 0, 1, 1, "> READY <")
    time.sleep(0.35)

xstr(W//2-45, 120, 90, 22, 4, 2016, 0, 1, 1, "> READY <")
time.sleep(1.5)

# ── 完成：待机画面 ──
cmd("cls 0")
time.sleep(0.1)
xstr(12, 16, W-24, 18, 0, 2016, 0, 0, 0, "OXALIS ELF2 : ONLINE")
xstr(12, H-16, W-24, 14, 0, 8608, 0, 0, 0, "awaiting voice input...")

screen.close()
print("[Boot] 完成")
