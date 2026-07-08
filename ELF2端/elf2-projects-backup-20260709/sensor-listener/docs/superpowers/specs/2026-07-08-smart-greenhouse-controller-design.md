# Smart Greenhouse Controller — Design Spec

**Date:** 2026-07-08
**Status:** approved

## Overview

将现有 UDP 传感器监听器扩展为智能温室控制系统：数据分析、自动控制、LLM 决策顾问、视频流 YOLO 植物检测、MQTT 云端指令路由。

- Language: Python 3.10+
- Architecture: asyncio + threading 混合（主线程 asyncio，视频/MQTT 独立线程）
- Directory: `sensor_listener/`（多模块 package）

## Architecture

```
sensor_listener/
├── __init__.py
├── main.py                  CLI + asyncio 启动 + 线程管理
├── protocol.py              SensorProtocol (UDP:8259 收 + UDP:8260 发)
├── display.py               CsvWriter + DisplayManager + 格式化函数
├── analysis.py              AnalysisEngine (健康指数/趋势/基线/事件日志)
├── control.py               ControlEngine (本地规则 + LLM顾问 + K230指令)
├── llm_advisor.py           LLMAdvisor (DeepSeek API)
├── video/
│   ├── __init__.py
│   ├── receiver.py          TCP:6001 服务器 (移植自 pc/lib/receiver.py)
│   ├── h265.py              HEVC 解码 → OpenCV BGR (移植自 pc/lib/h265.py)
│   └── yolo_detector.py     YOLOv5 叶片/花检测 (新增)
├── mqtt/
│   ├── __init__.py
│   ├── subscriber.py        MQTT 客户端 + 指令路由 (移植自 Connect/subscriber.py)
│   ├── commands.json        13条指令路由表
│   ├── base_cmd.py          指令基类
│   ├── cmd_sensor.py        传感器查询 (改读共享sensor_state)
│   ├── cmd_file.py          文件传输
│   └── cmd_sys.py           系统查询
└── best.pt                  YOLOv5 模型文件
```

## Data Flow

```
K230:8259 ──UDP──► SensorProtocol ──parsed dict──┬──► DisplayManager (终端)
                                                  ├──► CsvWriter (CSV)
                                                  ├──► AnalysisEngine (健康/趋势/基线)
                                                  └──► ControlEngine ──► LLMAdvisor
                                                       │
                                                  K230:8260 (UDP指令)

K230:6001 ──TCP──► DataReceiver ──H265──► VideoStreamHandler ──► YoloDetector
                                                    │                 │
                                              OpenCV 帧 (可选显示)   检测结果 → sensor_state

EMQX Cloud ──MQTT──► MQTT subscriber ──cmd_queue──► main loop ──► cmd_*.execute()
                                                       │
                                                  rpi5/cloud/data (发布结果/通知)
```

## Thread Model

| 线程 | 职责 | 通信方式 |
|------|------|---------|
| 主线程 (asyncio) | UDP收发 + 分析 + 控制 + 终端显示 | — |
| 视频线程 | TCP:6001 + H265解码 + YOLO推理 | sensor_state (Lock) |
| MQTT 线程 (paho) | EMQX 收发 + 指令路由 | cmd_queue (Queue) |

停止顺序：Ctrl+C → MQTT disconnect → 视频线程 join → asyncio shutdown

---

## Module: AnalysisEngine (`analysis.py`)

纯计算，无 I/O，~200 行。

### Plant Health Score

每个传感器映射到 0-25 分，满分 100：

| 传感器 | 理想区间 | 公式 |
|--------|---------|------|
| 温度 t | 18-28°C | max(0, 25 - abs(t-23)*2.5) |
| 湿度 h | 50-80% | max(0, 25 - abs(h-65)*1.7) |
| 光照 light | 200-800 lux | max(0, 25 - abs(light-500)*0.05) |
| 土壤 soil | 1000-2500 | max(0, 25 - abs(soil-1750)*0.017) |

### Trend Detection

维护 300 秒滑动窗口。计算当前值 vs 窗口头部的变化：

```
温度: 26.3°C ↗ +1.2°C/5min
```

### Adaptive Baseline

24 小时滚动统计（均值 ± 2σ），当前值与同时段历史基线比较：

```
温度: 26.3°C (基线 24.1±3.2, 正常)
土壤: 2800 (基线 1800±400, ⚠ 偏离)
```

### Decision Logger

环形缓冲 100 条，Ctrl+C 时写入 `decision_log.json`：

```
[14:32:05] 开风扇 80% | 触发: 温度 31.2°C > 阈值 30°C
[14:35:22] 开水泵 30% | 触发: 土壤 3100 > 阈值 2500, LLM确认
```

---

## Module: ControlEngine (`control.py`)

