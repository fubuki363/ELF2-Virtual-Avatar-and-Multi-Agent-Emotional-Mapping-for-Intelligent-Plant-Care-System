# test_integration.py — 端到端集成测试 (手动运行)
import sys
sys.path.append('/sdcard/app')

from shared_state import SharedState
state = SharedState()

# Test 1: 共享状态读写
print("--- Test 1: Shared State ---")
state.lock_actuator.acquire()
state.actuator_duty = [50, 30, 20, 10]
state.lock_actuator.release()
assert state.actuator_duty == [50, 30, 20, 10]
print("PASS")

# Test 2: 传感器 JSON 格式
print("--- Test 2: Sensor JSON ---")
import ujson
data = {"t": 26.3, "h": 54.8, "light": 320.5, "gas": 0.85, "soil": 2200, "ts": 12345}
json_str = ujson.dumps(data)
assert len(json_str) > 0
print(json_str)
print("PASS")

# Test 3: 命令解析
print("--- Test 3: Command Parsing ---")
from cmd_receiver import _parse_cmd_json
cmds = _parse_cmd_json('[{"d":"fan","v":80},{"d":"led","mode":"effect","effect":"rainbow","brightness":120}]')
assert len(cmds) == 2
assert cmds[0]['d'] == 'fan'
assert cmds[0]['v'] == 80
assert cmds[1]['d'] == 'led'
assert cmds[1]['effect'] == 'rainbow'
print("PASS")

# Test 4: 命令路由
print("--- Test 4: Command Routing ---")
from cmd_receiver import _apply_cmd
_apply_cmd({'d': 'fan', 'v': 60}, state)
state.lock_actuator.acquire()
assert state.actuator_duty[0] == 60
state.lock_actuator.release()

_apply_cmd({'d': 'led', 'mode': 'white', 'brightness': 200}, state)
state.lock_led.acquire()
assert state.led_mode == 'white'
assert state.led_brightness == 200
state.lock_led.release()
print("PASS")

# Test 5: CRC-8
print("--- Test 5: SHT35 CRC-8 ---")
from drivers.sht35 import SHT35
# 测试向量: SHT35 datasheet
class MockI2C:
    pass
sht = SHT35(None)
assert sht._crc8(bytes([0xBE, 0xEF])) == 0x92
print("PASS")

print("\n=== ALL TESTS PASSED ===")
