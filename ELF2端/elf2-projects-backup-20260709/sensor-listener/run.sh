#!/bin/bash
fuser -k 8259/udp 2>/dev/null
sleep 0.5
cd /home/elf/sensor-listener
clear
echo "====================================="
echo "  智能温室控制器 Phase A+B+C"
echo "  传感器: UDP 8259 | 视频: TCP 6001"
echo "  控制: UDP 8260 | MQTT: EMQX Cloud"
echo "====================================="
echo ""
python3 -m sensor_listener.main --verbose
echo ""
echo "控制器已停止。按 Enter 关闭窗口..."
read
