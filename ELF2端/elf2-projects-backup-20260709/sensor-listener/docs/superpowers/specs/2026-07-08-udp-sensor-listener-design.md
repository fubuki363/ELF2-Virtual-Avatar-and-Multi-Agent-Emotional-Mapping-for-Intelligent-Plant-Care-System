# UDP Sensor Listener — Design Spec

**Date:** 2026-07-08
**Status:** approved

## Overview

监听 UDP 8259 端口，接收 ESP32-C3 每秒发来的 JSON 传感器数据包，解析后在终端实时展示，同时写入 CSV 日志。

- Language: Python 3
- Architecture: asyncio 单文件 (~200 行)
- File: `udp_sensor_listener.py`

## Data Format (ESP32 → Receiver)

正常全部传感器就绪时：
```json
{"t":26.3,"h":54.8,"light":320.5,"eco2":450,"tvoc":12,"gas":0.85,"soil":2200,"ts":1234567}
```

CCS811 预热期间（约前 20 分钟），`eco2` 和 `tvoc` 字段不存在：
```json
{"t":26.3,"h":54.8,"light":320.5,"gas":0.85,"soil":2200,"ts":1234567}
```

I2C 传感器读取失败时对应字段值为 null：
```json
{"t":null,"h":null,"light":320.5,"gas":0.85,"soil":2200,"ts":1234567}
```

### Field Reference

| Key | Description | Type | Notes |
|-----|-------------|------|-------|
| `t` | Temperature | float °C | |
| `h` | Humidity | float %RH | |
| `light` | Ambient light | float lux | |
| `eco2` | Equivalent CO₂ | int ppm | Absent during CCS811 warmup (~20 min) |
| `tvoc` | TVOC | int ppb | Absent during CCS811 warmup (~20 min) |
| `gas` | Gas sensor voltage | float V | |
| `soil` | Soil moisture raw ADC | int 0-4095 | Lower = wetter |
| `ts` | ESP32 millis timestamp | int | For packet loss detection |

## Architecture

Single file, three components sharing one asyncio event loop:

```
                  ┌──────────────────┐
  UDP:8259 ─────► │ SensorProtocol   │  asyncio.DatagramProtocol
                  │ .datagram_received()                │
                  │ parse JSON → dict → display_state   │
                  └───────┬──────────┘
                          │ (shared dict, no lock needed — single thread)
                  ┌───────▼──────────┐
                  │ DisplayManager   │  called by SensorProtocol after update
                  │ .refresh()       │  ANSI in-place refresh, 1 line
                  └───────┬──────────┘
                          │
                  ┌───────▼──────────┐
                  │ CsvWriter        │  always active
                  │ .write_row()     │  append row on each valid packet
                  └──────────────────┘
```

### SensorProtocol

- Extends `asyncio.DatagramProtocol`.
- `datagram_received(data, addr)` called on each UDP packet.
- Parses JSON with `json.loads()`. On parse failure: increments error counter, prints red warning line (one line, does not disrupt refresh display), continues.
- Ignores zero-byte packets and packets > 4 KB.
- Maps fields to `display_state` dict using the field mapping table below.
- After updating state, calls `display_manager.refresh()` and `csv_writer.write_row()`.

### DisplayManager

- Holds reference to shared `display_state` dict.
- `refresh()`: builds a status line string and writes it via `sys.stdout.write()`.
- Uses ANSI escape codes for in-place refresh:
  - `\r` — return to column 0
  - `\033[K` — clear to end of line
  - Cursor control for verbose mode second line
- First line before any data: `监听 0.0.0.0:8259，等待数据...`
- On Ctrl+C: moves cursor down one line, prints exit statistics.

### CsvWriter

- Always active; no `--csv` flag needed.
- Writes to `./sensor_logs/YYYY-MM-DD.csv` (directory created on startup if missing).
- Appends one row per valid packet.
- File is flushed after each write to survive unexpected termination.
- On startup, runs retention cleanup: deletes CSV files older than `--retention-days` (default 60).

### Data Flow

Unidirectional: UDP packet → parse → display_state → terminal refresh + CSV append. No callbacks, no event bus.

## Field Mapping & Display

| Key | Label | Unit | When Missing | When null | Display Format |
|-----|-------|------|-------------|-----------|---------------|
| `t` | 温度 | °C | `--` | `--` | `26.3°C` |
| `h` | 湿度 | % | `--` | `--` | `54.8%` |
| `light` | 光照 | lx | `--` | `--` | `320.5 lx` |
| `eco2` | eCO₂ | ppm | `预热` | `--` | `450 ppm` |
| `tvoc` | TVOC | ppb | `预热` | `--` | `12 ppb` |
| `gas` | 气体 | V | `--` | `--` | `0.85 V` |
| `soil` | 土壤 | — | `--` | `--` | `2200` |
| `ts` | — | — | — | — | Packet loss detection only |

