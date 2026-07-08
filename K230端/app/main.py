# main.py — K230 传感器+控制+图传 系统入口 (调试版)
import sys
import time
import _thread
import network
import socket

sys.path.append('/sdcard/app')
sys.path.append('/sdcard/app/libs')

from config import WIFI_SSID, WIFI_PASSWORD, ELF2_HOSTNAME, ELF2_SENSOR_PORT, ELF2_STATIC_IP
from shared_state import SharedState


# ============================================================
#  DEBUG: 设为 True 开启详细调试输出
# ============================================================
DEBUG = True


def _mac_str(wlan):
    """获取 MAC 地址字符串 (MicroPython 兼容)"""
    try:
        mac = wlan.config('mac')
        return ':'.join('%02x' % b for b in mac)
    except:
        return 'unknown'


def _scan_ssid(n):
    """从 scan 结果提取 SSID (兼容 K230 属性对象和 ESP32 元组)"""
    try:
        # K230: rt_wlan_info 对象, 用属性访问
        s = n.ssid
        return s.decode() if isinstance(s, bytes) else str(s)
    except:
        # ESP32: 元组, n[0] 是 SSID
        try:
            s = n[0]
            return s.decode() if isinstance(s, bytes) else str(s)
        except:
            return '?'


def _scan_rssi(n):
    """从 scan 结果提取 RSSI (兼容 K230 属性对象和 ESP32 元组)"""
    try:
        return n.rssi
    except:
        try:
            return n[3] if len(n) > 3 else 0
        except:
            return 0


def debug_scan_wifi():
    """扫描附近 WiFi，列出所有可见网络"""
    print("\n[DEBUG] Scanning WiFi networks...")
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        nets = wlan.scan()
        if nets:
            print("[DEBUG] Found %d network(s):" % len(nets))
            for n in nets:
                ssid = _scan_ssid(n)
                rssi = _scan_rssi(n)
                print("         SSID='%s' RSSI=%s" % (ssid, rssi))
        else:
            print("[DEBUG] No WiFi networks found! Check antenna.")
    except Exception as e:
        print("[DEBUG] WiFi scan failed:", e)


