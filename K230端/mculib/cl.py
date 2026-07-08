import socket
import network
import time
import uerrno
import uhashlib

SECRET_KEY = "my_secret_key"  # 与PC端相同的密钥

class PC_Discoverer:
    def __init__(self, is_wlan=True, ssid="Canaan", password="Canaan314", ip=None, mask="255.255.255.0", gate="0.0.0.0", dns="8.8.8.8",
                 udp_port=5005, timeout=100):
        self.udp_port = udp_port
        self.timeout = timeout
        self.ip = None
        self.pc_ip = None
        self.udp_sock = None

        start_time = time.time()

        if is_wlan:
            sta = network.WLAN(network.STA_IF)
            sta.active(True)
            sta.connect(ssid, password)
            print("尝试连接 WiFi...")

            while not sta.isconnected():
                if time.time() - start_time > self.timeout:
                    raise RuntimeError("WLAN 连接超时")
                time.sleep_ms(100)

            # 等待 DHCP 分配有效 IP（isconnected=True 时 IP 可能仍为 0.0.0.0）
            while True:
                self.ip = sta.ifconfig()[0]
                if self.ip != '0.0.0.0':
                    break
                if time.time() - start_time > self.timeout:
                    raise RuntimeError("WLAN DHCP 超时，未获取到有效 IP")
                time.sleep_ms(100)

            print(f"WiFi 连接成功！ IP: {self.ip}")
        else:
            lan = network.LAN()
            if ip:
                lan.ifconfig((ip, mask, gate, dns))
            lan.active(True)
            print("尝试连接 LAN...")

            while lan.ifconfig()[0] == '0.0.0.0':
                if time.time() - start_time > self.timeout:
                    raise RuntimeError("LAN activation timeout")
                time.sleep_ms(100)

            self.ip = lan.ifconfig()[0]
            print(f"LAN activated! IP: {self.ip}")

    def _create_udp_socket(self):
        """Create UDP socket for broadcast reception"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('0.0.0.0', self.udp_port))
        sock.setblocking(True)
        sock.settimeout(0.1)
        return sock

    def discover_pc(self, timeout=10):
        """Discover PC with signature verification and return its IP"""
        if self.udp_sock is None:
            self.udp_sock = self._create_udp_socket()

        print("Listening for PC broadcast...")
        start_time = time.time()
        header = b"PC_DISC"
        header_len = len(header)

        while time.time() - start_time < timeout:
            try:
                data, addr = self.udp_sock.recvfrom(1024)
                if data is None:
                    continue
                # 最小长度检查: 头(7) + IP长度(1) + IP(>=7) + 随机数(4) + 签名(32) = 至少51
                if len(data) < 51:
                    continue

                # 检查消息头
                if data[:header_len] != header:
                    print("消息头无效")
                    continue

                # 解析IP长度和IP地址
                ip_len = data[header_len]  # IP地址长度
                ip_start = header_len + 1
                ip_end = ip_start + ip_len
                pc_ip_str = data[ip_start:ip_end].decode()
                print(f"解析到PC IP: {pc_ip_str}")

                # 提取其他组件
                random_pad = data[ip_end:ip_end+4]
                received_sign = data[ip_end+4:ip_end+36]

                # 计算本地签名（使用消息中的IP）
                sign_data = pc_ip_str.encode() + random_pad + SECRET_KEY.encode()
                obj = uhashlib.sha256()
                obj.update(sign_data)
                computed_sign = obj.digest()

                # 验证签名
                if computed_sign == received_sign:
                    self.pc_ip = pc_ip_str
                    print(f"Verified PC at: {self.pc_ip}")
                    return self.pc_ip
                else:
                    print("签名验证失败")

            except OSError as e:
                if e.args[0] not in (uerrno.EAGAIN, uerrno.EWOULDBLOCK):
                    print("UDP error:", e)

        print("PC discovery timeout")
        return None

    def close(self):
        """Close network resources"""
        if self.udp_sock:
            self.udp_sock.close()
            self.udp_sock = None
        print("Discovery resources closed")

# 使用示例
if __name__ == "__main__":
    discoverer = PC_Discoverer(is_wlan=False, ip="192.168.137.2", timeout=999)

    # 尝试发现PC
    pc_ip = discoverer.discover_pc(timeout=15)  # 修正参数名
    if pc_ip:
        print(f"Discovered PC at: {pc_ip}")
    else:
        print("Failed to discover PC")

    discoverer.close()
