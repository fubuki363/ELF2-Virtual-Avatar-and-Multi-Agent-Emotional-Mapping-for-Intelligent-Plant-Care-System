#!/bin/bash
# 先杀掉旧的监听进程
fuser -k 8259/udp 2>/dev/null
sleep 0.5
# 启动监听器
cd /home/elf/sensor-listener
clear
echo "====================================="
echo "  ESP32-C3 传感器数据监听器"
echo "  监听端口: 8259"
echo "  关闭此窗口即停止监听"
echo "====================================="
echo ""
python3 udp_sensor_listener.py --verbose
echo ""
echo "监听已停止。按 Enter 关闭窗口..."
read