def debug_connect_wifi(ssid, password):
    """WiFi 连接 (调试版) — 打印每一步详细信息"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print("[WiFi] Interface active:", wlan.active())
    print("[WiFi] Current MAC:", _mac_str(wlan))

    if wlan.isconnected():
        print("[WiFi] Already connected:", wlan.ifconfig())
        return wlan

    # 先扫描确认目标网络存在
    print("[WiFi] Scanning for '%s'..." % ssid)
    found = False
    scan_results = wlan.scan() or []
    for n in scan_results:
        name = _scan_ssid(n)
        if name == ssid:
            found = True
            rssi = _scan_rssi(n)
            print("[WiFi] Found target! SSID='%s' RSSI=%s" % (name, rssi))
            break
    if not found:
        print("[WiFi] WARNING: '%s' not found in scan results" % ssid)

    print("[WiFi] Connecting to '%s'..." % ssid)
    wlan.connect(ssid, password)
    print("[WiFi] connect() returned, waiting for DHCP...")

    timeout = 30
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
        status = wlan.status()
        elapsed = 30 - timeout
        # K230 的 network.STAT_* 常量名可能不同，统一用数字
        # 常见: 0=IDLE, 1=CONNECTING, 2=WRONG_PWD, 3=NO_AP, 4=FAIL, 5=GOT_IP
        print("  [%ds] status=%d" % (elapsed, status))

        if status == 2:   # WRONG_PASSWORD
            print("[WiFi] FATAL: Wrong password!")
            break
        if status == 3:   # NO_AP_FOUND
            print("[WiFi] FATAL: AP not found!")
            break

    print("[WiFi] Final status:", wlan.status())
    if wlan.isconnected():
        ip, mask, gw, dns = wlan.ifconfig()
        print("[WiFi] ✓ Connected!")
        print("       IP:      %s" % ip)
        print("       Netmask: %s" % mask)
        print("       Gateway: %s" % gw)
        print("       DNS:     %s" % dns)
    else:
        print("[WiFi] ✗ FAILED after 30s — status=%d" % wlan.status())

    return wlan


def debug_resolve_elf2(hostname):
    """ELF2 IP 解析 (调试版)"""
    print("\n[ELF2] Resolving '%s'..." % hostname)

    # Step A: mDNS (.local)
    mdns_name = hostname + ".local"
    print("[ELF2] Step A: mDNS %s" % mdns_name)
    try:
        addr_info = socket.getaddrinfo(mdns_name, ELF2_SENSOR_PORT)
        ip = addr_info[0][-1][0]
        print("[ELF2] ✓ mDNS resolved: %s -> %s" % (mdns_name, ip))
        return ip
    except OSError as e:
        print("[ELF2] mDNS failed:", e)

    # Step B: 直接 DNS / /etc/hosts
    print("[ELF2] Step B: DNS %s" % hostname)
    try:
        addr_info = socket.getaddrinfo(hostname, ELF2_SENSOR_PORT)
        ip = addr_info[0][-1][0]
        print("[ELF2] ✓ DNS resolved: %s -> %s" % (hostname, ip))
        return ip
    except OSError as e:
        print("[ELF2] DNS failed:", e)

    # Step C: 尝试常见后缀
    for suffix in ['', '.local', '.lan', '.home']:
        name = hostname + suffix
        print("[ELF2] Step C: Trying %s" % name)
        try:
            addr_info = socket.getaddrinfo(name, ELF2_SENSOR_PORT)
            ip = addr_info[0][-1][0]
            print("[ELF2] ✓ Resolved: %s -> %s" % (name, ip))
            return ip
        except OSError:
            pass

    # Step D: 静态 IP 回退
    if ELF2_STATIC_IP:
        print("[ELF2] Step D: Using static IP %s" % ELF2_STATIC_IP)
        return ELF2_STATIC_IP

    print("[ELF2] ✗ All resolution methods failed")
    print("[ELF2] HINT: Set ELF2_STATIC_IP in config.py")
    return None


def main():
    print("\n" + "=" * 60)
    print("  K230 Sensor + Actuator + Video System")
    print("  DEBUG MODE")
    print("=" * 60)

    # === DEBUG: 系统信息 ===
    import os
    print("\n[DEBUG] uname:", os.uname())

    # === DEBUG: WiFi 环境扫描 ===
    debug_scan_wifi()

    # === Step 1: WiFi 连接 ===
    print("\n" + "-" * 40)
    print("[Main] Step 1: Connecting WiFi")
    print("       SSID: '%s'" % WIFI_SSID)
    print("       PWD:  %s" % ('*' * len(WIFI_PASSWORD)))
    print("-" * 40)

    wlan = debug_connect_wifi(WIFI_SSID, WIFI_PASSWORD)

    if not wlan.isconnected():
        print("\n[Main] WiFi failed. Staying alive for debug — check terminal output above.")
        print("[Main] Try: import network; w=network.WLAN(0); w.active(1); w.scan()")
        while True:
            time.sleep(10)
            print("[Main] Still waiting... WiFi status=%d" % wlan.status())

    # === Step 2: ELF2 IP 解析 ===
    print("\n" + "-" * 40)
    print("[Main] Step 2: Resolving ELF2")
    print("-" * 40)

    elf2_ip = debug_resolve_elf2(ELF2_HOSTNAME)

    if elf2_ip is None:
        print("\n[Main] Cannot resolve ELF2. Entering fallback mode.")
        print("[Main] Sensor data will be printed to console AND sent to ELF2 when available.")
        print("[Main] To set ELF2 IP manually, edit config.py or /etc/hosts")
        # 不重启 — 留在调试模式，传感器数据本地打印
        elf2_ip = "0.0.0.0"  # dummy, UDP send 会静默失败但本地打印继续

    # === Step 3: 创建共享状态 ===
    print("\n" + "-" * 40)
    print("[Main] Step 3: SharedState")
    print("-" * 40)
    state = SharedState()
    print("[Main] SharedState created OK")

    # === Step 4: 启动线程 (视频线程可选) ===
    print("\n" + "-" * 40)
    print("[Main] Step 4: Starting threads")
    print("-" * 40)

    from sensor_loop import sensor_loop_thread
    from cmd_receiver import cmd_receiver_thread
    from actuator_loop import actuator_loop_thread

    _thread.start_new_thread(sensor_loop_thread, (state, elf2_ip))
    print("  [OK] Thread-1: SensorLoop started (prints to console)")

    _thread.start_new_thread(cmd_receiver_thread, (state,))
    print("  [OK] Thread-2: CmdReceiver started")

    _thread.start_new_thread(actuator_loop_thread, (state,))
    print("  [OK] Thread-3: ActuatorLoop started")

    # 视频线程仅在 WiFi 正常且摄像头就绪时启动
    try:
        from video_stream import video_stream_thread
        _thread.start_new_thread(video_stream_thread, (elf2_ip,))
        print("  [OK] Thread-4: VideoStream started")
    except Exception as e:
        print("  [SKIP] Thread-4: VideoStream —", e)

    print("\n" + "=" * 60)
    print("  SYSTEM READY")
    print("=" * 60)
    print("  WiFi SSID:  %s" % WIFI_SSID)
    print("  K230  IP:   %s" % wlan.ifconfig()[0])
    print("  ELF2  IP:   %s" % elf2_ip)
    print("  Sensor ->   %s:8259 (UDP) + console" % elf2_ip)
    print("  Command <-  %s:8260 (UDP)" % elf2_ip)
    print("  Video  ->   %s:6001 (TCP)" % elf2_ip)
    print("=" * 60)
    print("  Watch terminal for sensor data every 1s")
    print("=" * 60 + "\n")

    # === Step 5: 主线程保活 ===
    last_status = 0
    while True:
        time.sleep(5)
        now = time.ticks_ms()

        if time.ticks_diff(now, last_status) >= 15000:  # 15s status
            last_status = now
            is_connected = wlan.isconnected()
            if is_connected:
                ip, mask, gw, dns = wlan.ifconfig()
                print("\n[STATUS %ds] WiFi=OK  IP=%s  GW=%s" % (now // 1000, ip, gw))
            else:
                print("\n[STATUS %ds] WiFi=DOWN  status=%d" % (now // 1000, wlan.status()))

        if not wlan.isconnected():
            print("[Main] WiFi lost, reconnecting...")
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            for _ in range(15):
                time.sleep(1)
                if wlan.isconnected():
                    print("[Main] WiFi restored:", wlan.ifconfig()[0])
                    break


if __name__ == "__main__":
    main()