~150 行。

### Local Rules (毫秒响应)

| 优先级 | 条件 | 动作 |
|--------|------|------|
| P0 | t > 35°C | 风扇 100% |
| P1 | t > 30°C | 风扇 50-80% (按超出比例) |
| P1 | soil > 2500 | 水泵 30% |
| P2 | light < 50 lux | LED 白光 150 |
| P2 | h < 45% | 加湿器 50% |
| P3 | soil < 800 | 关水泵 |

### LLM Trigger Gates (事件触发)

| 条件 | LLM 决策内容 |
|------|-------------|
| soil > 2500 持续 10s | 是否浇水、浇多少 |
| t 连续5分钟上升 >3°C | 是否开风扇/关加热 |
| 健康指数 <60 持续1分钟 | 综合诊断 |

### Anti-Flutter

同一设备两次指令间隔 ≥30s。P0 不受此限。

### K230 UDP Control

发送到 K230_IP:8260，格式：
```json
[{"d":"fan","v":80}]
```
IP 从 SensorProtocol 收到的包源地址获取。

---

## Module: LLMAdvisor (`llm_advisor.py`)

~100 行。

- API: `POST https://api.deepseek.com/v1/chat/completions`
- Model: `deepseek-chat`
- API Key: `DEEPSEEK_API_KEY` (环境变量)
- Timeout: 3s (asyncio.wait_for)
- Fallback: 超时/失败 → 降级为本地规则
- 连续失败 3 次 → 暂停 LLM 5 分钟

### Safety Constraints (LLM 无法绕过)

| 设备 | 最大 | 原因 |
|------|------|------|
| pump | 50% | 防过浇 |
| heater | 80% | 防过热 |
| humidifier | 80% | 防过湿 |
| led | 200 brightness | 防功耗 |

---

## Module: Video + YOLO (`video/`)

### receiver.py (移植)
- TCP:6000 服务器
- 多线程 accept
- 处理视频帧和文本消息
- 双向通信（可发消息回 K230）

### h265.py (移植)
- PyAV (av) 解码 HEVC
- 输出 OpenCV BGR numpy 数组
- 帧队列（maxsize=2，丢旧帧）

### yolo_detector.py (新增)
- YOLOv5 推理（best.pt, 2 classes: leaf/flower）
- 推理间隔可配置（默认 10 秒）
- 去重：连续 3 次检测 + 30 秒冷却
- 新检测 → 保存截图到 `sensor_listener/video/captures/` → 写入共享状态

### YOLO → MQTT Notification

```
检测到新叶/新花 → sensor_state["yolo_event"] = {
    "type": "leaf" | "flower",
    "confidence": 0.92,
    "bbox": [x1,y1,x2,y2],
    "timestamp": "2026-07-08T14:32:05",
    "screenshot": "captures/leaf_20260708_143205.jpg"
}
→ 主循环检测到变化 → MQTT publish("/plant.new_growth", json)
→ 同时终端显示 "🌿 检测到新叶! 置信度 92%"
```

---

## Module: MQTT (`mqtt/`)

移植自 Plant_Project/Connect/，适配 ELF2。

### subscriber.py
- Broker: `p8c59112.ala.cn-hangzhou.emqxsl.cn:8883` (TLS)
- Topic Sub: `rpi5/cloud/command`
- Topic Pub: `rpi5/cloud/data`
- Topic Pub File: `rpi5/cloud/file`
- 非阻塞 `loop_start()`，消息入 `cmd_queue`

### Command Router

```json
{
    "/sensor.state.get":     {"module": "cmd_sensor", "class": "SensorStateGet"},
    "/sensor.temperature.get": {"module": "cmd_sensor", "class": "SensorTemperatureGet"},
    "/sensor.humidity.get":  {"module": "cmd_sensor", "class": "SensorHumidityGet"},
    "/sensor.CO2.get":       {"module": "cmd_sensor", "class": "SensorCO2Get"},
    "/sensor.air_quality.get": {"module": "cmd_sensor", "class": "SensorAir_qualityGet"},
    "/sensor.illumination_intensity.get": {"module": "cmd_sensor", "class": "SensorIllumination_intensityGet"},
    "/sensor.soil_moisture.get": {"module": "cmd_sensor", "class": "SensorSoil_moistureGet"},
    "/sys.cpu.temp":         {"module": "cmd_sys", "class": "SysCpuTemp"},
    "/sys.mem.info":         {"module": "cmd_sys", "class": "SysMemInfo"},
    "/sys.disk.info":        {"module": "cmd_sys", "class": "SysDiskInfo"},
    "/sys.os.uptime":        {"module": "cmd_sys", "class": "SysOsUptime"},
    "/sys.power.reboot":     {"module": "cmd_sys", "class": "SysPowerReboot"},
    "/file.get":             {"module": "cmd_file", "class": "FileSend"},
    "/plant.photo.take":     {"module": "cmd_sensor", "class": "PlantPhotoTake"},
    "/plant.health.get":     {"module": "cmd_sensor", "class": "PlantHealthGet"}
}
```

