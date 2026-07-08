"""
VTube Studio 连接诊断 v2 — 尝试多种协议格式
"""
import asyncio
import json
import sys
import traceback


async def try_read_first(host="localhost", port=8001):
    """先尝试读取，看 VTS 是否会先发消息"""
    print("\n--- 尝试: 连接后先读取 ---")
    try:
        import websockets
        ws = await asyncio.wait_for(
            websockets.connect(f"ws://{host}:{port}", ping_interval=None),
            timeout=5.0
        )
        print("  已连接，等待 VTS 发消息...")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            print(f"  VTS 先发来: {msg[:200]}")
            return ws, msg
        except asyncio.TimeoutError:
            print("  VTS 没有先发消息（正常）")
            return ws, None
    except Exception as e:
        print(f"  失败: {e}")
        return None, None


async def try_api_v1(ws):
    """尝试标准 VTS API v1.0 格式"""
    print("\n--- 尝试: API v1.0 标准格式 ---")
    payloads = [
        # 格式 1: 标准 AuthenticationTokenRequest
        {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "test_001",
            "messageType": "AuthenticationTokenRequest",
            "data": {"pluginName": "Test", "pluginDeveloper": "Test"},
        },
        # 格式 2: 不带 apiVersion
        {
            "apiName": "VTubeStudioPublicAPI",
            "requestID": "test_002",
            "messageType": "AuthenticationTokenRequest",
            "data": {"pluginName": "Test", "pluginDeveloper": "Test"},
        },
        # 格式 3: 不同的 apiName
        {
            "apiName": "VTubeStudioAPI",
            "apiVersion": "1.0",
            "requestID": "test_003",
            "messageType": "AuthenticationTokenRequest",
            "data": {"pluginName": "Test", "pluginDeveloper": "Test"},
        },
        # 格式 4: 不同的 messageType (TokenRequest)
        {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "test_004",
            "messageType": "TokenRequest",
            "data": {"pluginName": "Test", "pluginDeveloper": "Test"},
        },
        # 格式 5: 旧版 API 格式
        {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "test_005",
            "messageType": "AuthTokenRequest",
            "data": {"pluginName": "Test", "pluginDeveloper": "Test"},
        },
    ]

    for i, payload in enumerate(payloads):
        try:
            raw = json.dumps(payload, ensure_ascii=False)
            await ws.send(raw)
            print(f"  发送 [{i+1}]: {payload['messageType']} (apiName={payload.get('apiName', 'N/A')})")

            resp = await asyncio.wait_for(ws.recv(), timeout=3.0)
            data = json.loads(resp)
            msg_type = data.get("messageType", "?")
            print(f"  ← 收到: {msg_type}")
            if msg_type != "APIError":
                print(f"  ✓ 成功! 响应: {json.dumps(data, ensure_ascii=False)[:300]}")
                return data
            else:
                err = data.get("data", {}).get("message", str(data))
                print(f"  ✗ API错误: {err}")

        except asyncio.TimeoutError:
            print(f"  [{i+1}] 超时，无响应")
        except Exception as e:
            print(f"  [{i+1}] 异常: {type(e).__name__}: {e}")

    return None


async def try_raw_protocol(host="localhost", port=8001):
    """用最原始的方式测试"""
    print("\n--- 尝试: 原始 TCP + HTTP Upgrade ---")
    try:
        import websockets
        from websockets.asyncio.client import ClientConnection

        # 使用新版 API
        async with websockets.connect(
            f"ws://{host}:{port}",
            ping_interval=None,
            ping_timeout=None,
            close_timeout=2,
        ) as ws:
            print(f"  连接成功, type={type(ws).__name__}")

            # 尝试直接发 JSON 看看
            test_msg = json.dumps({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "raw_test",
                "messageType": "AuthenticationTokenRequest",
                "data": {"pluginName": "RawTest", "pluginDeveloper": "Test"},
            })
            await ws.send(test_msg)
            print("  → 已发送")

            # 等待更长时间
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"  ← {resp[:300]}")
                return json.loads(resp)
            except asyncio.TimeoutError:
                print("  5秒超时，无响应")
                return None

    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None


async def try_with_context_manager():
    """用 async with 测试"""
    print("\n--- 尝试: async with 方式 ---")
    try:
        import websockets

        async with websockets.connect("ws://localhost:8001") as ws:
            print(f"  已连接")
            await ws.send(json.dumps({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "ctx_001",
                "messageType": "AuthenticationTokenRequest",
                "data": {"pluginName": "CTX", "pluginDeveloper": "Test"},
            }))
            print("  → 已发送")

            resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"  ← {resp[:300]}")
            return json.loads(resp)

    except asyncio.TimeoutError:
        print("  超时")
        return None
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
        return None


async def main():
    print("VTS API 协议探测")
    print("=" * 60)

    # 方法 A: 先读后写
    ws, first_msg = await try_read_first()
    if ws and first_msg:
        print("\n  ✓ VTS 会主动发消息，可能是新版协议")
        await ws.close()
        return

    if ws:
        # 方法 B: 尝试多种 API 格式
        result = await try_api_v1(ws)
        await ws.close()
        if result:
            print(f"\n  ✓✓ 找到有效格式!")
            return

    # 方法 C: 用 context manager 方式重试
    result = await try_with_context_manager()
    if result:
        print(f"\n  ✓✓ context manager 方式有效!")
        return

    # 方法 D: 原始协议
    result = await try_raw_protocol()
    if result:
        print(f"\n  ✓✓ 原始方式有效!")
        return

    # 总结
    print("\n" + "!" * 60)
    print("  所有尝试均失败 — VTS WebSocket 端口响应握手")
    print("  但不响应任何 API 消息。")
    print()
    print("  请检查:")
    print("  1. VTube Studio 版本号? (帮助 → 关于)")
    print("  2. 设置 → API 中是否有其他选项需要勾选?")
    print("     (如 'Plugin API' / 'Allow External Control' 等)")
    print("  3. VTS 控制台有无报错日志?")
    print("!" * 60)


if __name__ == "__main__":
    asyncio.run(main())
