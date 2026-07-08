import json
import os
import websockets

VTS_WS_URL = os.getenv("VTS_WS_URL", "ws://localhost:8001")
MOUTH_OPEN_PARAM = "MouthOpen"


class VTubeClient:
    def __init__(self):
        self._ws = None
        self._request_id = 0

    async def connect(self):
        try:
            self._ws = await websockets.connect(VTS_WS_URL, open_timeout=1)
            print(f"[VTube] [OK] 已连接 {VTS_WS_URL}")
        except Exception as e:
            print(f"[VTube] [WARN] 连接失败 (VTube Studio 是否已打开?): {e}")
            self._ws = None

    async def _send_request(self, method: str, data: dict) -> dict | None:
        if not self._ws:
            return None
        self._request_id += 1
        req = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"req_{self._request_id}",
            "messageType": method,
            "data": data,
        }
        try:
            await self._ws.send(json.dumps(req))
            resp = await self._ws.recv()
            return json.loads(resp)
        except Exception as e:
            print(f"[VTube] 请求失败: {e}")
            return None

    async def authenticate(self, plugin_name="elf2_avatar", developer="elf2"):
        auth_req = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "auth_1",
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": plugin_name,
                "pluginDeveloper": developer,
            },
        }
        if self._ws:
            await self._ws.send(json.dumps(auth_req))
            resp = await self._ws.recv()
            result = json.loads(resp)
            print(f"[VTube] 认证结果: {result.get('messageType', 'unknown')}")
            return result
        return None

    async def set_mouth_open(self, value: float = 1.0):
        return await self._send_request("ParameterValueRequest", {
            "parameterValues": [
                {"id": MOUTH_OPEN_PARAM, "value": value}
            ]
        })

    async def set_mouth_close(self):
        return await self.set_mouth_open(0.0)

    async def disconnect(self):
        if self._ws:
            await self._ws.close()
            self._ws = None
            print("[VTube] 已断开")
