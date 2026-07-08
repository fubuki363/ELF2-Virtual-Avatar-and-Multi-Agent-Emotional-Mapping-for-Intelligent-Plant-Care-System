# boot.py — K230 上电自动启动脚本
# 将此文件放在 TF 卡根目录 /sdcard/boot.py
# 上电后 MicroPython 自动执行，启动传感器+控制+图传系统
import sys
sys.path.append('/sdcard/app')
import main
main.main()
