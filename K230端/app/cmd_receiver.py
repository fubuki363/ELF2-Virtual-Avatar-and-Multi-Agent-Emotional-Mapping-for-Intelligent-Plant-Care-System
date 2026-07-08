# cmd_receiver.py — Thread-2: UDP:8260 命令接收 + stream-style JSON 解析
import socket
from config import ELF2_CMD_PORT

MAX_CMD_PER_PACKET = 8


def cmd_receiver_thread(state):
    """Thread-2: 非阻塞 UDP 监听 8260 → JSON 解析 → 写共享状态"""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', ELF2_CMD_PORT))
    sock.settimeout(0.05)  # 50ms 超时 → 非阻塞轮询

    print(f"[CmdReceiver] Listening UDP:{ELF2_CMD_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
        except OSError:
            continue  # 超时

        if not data:
            continue

        cmds = _parse_cmd_json(data.decode())
        for cmd in cmds:
            _apply_cmd(cmd, state)


def _parse_cmd_json(text):
    """Stream-style 解析 [{"d":"fan","v":80},...] 返回 Cmd dict 列表"""
    cmds = []
    i = 0
    n = len(text)

    while i < n and len(cmds) < MAX_CMD_PER_PACKET:
        # 找 '{'
        while i < n and text[i] != '{':
            i += 1
        if i >= n:
            break

        # 提取完整 {} 对象
        depth = 0
        start = i
        while i < n:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1

        obj = _parse_one_cmd(text[start:i])
        if obj:
            cmds.append(obj)
    return cmds


def _parse_one_cmd(s):
    """从 {"d":"fan","v":80,"mode":"effect"...} 提取字段"""
    cmd = {}

    # 提取 "d" 值
    cmd['d'] = _extract_str(s, 'd')

    # 提取 "v" 值
    v_str = _extract_str(s, 'v')
    if v_str:
        try:
            cmd['v'] = int(float(v_str))
        except ValueError:
            pass

    # 提取 "mode" 值
    mode = _extract_str(s, 'mode')
    if mode:
        cmd['mode'] = mode

    # 提取 "effect" 值
    effect = _extract_str(s, 'effect')
    if effect:
        cmd['effect'] = effect

    # 提取 "brightness" 值
    b_str = _extract_str(s, 'brightness')
    if b_str:
        try:
            cmd['brightness'] = int(float(b_str))
        except ValueError:
            pass

    return cmd if 'd' in cmd else None


def _extract_str(s, key):
    """从 JSON 片段提取字符串字段值"""
    search = f'"{key}"'
    idx = s.find(search)
    if idx < 0:
        return None

    # 跳过 key + 引号 + 冒号 + 空白
    pos = idx + len(search)
    while pos < len(s) and s[pos] in ' \t\n\r:':
        pos += 1

    if pos >= len(s):
        return None

    # 字符串值: "value"
    if s[pos] == '"':
        end = s.find('"', pos + 1)
        if end >= 0:
            return s[pos+1:end]
    else:
        # 数字值
        end = pos
        while end < len(s) and s[end] not in ' \t\n\r,}':
            end += 1
        return s[pos:end]

    return None


def _apply_cmd(cmd, state):
    """将解析后的命令写入共享状态"""
    d = cmd.get('d', '')

    # PWM 设备
    idx_map = {'fan': 0, 'heater': 1, 'pump': 2, 'humidifier': 3}
    if d in idx_map:
        v = max(0, min(100, cmd.get('v', 0)))
        state.lock_actuator.acquire()
        state.actuator_duty[idx_map[d]] = v
        state.lock_actuator.release()
        return

    # LED 设备
    if d == 'led':
        state.lock_led.acquire()
        if 'mode' in cmd:
            state.led_mode = cmd['mode']
        if 'effect' in cmd:
            state.led_effect = cmd['effect']
        if 'brightness' in cmd:
            state.led_brightness = max(0, min(255, cmd['brightness']))
        state.led_need_update = True
        state.lock_led.release()
        return

    # 未知设备: 静默忽略
