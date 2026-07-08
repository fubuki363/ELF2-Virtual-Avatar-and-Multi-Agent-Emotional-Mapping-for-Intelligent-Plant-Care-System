# wifi_mdns.py — WiFi STA 连接 + ELF2 IP 解析
import network
import socket
import time

_elf2_cache = None  # mDNS 解析缓存


def connect_wifi(ssid, password):
    """连接 WiFi 热点，阻塞直到成功。返回 WLAN 对象。"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        print("[WiFi] Already connected:", wlan.ifconfig())
        return wlan

    print(f"[WiFi] Connecting to '{ssid}'...")
    wlan.connect(ssid, password)

    timeout = 30
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
        print(f"  waiting... ({timeout}s)")

    if wlan.isconnected():
        ip, mask, gw, dns = wlan.ifconfig()
        print(f"[WiFi] Connected! IP: {ip}")
    else:
        print("[WiFi] FAILED — timeout after 30s")

    return wlan


def resolve_elf2(hostname):
    """解析 ELF2 主机名 → IP，优先 .local mDNS，失败则用缓存。"""
    global _elf2_cache

    # 尝试 mDNS: hostname.local
    mdns_name = hostname + ".local"
    try:
        addr_info = socket.getaddrinfo(mdns_name, 8259)
        ip = addr_info[0][-1][0]
        _elf2_cache = ip
        print(f"[mDNS] {mdns_name} → {ip}")
        return ip
    except OSError as e:
        print(f"[mDNS] Resolution failed for {mdns_name}: {e}")

    # 回退到缓存
    if _elf2_cache:
        print(f"[mDNS] Using cached IP: {_elf2_cache}")
        return _elf2_cache

    # 最后一次尝试: 直接 hostname (可能已在 /etc/hosts 或 DNS)
    try:
        addr_info = socket.getaddrinfo(hostname, 8259)
        ip = addr_info[0][-1][0]
        _elf2_cache = ip
        print(f"[mDNS] {hostname} → {ip}")
        return ip
    except OSError:
        print(f"[mDNS] CRITICAL: Cannot resolve {hostname}")
        return None