### sensor_state (共享内存)

cmd_sensor 的查询从原来的 I2C 物理读取改为读取共享 dict：

```python
sensor_state = {
    "t": 26.3, "h": 54.8, "light": 320.5,
    "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200,
    "ts": 1234567,
    "health_score": 87,
    "yolo_event": None,
    "last_update": "2026-07-08T14:32:05",
}
```

---

## Terminal Display

多行 ANSI 区域刷新：

```
┌─────────────────────────────────────────────────────────┐
│ [14:32:05] 温度: 26.3°C  湿度: 54.8%  光照: 320 lx     │
│            eCO2: 450 ppm  TVOC: 12 ppb  气体: 0.85V     │
│            土壤: 2200  健康指数: 87  ████▉  良好        │
│            趋势: 温度 ↗1.2°C  土壤 → 稳定               │
│ ─────────────────────────────────────────────────────  │
│ ⚡ 风扇 80% │ 🌊 水泵 30% │ 💡 白光 150│ 🤖 LLM 待机   │
│ ─────────────────────────────────────────────────────  │
│ 🌿 检测到新叶! 置信度 92% [14:32]                       │
└─────────────────────────────────────────────────────────┘
```

- 传感器行：每次数据到达刷新
- 分析行：每次数据到达刷新
- 控制状态：指令发出时刷新
- 事件行：新事件产生时刷新
- 颜色：null/缺失=灰，警告=黄，危险=红，LLM=青，YOLO=绿

---

## CLI Interface

```bash
python -m sensor_listener [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--port` | `8259` | UDP listen port |
| `--bind` | `0.0.0.0` | Bind address |
| `--log-dir` | `./sensor_logs` | CSV directory |
| `--retention-days` | `60` | CSV retention |
| `--no-color` | off | Disable ANSI color |
| `--verbose` / `-v` | off | Show source IP + byte count |
| `--no-analysis` | off | Disable analysis engine |
| `--no-control` | off | Disable auto control |
| `--no-llm` | off | Disable LLM (local rules only) |
| `--no-video` | off | Disable video + YOLO |
| `--no-mqtt` | off | Disable MQTT |
| `--llm-api-key` | built-in | Override API key |
| `--k230-port` | `8260` | K230 control port |
| `--video-port` | `6001` | TCP video port |
| `--yolo-interval` | `10` | YOLO inference interval (seconds) |
| `--yolo-model` | `./best.pt` | YOLO model path |
| `--yolo-conf` | `0.5` | YOLO confidence threshold |

---

## Dependencies

### Standard Library
asyncio, json, csv, argparse, datetime, pathlib, sys, signal, socket, struct, threading, queue, ssl, subprocess, importlib, os, time

### pip Packages
| Package | Version | Used By |
|---------|---------|---------|
| `av` | latest | h265.py — HEVC 解码 |
| `opencv-python` | latest | 视频显示 + YOLO 预处理 |
| `paho-mqtt` | latest | MQTT 通信 |
| `torch` | latest | YOLOv5 推理 |
| `ultralytics` | latest | YOLOv5 (如用 ultralytics 加载) |
| `numpy` | latest | 数组运算 |
| `openai` | latest | DeepSeek API (兼容 OpenAI SDK) |

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| K230 视频断开 | 重连等待，不影响传感器 + 控制 |
| MQTT 断连 | paho 自动重连，sensor_state 不受影响 |
| YOLO 推理超时 | 跳过本帧，下个周期重试 |
| LLM API 超时/失败 | 降级为本地规则 |
| LLM 连续失败 3 次 | 暂停 5 分钟 |
| K230 UDP 不可达 | 静默丢弃（UDP 无连接），下个周期重发 |
| CSV 写失败 | stderr 警告，继续 |
| MQTT 发布失败 | stderr 警告，继续 |

---

## Testing Strategy

| 模块 | 测试方法 |
|------|---------|
| analysis.py | 单元测试：健康指数公式、趋势计算、基线统计 |
| control.py | 单元测试：本地规则触发、防抖、安全上限 |
| llm_advisor.py | Mock DeepSeek API，测试超时降级、安全过滤 |
| video/yolo_detector.py | 离线图片推理测试、去重逻辑 |
| mqtt/cmd_*.py | Mock MQTT client，测试指令路由 + 返回格式 |
| protocol.py | 集成测试：UDP 收发 + 控制指令构造 |
| main.py | 手动烟雾测试 |
