"""
VTube Studio 连接诊断工具
运行: python diagnose.py
"""

import asyncio
import json
import sys
import traceback

DIAG_RESULTS = {}


async def test_basic_socket(host: str, port: int):
    """测试 1: TCP 能否连通端口"""
    print("\n" + "=" * 60)
    print("  测试 1: TCP 端口连通性")
    print("=" * 60)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0,
        )
        writer.close()
        await writer.wait_closed()
        print(f"  ✓ TCP 连接成功 → {host}:{port} 可达")
        DIAG_RESULTS["tcp"] = True
    except asyncio.TimeoutError:
        print(f"  ✗ 连接超时 → {host}:{port} 不可达")
        print(f"    请确认: VTube Studio 正在运行，且 API 已开启")
        DIAG_RESULTS["tcp"] = False
    except ConnectionRefusedError:
        print(f"  ✗ 连接被拒绝 → {host}:{port}")
        print(f"    端口 {port} 没有服务在监听")
        print(f"    VTube Studio → 设置 → API → 勾选 Start API")
        DIAG_RESULTS["tcp"] = False
    except Exception as e:
        print(f"  ✗ 异常: {type(e).__name__}: {e}")
        DIAG_RESULTS["tcp"] = False


async def test_websocket_handshake(host: str, port: int):
    """测试 2: WebSocket 握手"""
    print("\n" + "=" * 60)
    print("  测试 2: WebSocket 握手")
    print("=" * 60)
    try:
        import websockets
        print(f"  websockets 版本: {websockets.__version__}")

        ws = await asyncio.wait_for(
            websockets.connect(
                f"ws://{host}:{port}",
                ping_interval=None,   # 关闭自动 ping
                ping_timeout=None,
                close_timeout=3,
                max_queue=16,
            ),
            timeout=5.0,
        )
        print(f"  ✓ WebSocket 握手成功")
        DIAG_RESULTS["ws_handshake"] = True
        return ws
    except asyncio.TimeoutError:
        print(f"  ✗ WebSocket 握手超时")
        print(f"    VTS 可能版本较旧，不支持 WebSocket API")
        DIAG_RESULTS["ws_handshake"] = False
        return None
    except Exception as e:
        print(f"  ✗ 握手失败: {type(e).__name__}: {e}")
        traceback.print_exc()
        DIAG_RESULTS["ws_handshake"] = False
        return None


async def test_authentication(ws):
    """测试 3: 认证"""
    print("\n" + "=" * 60)
    print("  测试 3: API 认证")
    print("=" * 60)

    if ws is None:
        print("  跳过 (WebSocket 未连接)")
        DIAG_RESULTS["auth"] = False
        return

    try:
        # Step 1: 获取 token
        req_id = "diag_auth_1"
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": req_id,
            "messageType": "AuthenticationTokenRequest",
            "data": {
                "pluginName": "VTS Diag Tool",
                "pluginDeveloper": "User",
            },
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))
        print(f"  → 已发送 AuthenticationTokenRequest")

        # 等响应
        resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(resp)
        print(f"  ← 收到: {data.get('messageType')}")

        if data.get("messageType") == "APIError":
            err = data.get("data", {})
            print(f"  ✗ API 错误: {err.get('message', str(err))}")
            DIAG_RESULTS["auth"] = False
            return

        token = data.get("data", {}).get("authenticationToken", "")
        print(f"  Token: {token[:20]}..." if token else "  ✗ 未收到 token")

        # Step 2: 用 token 认证
        req_id2 = "diag_auth_2"
        payload2 = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": req_id2,
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": "VTS Diag Tool",
                "pluginDeveloper": "User",
                "authenticationToken": token,
            },
        }
        await ws.send(json.dumps(payload2, ensure_ascii=False))
        print(f"  → 已发送 AuthenticationRequest")

        resp2 = await asyncio.wait_for(ws.recv(), timeout=10.0)
        data2 = json.loads(resp2)
        print(f"  ← 收到: {data2.get('messageType')}")

        if data2.get("messageType") == "APIError":
            err = data2.get("data", {})
            print(f"  ✗ API 错误: {err.get('message', str(err))}")
            DIAG_RESULTS["auth"] = False
            return

        authed = data2.get("data", {}).get("authenticated", False)
        if authed:
            print(f"  ✓ 认证成功！")
            DIAG_RESULTS["auth"] = True
        else:
            print(f"  ⚠ 认证未通过 — 请在 VTube Studio 弹窗中点击「允许」")
            DIAG_RESULTS["auth"] = False

    except asyncio.TimeoutError:
        print(f"  ✗ 等待响应超时")
        DIAG_RESULTS["auth"] = False
    except Exception as e:
        print(f"  ✗ 异常: {type(e).__name__}: {e}")
        traceback.print_exc()
        DIAG_RESULTS["auth"] = False