- **CCS811 warmup**: `eco2`/`tvoc` keys absent → display `预热` in dim gray; not treated as error.
- **null values**: I2C read failure → display `--` in dim gray.
- **JSON parse failure**: print red warning with raw byte summary (one line), increment error counter.

## Packet Loss Detection

- Compare consecutive `ts` values.
- Normal interval ≈ 1000 ms.
- Gap > 2000 ms: append `⚠ 丢包 N` (yellow) to status line, increment drop counter.

## Terminal Display

Default mode (single line, ANSI in-place refresh):

```
[14:32:05] 温度: 26.3°C  湿度: 54.8%  光照: 320.5 lx  eCO2: 450 ppm  TVOC: 12 ppb  气体: 0.85 V  土壤: 2200
```

Verbose mode (`--verbose` / `-v`): second line above the sensor line showing source IP and byte count:

```
[14:32:05] 来自 192.168.1.42:12345  102 字节
温度: 26.3°C  湿度: 54.8%  光照: 320.5 lx  eCO2: 450 ppm  TVOC: 12 ppb  气体: 0.85 V  土壤: 2200
```

### Color Scheme

| State | Effect | ANSI |
|-------|--------|------|
| Normal value | Default terminal color | — |
| null / missing | Dim gray | `\033[2m` |
| CCS811 warmup | Dim gray `预热` | `\033[2m` |
| Packet loss warning | Yellow `⚠ 丢包 N` | `\033[33m` |
| JSON parse error | Red line (separate line) | `\033[31m` |

All colors disabled when `--no-color` is set.

### Startup & Shutdown

- **Startup**: prints `监听 0.0.0.0:{port}，等待数据...`, then on first packet begins in-place refresh.
- **Ctrl+C**: cursor down one line, print summary:

```
已退出。
运行时间: 3h 42min  |  总包数: 13320  |  丢包: 5  |  解析错误: 0  |  CSV: 3.1 MB
```

## CSV Storage

- **Directory**: `./sensor_logs/` (created on startup)
- **Filename**: `YYYY-MM-DD.csv` (rolls over at midnight local time)
- **Retention**: 60 days (configurable via `--retention-days`); startup cleanup deletes expired files
- **Encoding**: UTF-8
- **Flush**: after every row

### CSV Schema

```csv
timestamp,t,h,light,eco2,tvoc,gas,soil,esp32_ts,drop_count,error_count
2026-07-08T14:32:05,26.3,54.8,320.5,450,12,0.85,2200,1234567,0,0
2026-07-08T14:32:06,26.4,54.7,318.9,,,0.86,2198,1235567,0,0
```

- `timestamp`: receiver local ISO 8601
- `esp32_ts`: raw ESP32 millis timestamp (for cross-reference)
- `drop_count` / `error_count`: cumulative counters (snapshot at each row)
- Missing/null fields: empty (two consecutive commas)

### Capacity

~70 bytes/row × 86,400 rows/day ≈ 6 MB/day. 60-day retention ≈ 360 MB. On a 32 GB ELF 2 desktop, this is ~1.1% of available space.

## CLI Interface

```
python udp_sensor_listener.py [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--port` | `8259` | UDP listen port |
| `--bind` | `0.0.0.0` | Bind address |
| `--log-dir` | `./sensor_logs` | CSV output directory |
| `--retention-days` | `60` | Days to retain CSV files |
| `--no-color` | off | Disable ANSI color output |
| `--verbose` / `-v` | off | Show extra info line (source IP, byte count) |

## Error Handling Summary

| Condition | Behavior |
|-----------|----------|
| JSON parse error | Red warning line, increment error counter, continue |
| Missing keys (CCS811 warmup) | Display `预热`, normal field in CSV left empty |
| null field values (I2C fail) | Display `--` dim gray, CSV field left empty |
| Zero-byte or >4KB packet | Silently ignored |
| Packet loss (>2s gap) | Yellow `⚠ 丢包 N` on status line |
| CSV write failure | Print error to stderr, continue receiving |
| Retention cleanup failure | Print warning to stderr, do not abort startup |
| Port already in use | Fatal: print error and exit with code 1 |

## Dependencies

Standard library only:
- `asyncio` — event loop + UDP protocol
- `json` — parsing
- `argparse` — CLI
- `csv` — CSV writing
- `datetime` — timestamps, filename rotation, retention
- `os` / `pathlib` — directory creation, file cleanup
- `sys` — stdout control
- `signal` — Ctrl+C handling

No pip packages required.

## Testing Strategy

- Manual: run the script, use `echo '{"t":26.3,...}' | nc -u localhost 8259` to simulate packets
- Test cases to cover:
  1. Full sensor packet (all 8 fields)
  2. CCS811 warmup packet (eco2/tvoc missing)
  3. null field packet (sensor failure)
  4. Malformed JSON
  5. Packet loss scenario (gap > 2s between ts values)
  6. Ctrl+C graceful shutdown
  7. CSV file rotation at midnight boundary
  8. Retention cleanup on startup
