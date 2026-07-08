import os
import subprocess
import threading
import time
from sensor_listener.mqtt.base_cmd import BaseCommand


class SysCpuTemp(BaseCommand):
    """获取树莓派 CPU 温度"""

    def execute(self, args: str) -> str:
        try:
            # 读取 Linux 底层系统文件，最稳妥且无需装库
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_raw = f.read().strip()
                temp_celsius = float(temp_raw) / 1000.0
            return f"[OK] /sys.cpu.temp = CPU 温度: {temp_celsius:.1f}°C"
        except Exception as e:
            return f"[ERROR 500] 无法读取 CPU 温度: {str(e)}"


class SysMemInfo(BaseCommand):
    """获取内存使用情况 (RAM)"""

    def execute(self, args: str) -> str:
        try:
            # 调用 Linux 的 free 命令并解析输出
            result = subprocess.check_output("free -m | grep Mem", shell=True).decode('utf-8')
            parts = result.split()
            total, used, free = parts[1], parts[2], parts[3]
            return f"[OK] /sys.mem.info = 内存 (MB) -> 总计:{total}, 已用:{used}, 空闲:{free}"
        except Exception as e:
            return f"[ERROR 500] 无法读取内存信息: {str(e)}"


class SysDiskInfo(BaseCommand):
    """获取 SD 卡/硬盘的存储使用情况"""

    def execute(self, args: str) -> str:
        try:
            # 调用 Linux 的 df 命令查看根目录挂载点
            result = subprocess.check_output("df -h / | tail -1", shell=True).decode('utf-8')
            parts = result.split()
            total, used, avail, percent = parts[1], parts[2], parts[3], parts[4]
            return f"[OK] /sys.disk.info = 存储 (根目录) -> 总计:{total}, 已用:{used} ({percent}), 剩余:{avail}"
        except Exception as e:
            return f"[ERROR 500] 无法读取存储信息: {str(e)}"


class SysOsUptime(BaseCommand):
    """获取系统连续运行时间"""

    def execute(self, args: str) -> str:
        try:
            # 调用 uptime -p 获取易读的运行时间格式 (例如: up 2 hours, 15 minutes)
            uptime_str = subprocess.check_output("uptime -p", shell=True).decode('utf-8').strip()
            return f"[OK] /sys.os.uptime = 系统运行时间: {uptime_str}"
        except Exception as e:
            return f"[ERROR 500] 无法读取运行时间: {str(e)}"


class SysPowerReboot(BaseCommand):
    """安全重启树莓派"""

    def execute(self, args: str) -> str:
        # 1. 严格的安全校验，防止误触指令导致设备掉线
        if args.strip() != "confirm":
            return "[ERROR 422] 缺少安全确认参数。请发送完整指令: /sys.power.reboot confirm"

        # 2. 定义一个后台延时任务
        def delayed_reboot():
            time.sleep(2)  # 延时 2 秒，给 MQTT 充足的时间把下面的 [OK] 消息发给主机
            os.system("sudo reboot")

        # 3. 开启独立线程执行重启，不阻塞当前的主线程
        threading.Thread(target=delayed_reboot).start()

        return "[OK] /sys.power.reboot = 指令已确认，树莓派将在 2 秒后重启..."