async def test_expressions(ws):
    """测试 4: 获取表情"""
    print("\n" + "=" * 60)
    print("  测试 4: 获取表情列表")
    print("=" * 60)

    if ws is None:
        print("  跳过")
        DIAG_RESULTS["expr"] = False
        return

    try:
        req_id = "diag_expr"
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": req_id,
            "messageType": "ExpressionStateRequest",
            "data": {"details": True},
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))
        print(f"  → 已发送 ExpressionStateRequest")

        resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(resp)
        print(f"  ← 收到: {data.get('messageType')}")

        if data.get("messageType") == "APIError":
            err = data.get("data", {})
            print(f"  ✗ API 错误: {err.get('message', str(err))}")
            DIAG_RESULTS["expr"] = False
            return

        expressions = data.get("data", {}).get("expressions", [])
        print(f"  ✓ 获取到 {len(expressions)} 个表情:")
        for e in expressions:
            active = "🟢" if e.get("active") else "⚪"
            print(f"     {active} {e.get('name', '?')}  ({e.get('file', '?')})")
        DIAG_RESULTS["expr"] = True

    except Exception as e:
        print(f"  ✗ 异常: {type(e).__name__}: {e}")
        traceback.print_exc()
        DIAG_RESULTS["expr"] = False


async def main():
    host = "localhost"
    port = 8001

    print("╔══════════════════════════════════════════════════════╗")
    print("║     VTube Studio API 连接诊断工具                    ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  Python:  " + f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}".ljust(42) + "║")
    print(f"║  目标:     ws://{host}:{port}".ljust(55) + "║")
    print("╚══════════════════════════════════════════════════════╝")

    # 测试 1: TCP
    await test_basic_socket(host, port)
    if not DIAG_RESULTS.get("tcp"):
        print("\n" + "!" * 60)
        print("  TCP 连接失败 — 请检查:")
        print("  1. VTube Studio 是否正在运行?")
        print("  2. 设置 → API → Start API 是否勾选?")
        print("  3. 端口号是否为 8001?")
        print("  4. 防火墙是否阻止了本地连接?")
        print("!" * 60)
        return

    # 测试 2-4
    ws = await test_websocket_handshake(host, port)
    if ws:
        try:
            await test_authentication(ws)
            if DIAG_RESULTS.get("auth"):
                await test_expressions(ws)
        finally:
            await ws.close()
            print("\n  连接已关闭")

    # 总结
    print("\n" + "=" * 60)
    print("  诊断总结")
    print("=" * 60)
    all_pass = True
    for test_name, passed in DIAG_RESULTS.items():
        status = "✓ 通过" if passed else "✗ 失败"
        labels = {
            "tcp": "TCP 端口连通",
            "ws_handshake": "WebSocket 握手",
            "auth": "API 认证",
            "expr": "表情获取",
        }
        print(f"  {status}  {labels.get(test_name, test_name)}")
        if not passed:
            all_pass = False

    if all_pass:
        print(f"\n  ✓ 全部通过！可以使用 python vts_cli.py 控制表情了。")
    else:
        print(f"\n  ! 存在失败项，请根据上面的提示排查。")


if __name__ == "__main__":
    asyncio.run(main())
