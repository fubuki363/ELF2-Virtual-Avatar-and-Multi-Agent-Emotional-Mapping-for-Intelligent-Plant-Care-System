"""
VTube Studio 角色预设表情 & 动作控制器
=============================================
通过 VTube Studio Public API (WebSocket) 独立控制
古钟角色模型的每一个预设表情和动作。

前置条件: VTube Studio → 设置 → API → 勾选 "Start API" (端口 8001)

核心机制:
  - 表情 → 通过 ExpressionActivationRequest 直接激活，无需热键
  - 动作 → 需要先在 VTS 中配置热键，然后触发
  - 参数 → 通过 InjectParameterDataRequest 直接操控 Live2D 参数

使用方式:
  - 作为库导入: from vts_controller import VTSController
  - 命令行交互: python vts_cli.py
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Optional, Callable, Any, Union

import websockets
from websockets import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

logger = logging.getLogger("vts_controller")

# Token 持久化文件路径
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vts_token")
# 向后兼容：也检查 vts_code/ 目录下的旧 token
_LEGACY_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vts_code", ".vts_token")


def _load_saved_token() -> Optional[str]:
    """读取已保存的认证 token"""
    for path in (TOKEN_FILE, _LEGACY_TOKEN_FILE):
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return f.read().strip()
        except Exception:
            pass
    return None


def _save_token(token: str):
    """保存认证 token"""
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
    except Exception as e:
        logger.warning(f"无法保存 token: {e}")


# ─── 数据模型 ───────────────────────────────────────────────

@dataclass
class ExpressionInfo:
    """模型的表情（直接从模型文件读取，不依赖热键）"""
    name: str           # 表情名称
    file: str           # 文件名，如 "Smile.exp3.json"
    active: bool = False
    deactivate_when_key_is_let_go: bool = False

    def __str__(self):
        status = "🟢" if self.active else "⚪"
        return f"  {status} {self.name}  ({self.file})"


@dataclass
class HotkeyInfo:
    """VTS 中配置的热键（用于触发动作等）"""
    hotkey_id: str
    name: str
    kind: str       # "expression" / "motion" / "unknown"
    file: str = ""

    def __str__(self):
        icon = "🎭" if self.kind == "expression" else "🏃"
        return f"  {icon} [{self.kind}] {self.name}  (id={self.hotkey_id})"


@dataclass
class Live2DParameter:
    """Live2D 参数"""
    name: str
    default_value: float = 0.0
    min_value: float = 0.0
    max_value: float = 1.0

    def __str__(self):
        return f"  📐 {self.name}  [{self.min_value}~{self.max_value}]  默认={self.default_value:.2f}"


@dataclass
class ArtMesh:
    """模型部件（可单独显示/隐藏）"""
    name: str
    enabled: bool = True
    group: str = ""

    def __str__(self):
        icon = "👁" if self.enabled else "🚫"
        return f"  {icon} {self.name}  (group={self.group})"


# ─── 异常 ────────────────────────────────────────────────────

class VTSAPIError(Exception):
    """VTS API 返回的错误"""
    def __init__(self, message: str, error_id: int = 0):
        super().__init__(message)
        self.error_id = error_id


class VTSAuthError(VTSAPIError):
    """认证相关错误"""
    pass


# ═══════════════════════════════════════════════════════════════
#  主控制器
# ═══════════════════════════════════════════════════════════════

class VTSController:
    """
    VTube Studio 控制器

    两种控制方式:

    【方式一】直接表情控制（推荐，无需在 VTS 中配置热键）
        expressions = await vts.list_expressions()        # 获取模型自带表情
        await vts.activate_expression_by_name("Smile")    # 按名称激活

    【方式二】热键控制（需要先在 VTS 中配置热键）
        await vts.trigger_hotkey_by_name("挥手键")         # 触发动作热键
    """

    def __init__(self, host: str = "localhost", port: int = 8001,
                 plugin_name: str = "VTS Python Controller",
                 plugin_developer: str = "User"):
        self.host = host
        self.port = port
        self.plugin_name = plugin_name
        self.plugin_developer = plugin_developer
        self._ws: Optional[WebSocketClientProtocol] = None
        self._session_token: Optional[str] = None
        # 缓存
        self._expressions: list[ExpressionInfo] = []
        self._hotkeys: list[HotkeyInfo] = []
        self._parameters: list[Live2DParameter] = []
        self._art_meshes: list[ArtMesh] = []
        self._model_name: str = ""

    # ── 连接管理 ──────────────────────────────────────────

    async def connect(self):
        """建立 WebSocket 连接并认证"""
        await self._ws_connect()
        await self._authenticate()
        logger.info("VTube Studio 连接 & 认证成功 ✓")

    async def _ws_connect(self):
        """仅建立 WebSocket 连接（不认证）"""
        uri = f"ws://{self.host}:{self.port}"
        try:
            self._ws = await websockets.connect(
                uri,
                ping_interval=20,       # 20秒发一次 ping 保持连接
                ping_timeout=10,        # ping 10秒无响应则断连
                close_timeout=3,
            )
            logger.info(f"WebSocket 已连接: {uri}")
        except (ConnectionRefusedError, OSError) as e:
            raise VTSAPIError(
                f"无法连接到 VTube Studio ({uri})。\n"
                f"请确认:\n"
                f"  1. VTube Studio 正在运行\n"
                f"  2. 设置 → API → 已勾选 'Start API' (端口 {self.port})\n"
                f"  3. 防火墙未阻止连接\n"
                f"原始错误: {e}"
            )

    async def reconnect(self):
        """断开后重新连接并认证（保留 token，无需重新授权）"""
        logger.info("正在重连 VTube Studio...")
        # 关闭旧连接
        try:
            if self._ws:
                await self._ws.close()
        except Exception:
            pass
        self._ws = None
        # 清除可能需要刷新的缓存
        self._expressions = []
        self._hotkeys = []
        # 重新连接和认证
        await self._ws_connect()
        await self._authenticate()
        logger.info("重连成功 ✓")

    def _is_ws_closed(self) -> bool:
        """检查 WebSocket 是否已关闭 (兼容 websockets 12.x+)"""
        if self._ws is None:
            return True
        # websockets 12.x: ClientConnection 没有 .closed 属性
        if hasattr(self._ws, 'protocol'):
            return self._ws.protocol.close_code is not None
        # websockets < 12.0: 使用 .closed
        return self._ws.closed if hasattr(self._ws, 'closed') else False

    async def _ensure_connected(self):
        """确保连接可用，如果断开则自动重连"""
        if self._is_ws_closed():
            await self.reconnect()

    async def _authenticate(self):
        """
        认证流程（处理授权窗口弹窗）

        流程:
        1. 先查本地有没有保存的 token → 直接尝试认证
        2. 如果没有或 token 失效 → 请求新 token
        3. 此时 VTS 会弹授权窗口 → 等待用户点击"允许"
        4. 拿到 token 后保存到本地
        """
        saved_token = _load_saved_token()

        # Step 1: 如果有已保存的 token，直接认证
        if saved_token:
            try:
                data = await self._send("AuthenticationRequest", {
                    "pluginName": self.plugin_name,
                    "pluginDeveloper": self.plugin_developer,
                    "authenticationToken": saved_token,
                })
                if data.get("authenticated", False):
                    self._session_token = saved_token
                    logger.info("使用已保存的 token 认证成功 ✓")
                    return
                else:
                    logger.info("已保存的 token 已失效，重新获取...")
            except VTSAPIError as e:
                logger.info(f"用已保存 token 认证失败 ({e})，重新获取...")

        # Step 2: 请求新 token
        await self._request_new_token()

    async def _request_new_token(self):
        """请求新的认证 token（会弹出 VTS 授权窗口）"""
        print(f"\n  ╔══════════════════════════════════════════╗")
        print(f"  ║  请在 VTube Studio 中点击「允许」     ║")
        print(f"  ╚══════════════════════════════════════════╝\n")

        # Step 1: 请求 token（如果已有授权窗口开着，会收到 error 51）
        retry_count = 0
        while True:
            try:
                data = await self._send("AuthenticationTokenRequest", {
                    "pluginName": self.plugin_name,
                    "pluginDeveloper": self.plugin_developer,
                })
                token = data.get("authenticationToken", "")
                if token:
                    logger.info("已获取 token")
                    break
                # token 为空但没报错，重试
                retry_count += 1
                if retry_count > 5:
                    raise VTSAuthError("多次请求均未收到认证 token")
                await asyncio.sleep(1.0)

            except VTSAPIError as e:
                if e.error_id == 51:
                    # 认证窗口已经开着（上次连接遗留），等待用户点击
                    print(f"  检测到授权窗口已打开，请点击「允许」...")
                    await asyncio.sleep(2.0)
                    retry_count += 1
                    if retry_count > 15:
                        raise VTSAuthError(
                            "等待授权超时。请切换到 VTube Studio 窗口，"
                            "点击「允许」后重试。"
                        )
                    continue
                raise

        # Step 2: 用 token 完成认证
        for attempt in range(30):  # 最多等 30 秒
            await asyncio.sleep(1.0)
            try:
                data = await self._send("AuthenticationRequest", {
                    "pluginName": self.plugin_name,
                    "pluginDeveloper": self.plugin_developer,
                    "authenticationToken": token,
                })
                if data.get("authenticated", False):
                    self._session_token = token
                    _save_token(token)
                    print("  认证成功 ✓\n")
                    logger.info("认证成功 ✓")
                    return
                else:
                    logger.debug(f"等待授权... ({attempt + 1}/30)")
            except VTSAPIError as e:
                if e.error_id == 51:
                    logger.debug(f"等待用户授权... ({attempt + 1}/30)")
                    continue
                raise

        raise VTSAuthError(
            "认证超时 — 请在 VTube Studio 中点击「允许」后重试"
        )

    async def disconnect(self):
        """断开连接"""
        if self._ws:
            await self._ws.close()
            self._ws = None
            logger.info("已断开 VTube Studio 连接")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    # ── 底层通信 ──────────────────────────────────────────

    async def _send(self, message_type: str, data: dict, _retry: bool = True) -> dict:
        """
        发送请求，返回响应的 data 字段。
        连接断开时自动重连并重试一次。
        """

        req_id = str(uuid.uuid4())[:8]
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": req_id,
            "messageType": message_type,
            "data": data,
        }

        try:
            await self._ensure_connected()
        except VTSAPIError:
            pass  # 如果重连失败，让下面的 send 报具体错误

        try:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed as e:
            if _retry:
                logger.warning(f"发送失败 (连接断开)，尝试重连...")
                await self.reconnect()
                return await self._send(message_type, data, _retry=False)
            raise VTSAPIError(f"连接已断开，重连后仍无法发送: {e}")

        logger.debug(f"→ {message_type} (id={req_id})")

        # 等待匹配的响应
        while True:
            try:
                resp_raw = await asyncio.wait_for(self._ws.recv(), timeout=15.0)
            except asyncio.TimeoutError:
                raise VTSAPIError(f"等待 {message_type} 响应超时 (15秒)")
            except ConnectionClosedError as e:
                if _retry:
                    logger.warning(f"接收时连接断开 ({e.code})，尝试重连重试...")
                    await self.reconnect()
                    return await self._send(message_type, data, _retry=False)
                raise VTSAPIError(
                    f"VTube Studio 断开了连接 ({e.code})。\n"
                    f"可能原因: VTS 崩溃、模型切换、或 API 被关闭。\n"
                    f"请确认 VTS 仍在运行后重新操作。"
                )
            except ConnectionClosed as e:
                raise VTSAPIError(f"连接关闭: {e}")

            try:
                resp = json.loads(resp_raw)
            except json.JSONDecodeError as e:
                logger.warning(f"收到非 JSON 响应: {resp_raw[:100]}")
                continue

            if resp.get("requestID") != req_id:
                logger.debug(f"跳过非匹配响应: {resp.get('messageType')} (id={resp.get('requestID')})")
                continue

            logger.debug(f"← {resp.get('messageType')}")

            if resp.get("messageType") == "APIError":
                err_data = resp.get("data", {})
                msg = err_data.get("message", str(err_data))
                err_id = err_data.get("errorID", 0)
                raise VTSAPIError(msg, error_id=err_id)

            return resp.get("data", {})

    # ══════════════════════════════════════════════════════════
    #  一、表情控制（直接方式 — 不需要热键）
    # ══════════════════════════════════════════════════════════

    async def fetch_expressions(self) -> list[ExpressionInfo]:
        """从模型获取所有表情（不依赖热键）"""
        data = await self._send("ExpressionStateRequest", {"details": True})
        expressions = []
        for item in data.get("expressions", []):
            expressions.append(ExpressionInfo(
                name=item.get("name", ""),
                file=item.get("file", ""),
                active=item.get("active", False),
                deactivate_when_key_is_let_go=item.get("deactivateWhenKeyIsLetGo", False),
            ))
        self._expressions = expressions
        return expressions

    async def list_expressions(self, refresh: bool = False) -> list[ExpressionInfo]:
        """获取表情列表（优先使用缓存）"""
        if refresh or not self._expressions:
            await self.fetch_expressions()
        return self._expressions

    @property
    def expressions(self) -> list[ExpressionInfo]:
        """同步获取已缓存的表情列表（需先 await list_expressions()）"""
        return self._expressions

    # ══════════════════════════════════════════════════════════
    #  一、表情控制
    #     优先级: 热键触发 → ExpressionActivation API
    #     因为部分 VTS 版本 ExpressionActivationRequest 不稳定,
    #     优先使用模型自带的热键来切换表情。
    # ══════════════════════════════════════════════════════════

    async def _find_expression_hotkey(self, expr: ExpressionInfo) -> Optional[HotkeyInfo]:
        """查找表情对应的热键（通过文件名匹配）"""
        hotkeys = await self.list_hotkeys()
        for hk in hotkeys:
            if hk.file == expr.file:
                return hk
        # 也试试名字匹配
        for hk in hotkeys:
            if hk.name == expr.name:
                return hk
        return None

    async def activate_expression(self, file_name: str, active: bool = True):
        """
        按文件名激活/停用表情

        优先使用热键切换（更可靠），否则用 ExpressionActivation API
        """
        label = "激活" if active else "停用"
        logger.info(f"{label}表情: {file_name}")

        # 找到对应的表情和热键
        expr = None
        for e in self._expressions:
            if e.file == file_name:
                expr = e
                break

        if expr is None:
            # 缓存中没有，先刷新
            await self.fetch_expressions()
            for e in self._expressions:
                if e.file == file_name:
                    expr = e
                    break

        if expr is None:
            raise ValueError(f"未找到表情: {file_name}")

        # 检查是否已经是目标状态
        if expr.active == active:
            logger.info(f"表情已在目标状态，跳过")
            return

        # 查找关联热键
        hotkey = await self._find_expression_hotkey(expr)

        if hotkey and hotkey.kind in ("toggleexpression", "expression"):
            # 通过热键切换（最可靠的方式）
            logger.info(f"通过热键 [{hotkey.name}] 切换表情")
            await self._send("HotkeyTriggerRequest", {
                "hotkeyID": hotkey.hotkey_id,
            })
            expr.active = active
        else:
            # 回退到 ExpressionActivation API
            try:
                await self._send("ExpressionActivationRequest", {
                    "expressionFileName": file_name,
                    "active": active,
                })
                expr.active = active
            except VTSAPIError as e:
                raise VTSAPIError(
                    f"无法切换表情 '{file_name}': {e}\n"
                    f"提示: 请在 VTube Studio 中为该表情配置一个热键"
                ) from e

    async def deactivate_expression(self, file_name: str):
        """按文件名停用表情"""
        await self.activate_expression(file_name, active=False)

    async def activate_expression_by_name(self, name: str, active: bool = True, refresh: bool = False):
        """按表情名称激活/停用（模糊匹配）"""
        expressions = await self.list_expressions(refresh)
        match = self._find_expression(name, expressions)
        if match:
            return await self.activate_expression(match.file, active)

        available = "\n".join(f"  - {e.name}" for e in expressions)
        raise ValueError(
            f"未找到名为 '{name}' 的表情。\n当前可用表情:\n{available}"
        )

    async def deactivate_expression_by_name(self, name: str, refresh: bool = False):
        """按名称停用表情"""
        await self.activate_expression_by_name(name, active=False, refresh=refresh)

    async def activate_expression_by_index(self, index: int, active: bool = True, refresh: bool = False):
        """按索引激活/停用表情"""
        expressions = await self.list_expressions(refresh)
        if not expressions:
            raise ValueError("当前模型没有表情")
        if index < 0 or index >= len(expressions):
            raise ValueError(f"表情索引超出范围 (0~{len(expressions) - 1})")
        return await self.activate_expression(expressions[index].file, active)

    async def deactivate_expression_by_index(self, index: int, refresh: bool = False):
        """按索引停用表情"""
        await self.activate_expression_by_index(index, active=False, refresh=refresh)

    async def deactivate_all_expressions(self):
        """停用所有当前激活的表情（回到默认表情）"""
        expressions = await self.list_expressions(refresh=True)
        for expr in expressions:
            if expr.active:
                hotkey = await self._find_expression_hotkey(expr)
                if hotkey:
                    await self._send("HotkeyTriggerRequest", {
                        "hotkeyID": hotkey.hotkey_id,
                    })
                    expr.active = False
                    await asyncio.sleep(0.05)  # 避免请求太快
        logger.info("已停用所有表情 ✓")

    async def play_all_expressions(self, delay: float = 0.5):
        """依次激活所有表情（预览用，使用热键切换）"""
        expressions = await self.list_expressions(refresh=True)
        for i, expr in enumerate(expressions):
            print(f"  [{i}] {expr.name}")
            hotkey = await self._find_expression_hotkey(expr)
            if hotkey:
                # 激活
                if not expr.active:
                    await self._send("HotkeyTriggerRequest", {"hotkeyID": hotkey.hotkey_id})
                await asyncio.sleep(delay)
                # 停用
                await self._send("HotkeyTriggerRequest", {"hotkeyID": hotkey.hotkey_id})
            await asyncio.sleep(0.1)

    def _find_expression(self, name: str, expressions: list[ExpressionInfo]) -> Optional[ExpressionInfo]:
        """查找表情：先精确匹配，再模糊匹配"""
        # 精确匹配
        for e in expressions:
            if e.name == name:
                return e
        # 模糊匹配
        name_lower = name.lower()
        matches = [e for e in expressions if name_lower in e.name.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(e.name for e in matches)
            logger.warning(f"匹配到多个: {names}，使用第一个: {matches[0].name}")
            return matches[0]
        return None

    # ══════════════════════════════════════════════════════════
    #  二、热键控制（需要先在 VTS 中配置热键）
    # ══════════════════════════════════════════════════════════

    async def fetch_hotkeys(self) -> list[HotkeyInfo]:
        """获取 VTS 中已配置的热键"""
        data = await self._send("HotkeysInCurrentModelRequest", {})
        hotkeys = []
        for item in data.get("availableHotkeys", []):
            hotkeys.append(HotkeyInfo(
                hotkey_id=item["hotkeyID"],
                name=item.get("name", ""),
                kind=item.get("type", "unknown").lower(),
                file=item.get("file", ""),
            ))
        self._hotkeys = hotkeys
        return hotkeys

    async def list_hotkeys(self, refresh: bool = False) -> list[HotkeyInfo]:
        """获取热键列表"""
        if refresh or not self._hotkeys:
            await self.fetch_hotkeys()
        return self._hotkeys

    async def trigger_hotkey_by_id(self, hotkey_id: str):
        """按 ID 触发热键"""
        logger.info(f"触发热键: id={hotkey_id}")
        await self._send("HotkeyTriggerRequest", {"hotkeyID": hotkey_id})

    async def trigger_hotkey_by_name(self, name: str, refresh: bool = False):
        """按名称触发热键"""
        hotkeys = await self.list_hotkeys(refresh)
        for hk in hotkeys:
            if hk.name == name:
                return await self.trigger_hotkey_by_id(hk.hotkey_id)
        name_lower = name.lower()
        matches = [hk for hk in hotkeys if name_lower in hk.name.lower()]
        if not matches:
            available = "\n".join(f"  - {hk.name}" for hk in hotkeys) if hotkeys else "  (无)"
            raise ValueError(
                f"未找到名为 '{name}' 的热键。\n已配置的热键:\n{available}\n\n"
                f"提示: 表情可直接用 activate_expression_by_name() 控制，不需要热键。"
            )
        return await self.trigger_hotkey_by_id(matches[0].hotkey_id)

    async def trigger_hotkey_by_index(self, index: int, refresh: bool = False):
        """按索引触发热键"""
        hotkeys = await self.list_hotkeys(refresh)
        if not hotkeys:
            raise ValueError("当前没有配置任何热键")
        if index < 0 or index >= len(hotkeys):
            raise ValueError(f"热键索引超出范围 (0~{len(hotkeys) - 1})")
        return await self.trigger_hotkey_by_id(hotkeys[index].hotkey_id)

    # ══════════════════════════════════════════════════════════
    #  三、Live2D 参数控制
    # ══════════════════════════════════════════════════════════

    async def fetch_parameters(self) -> list[Live2DParameter]:
        """获取所有 Live2D 参数"""
        data = await self._send("Live2DParameterListRequest", {})
        params = []
        for item in data.get("parameters", []):
            params.append(Live2DParameter(
                name=item.get("name", ""),
                default_value=item.get("defaultValue", 0.0),
                min_value=item.get("minValue", 0.0),
                max_value=item.get("maxValue", 1.0),
            ))
        self._parameters = params
        return params

    async def list_parameters(self, refresh: bool = False) -> list[Live2DParameter]:
        """获取 Live2D 参数列表"""
        if refresh or not self._parameters:
            await self.fetch_parameters()
        return self._parameters

    async def create_parameter(
        self, name: str, min_val: float = -1.0, max_val: float = 1.0,
        default_val: float = 0.0, explanation: str = ""
    ) -> dict:
        """
        创建自定义追踪参数（可注入数据）

        VTS 中需要将此参数手动映射到 Live2D 参数才能影响模型。
        只需设置一次，之后自动生效。
        """
        logger.info(f"创建参数: {name}")
        data = await self._send("ParameterCreationRequest", {
            "parameterName": name,
            "explanation": explanation or f"Custom control for {name}",
            "min": min_val,
            "max": max_val,
            "defaultValue": default_val,
        })
        return data

    async def inject_parameters(self, params: dict[str, float], auto_create: bool = True):
        """
        注入参数值。如果参数不存在则自动创建（仅限自定义参数）。

        注意: 首次使用需要在 VTS 中将自定义参数映射到 Live2D 参数。
              参见 print_mapping_guide()
        """
        param_list = [{"id": name, "value": value} for name, value in params.items()]
        try:
            await self._send("InjectParameterDataRequest", {"parameterValues": param_list})
        except VTSAPIError as e:
            if auto_create and "not found" in str(e):
                for name, value in params.items():
                    await self.create_parameter(
                        name,
                        min_val=-1.0, max_val=1.0,
                        default_val=0.0,
                        explanation=f"Controls {name}"
                    )
                # 重试注入
                await self._send("InjectParameterDataRequest", {"parameterValues": param_list})
            else:
                raise
        logger.debug(f"参数: {params}")

    async def reset_parameters(self):
        """重置所有参数到默认值"""
        await self._send("ParameterDeletionRequest", {"parameterNames": []})
        logger.info("已重置所有参数 ✓")

    # ── 参数搜索 ─────────────────────────────────────────

    async def search_parameters(self, keyword: str) -> list[Live2DParameter]:
        """按关键字搜索参数"""
        params = await self.list_parameters()
        kw = keyword.lower()
        return [p for p in params if kw in p.name.lower()]

    async def print_parameters(self, keyword: str = ""):
        """打印参数列表（可按关键字过滤）"""
        if keyword:
            params = await self.search_parameters(keyword)
        else:
            params = await self.list_parameters()
        print(f"\n参数 ({len(params)} 个):")
        for i, p in enumerate(params):
            print(f"  [{i}] {p}")

    # ── 自定义参数名 ─────────────────────────────────────
    # 这些参数通过 InjectParameterData 控制，需在 VTS 中映射到 Live2D 参数

    PARAM_MOUTH_OPEN = "ctrl_mouth_open"      # → 映射到 ParamMouthOpenY
    PARAM_MOUTH_FORM = "ctrl_mouth_form"      # → 映射到 ParamMouthForm
    PARAM_EYE_OPEN_L = "ctrl_eye_open_left"   # → 映射到 ParamEyeLOpen
    PARAM_EYE_OPEN_R = "ctrl_eye_open_right"  # → 映射到 ParamEyeROpen
    PARAM_EYE_SMILE_L = "ctrl_eye_smile_left" # → 映射到 ParamEyeLSmile
    PARAM_EYE_SMILE_R = "ctrl_eye_smile_right"# → 映射到 ParamEyeRSmile
    PARAM_BODY_ANGLE_X = "ctrl_body_sway_x"   # → 映射到 ParamBodyAngleX
    PARAM_BODY_ANGLE_Y = "ctrl_body_sway_y"   # → 映射到 ParamBodyAngleY
    PARAM_BODY_ANGLE_Z = "ctrl_body_sway_z"   # → 映射到 ParamBodyAngleZ
    PARAM_BREATH = "ctrl_breath"              # → 映射到 ParamBreath
    PARAM_BROW_Y_L = "ctrl_brow_y_left"       # → 映射到 ParamBrowLY
    PARAM_BROW_Y_R = "ctrl_brow_y_right"      # → 映射到 ParamBrowRY
    PARAM_HEAD_ANGLE_Z = "ctrl_head_angle_z"   # → 映射到 ParamAngleZ (摇头)
    PARAM_HEAD_ANGLE_X = "ctrl_head_angle_x"   # → 映射到 ParamAngleX (点头)

    async def setup_all_control_params(self):
        """
        一次性创建所有控制参数 + 打印映射指引
        首次使用调用一次即可
        """
        params_to_create = [
            (self.PARAM_MOUTH_OPEN, "ParamMouthOpenY", "嘴巴开合"),
            (self.PARAM_MOUTH_FORM, "ParamMouthForm", "嘴巴形状"),
            (self.PARAM_EYE_OPEN_L, "ParamEyeLOpen", "左眼开合"),
            (self.PARAM_EYE_OPEN_R, "ParamEyeROpen", "右眼开合"),
            (self.PARAM_BODY_ANGLE_X, "ParamBodyAngleX", "身体左右摇晃"),
            (self.PARAM_BODY_ANGLE_Y, "ParamBodyAngleY", "身体前后倾斜"),
            (self.PARAM_BODY_ANGLE_Z, "ParamBodyAngleZ", "身体歪头"),
            (self.PARAM_EYE_SMILE_L, "ParamEyeLSmile", "左眼笑眼"),
            (self.PARAM_EYE_SMILE_R, "ParamEyeRSmile", "右眼笑眼"),
            (self.PARAM_BREATH, "ParamBreath", "呼吸幅度"),
            (self.PARAM_BROW_Y_L, "ParamBrowLY", "左眉毛高低"),
            (self.PARAM_BROW_Y_R, "ParamBrowRY", "右眉毛高低"),
            (self.PARAM_HEAD_ANGLE_X, "ParamAngleX", "点头/抬头"),
        ]

        print(f"\n{'=' * 60}")
        print("  一键配置控制参数")
        print(f"{'=' * 60}")
        for param_name, live2d_target, desc in params_to_create:
            try:
                await self.create_parameter(
                    param_name,
                    min_val=-1.0, max_val=1.0, default_val=0.0,
                    explanation=f"Controls {live2d_target} ({desc})",
                )
                print(f"  ✓ 已创建: {param_name}")
            except VTSAPIError as e:
                if "already exists" in str(e).lower() or "already" in str(e).lower():
                    print(f"  · 已存在: {param_name}")
                else:
                    print(f"  ✗ 创建失败 {param_name}: {e}")

        self.print_mapping_guide()

    def print_mapping_guide(self):
        """打印 VTS 参数映射指引"""
        guide = f"""
{'=' * 60}
  ⚙ VTS 参数映射指引 — 只需设置一次
{'=' * 60}

  详细图文指引: 见 VTS_MAPPING_GUIDE.md

  操作步骤:
  1. 在 VTube Studio 中打开设置 (⚙)
  2. 找到 Live2D 参数面板（设置中通常叫 "参数" 或 "Tracking"）
  3. 对于每个 Live2D 参数，点击 "+" 添加输入源
  4. 在输入源列表中选择对应的自定义参数（ctrl_ 开头）

  最少映射（嘴巴+眼睛+身体，5 个即可）:
  ┌──────────────────────────┬─────────────────────┬──────────┐
  │ 自定义参数 (程序注入)     │ Live2D 目标参数      │ 功能      │
  ├──────────────────────────┼─────────────────────┼──────────┤
  │ {self.PARAM_MOUTH_OPEN:<24} │ ParamMouthOpenY     │ 嘴巴开合  │
  │ {self.PARAM_EYE_OPEN_L:<24} │ ParamEyeLOpen       │ 左眼开合  │
  │ {self.PARAM_EYE_OPEN_R:<24} │ ParamEyeROpen       │ 右眼开合  │
  │ {self.PARAM_BODY_ANGLE_X:<24} │ ParamBodyAngleX     │ 左右摇晃  │
  │ {self.PARAM_BODY_ANGLE_Y:<24} │ ParamBodyAngleY     │ 身体倾斜  │
  └──────────────────────────┴─────────────────────┴──────────┘

  完整映射（14 个）:
  ┌──────────────────────────┬─────────────────────┬──────────┐
  │ {self.PARAM_MOUTH_OPEN:<24} │ ParamMouthOpenY     │ 嘴巴开合  │
  │ {self.PARAM_MOUTH_FORM:<24} │ ParamMouthForm      │ 嘴巴形状  │
  │ {self.PARAM_EYE_OPEN_L:<24} │ ParamEyeLOpen       │ 左眼开合  │
  │ {self.PARAM_EYE_OPEN_R:<24} │ ParamEyeROpen       │ 右眼开合  │
  │ {self.PARAM_EYE_SMILE_L:<24} │ ParamEyeLSmile      │ 左笑眼    │
  │ {self.PARAM_EYE_SMILE_R:<24} │ ParamEyeRSmile      │ 右笑眼    │
  │ {self.PARAM_BODY_ANGLE_X:<24} │ ParamBodyAngleX     │ 左右摇晃  │
  │ {self.PARAM_BODY_ANGLE_Y:<24} │ ParamBodyAngleY     │ 身体倾斜  │
  │ {self.PARAM_BODY_ANGLE_Z:<24} │ ParamBodyAngleZ     │ 歪头      │
  │ {self.PARAM_BREATH:<24} │ ParamBreath         │ 呼吸幅度  │
  │ {self.PARAM_BROW_Y_L:<24} │ ParamBrowLY         │ 左眉高低  │
  │ {self.PARAM_BROW_Y_R:<24} │ ParamBrowRY         │ 右眉高低  │
      │ {self.PARAM_HEAD_ANGLE_X:<24} │ ParamAngleX         │ 点头抬头  │
  └──────────────────────────┴─────────────────────┴──────────┘

  提示: 先映射上面 6 个最少映射，确认生效后再映射其余的。
{'=' * 60}
"""
        print(guide)

    # ── 嘴巴控制 ─────────────────────────────────────────

    async def set_mouth_open(self, value: float):
        """
        嘴巴开合: -1.0=紧闭, 0.0=自然, 1.0=大张
        (自定义参数 -1~1 线性映射到 Live2D ParamMouthOpenY 0~1)
        """
        value = max(-1.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_MOUTH_OPEN: value})
        if value > 0.5:
            state = "大张"
        elif value > 0.1:
            state = "微张"
        elif value > -0.1:
            state = "自然闭合"
        else:
            state = "紧闭"
        logger.info(f"嘴巴: {state} (值={value:.2f})")

    async def set_mouth_form(self, value: float):
        """嘴巴形状 (微笑弧度)"""
        value = max(0.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_MOUTH_FORM: value})

    # ── 眼睛控制 ─────────────────────────────────────────

    async def set_eye_open(self, value: float):
        """
        双眼开合: -1.0=紧闭, 0.0=半睁, 1.0=全睁
        (自定义参数 -1~1 线性映射到 Live2D ParamEyeLOpen/ROpen 0~1)
        """
        value = max(-1.0, min(1.0, value))
        await self.inject_parameters({
            self.PARAM_EYE_OPEN_L: value,
            self.PARAM_EYE_OPEN_R: value,
        })
        if value > 0.7:
            state = "全睁"
        elif value > 0.3:
            state = "半睁"
        elif value > -0.3:
            state = "微睁"
        else:
            state = "紧闭"
        logger.info(f"双眼: {state} (值={value:.2f})")

    async def set_eye_left(self, value: float):
        """左眼开合"""
        value = max(0.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_EYE_OPEN_L: value})

    async def set_eye_right(self, value: float):
        """右眼开合"""
        value = max(0.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_EYE_OPEN_R: value})

    async def blink(self, duration: float = 0.12, close_val: float = -1.0):
        """
        眨眼一次

        参数:
            duration: 闭合持续时间（秒）
            close_val: 闭合程度 (-1.0=完全紧闭, -0.5=半闭), 默认 -1.0
        """
        await self.set_eye_open(close_val)
        await asyncio.sleep(duration)
        await self.set_eye_open(1.0)
        logger.info("眨眼 ✓")

    async def wink_left(self, duration: float = 0.15):
        """左眼 wink（紧闭）"""
        await self.set_eye_left(-1.0)   # -1 = 紧闭
        await asyncio.sleep(duration)
        await self.set_eye_left(1.0)

    async def wink_right(self, duration: float = 0.15):
        """右眼 wink（紧闭）"""
        await self.set_eye_right(-1.0)  # -1 = 紧闭
        await asyncio.sleep(duration)
        await self.set_eye_right(1.0)

    async def set_eye_smile(self, value: float):
        """笑眼程度: 0=正常, 1=弯弯笑眼"""
        value = max(0.0, min(1.0, value))
        await self.inject_parameters({
            self.PARAM_EYE_SMILE_L: value,
            self.PARAM_EYE_SMILE_R: value,
        })

    # ── 身体摇晃 ─────────────────────────────────────────

    async def set_body_sway_x(self, value: float):
        """
        身体左右摇晃（Live2D 骨骼 ParamBodyAngleX）

        ⚠ 需要在 VTS 中先将 ctrl_body_sway_x 映射到 ParamBodyAngleX
           运行 setup 命令查看映射指引

        参数:
            value: -1.0=大幅左倾, 0=居中, 1.0=大幅右倾
        """
        value = max(-1.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_BODY_ANGLE_X: value})
        if value > 0.3:
            d = "大幅右倾"
        elif value > 0.05:
            d = "微右倾"
        elif value < -0.3:
            d = "大幅左倾"
        elif value < -0.05:
            d = "微左倾"
        else:
            d = "居中"
        logger.info(f"身体左右: {d} (值={value:.2f})")

    async def set_body_sway_y(self, value: float):
        """
        身体前后倾斜（Live2D 骨骼 ParamBodyAngleY）

        ⚠ 需要在 VTS 中先将 ctrl_body_sway_y 映射到 ParamBodyAngleY
        """
        value = max(-1.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_BODY_ANGLE_Y: value})

    async def set_body_sway_z(self, value: float):
        """
        歪头（Live2D 骨骼 ParamBodyAngleZ）

        ⚠ 需要在 VTS 中先将 ctrl_body_sway_z 映射到 ParamBodyAngleZ
        """
        value = max(-1.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_BODY_ANGLE_Z: value})

    async def set_body_sway(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        """
        同时设置三轴身体摇晃（Live2D 骨骼参数）

        ⚠ 需要先在 VTS 中完成映射: setup → 按指引操作
        """
        params = {}
        if x != 0.0: params[self.PARAM_BODY_ANGLE_X] = max(-1.0, min(1.0, x))
        if y != 0.0: params[self.PARAM_BODY_ANGLE_Y] = max(-1.0, min(1.0, y))
        if z != 0.0: params[self.PARAM_BODY_ANGLE_Z] = max(-1.0, min(1.0, z))
        if params:
            await self.inject_parameters(params)
        logger.info(f"身体: X={x:.2f} Y={y:.2f} Z={z:.2f}")

    async def reset_body(self):
        """重置身体 Live2D 骨骼姿态"""
        await self.inject_parameters({
            self.PARAM_BODY_ANGLE_X: 0.0,
            self.PARAM_BODY_ANGLE_Y: 0.0,
            self.PARAM_BODY_ANGLE_Z: 0.0,
        })
        logger.info("身体已重置 ✓")
    async def sway_animation(self, cycles: int = 3, amplitude: float = 0.8, duration: float = 0.50):
        """
        身体左右摇晃动画（Live2D 骨骼 ParamBodyAngleX，平滑过渡）

        参数:
            cycles:    摇晃次数
            amplitude: 摇晃幅度 (0~1.0, 默认 0.8)
            duration:  单次半周期持续秒数（越大越慢，默认 0.50）
        """
        amp = max(0.1, min(1.0, amplitude))
        dur = max(0.1, duration)
        for _ in range(cycles):
            await self._smooth_param(self.PARAM_BODY_ANGLE_X, -amp, amp, dur)
            await self._smooth_param(self.PARAM_BODY_ANGLE_X, amp, -amp, dur)
        await self._smooth_param(self.PARAM_BODY_ANGLE_X, -amp, 0.0, dur * 0.5)
        logger.info("摇晃动画完成 ✓")

    async def _smooth_param(self, param_name: str, from_val: float, to_val: float,
                            duration: float, steps: int = 12):
        """平滑过渡参数值（分步注入，实现动画效果）"""
        if duration <= 0 or steps <= 1:
            await self.inject_parameters({param_name: to_val})
            return
        step_dur = duration / steps
        for i in range(1, steps + 1):
            t = i / steps
            val = from_val + (to_val - from_val) * t
            await self.inject_parameters({param_name: val})
            await asyncio.sleep(step_dur)

    async def head_shake(self, count: int = 3, amplitude: float = 0.6, duration: float = 0.40):
        """
        左右晃头（Live2D 骨骼 ParamAngleZ，否定动作）

        参数:
            count:     晃头次数
            amplitude: 幅度 (0~1.0, 默认 0.6)
            duration:  单次半周期持续秒数（越大越慢，默认 0.40）
        """
        amp = max(0.1, min(1.0, amplitude))
        dur = max(0.1, duration)
        for _ in range(count):
            await self._smooth_param(self.PARAM_HEAD_ANGLE_Z, -amp, amp, dur)
            await self._smooth_param(self.PARAM_HEAD_ANGLE_Z, amp, -amp, dur)
        await self._smooth_param(self.PARAM_HEAD_ANGLE_Z, -amp, 0.0, dur * 0.6)
        logger.info(f"晃头 {count} 次 ✓")

    async def head_nod(self, count: int = 4, amplitude: float = 0.8, duration: float = 0.35):
        """
        点头（Live2D 骨骼 ParamAngleX，肯定动作）

        参数:
            count:     点头次数
            amplitude: 幅度 (0~1.0, 默认 0.8)
            duration:  单次半周期持续秒数（越大越慢，默认 0.35）
        """
        amp = max(0.1, min(1.0, amplitude))
        dur = max(0.1, duration)
        for _ in range(count):
            await self._smooth_param(self.PARAM_HEAD_ANGLE_X, 0.0, amp, dur)
            await self._smooth_param(self.PARAM_HEAD_ANGLE_X, amp, 0.0, dur)
            await asyncio.sleep(0.2)  # 点头间停顿
        logger.info(f"点头 {count} 次 ✓")


    # ── 呼吸 ─────────────────────────────────────────────

    async def set_breath(self, value: float):
        """呼吸幅度"""
        value = max(0.0, min(1.0, value))
        await self.inject_parameters({self.PARAM_BREATH: value})

    # ── 眉毛 ─────────────────────────────────────────────

    async def set_eyebrow_raise(self, value: float):
        """抬眉毛 (0=正常, 1=抬高)"""
        value = max(0.0, min(1.0, value))
        await self.inject_parameters({
            self.PARAM_BROW_Y_L: value,
            self.PARAM_BROW_Y_R: value,
        })

    # ── VTS Item（道具/贴纸）管理 ─────────────────────────

    async def load_item(self, file_name: str) -> str:
        """
        加载一个 Item（PNG 图片需先放入 VTS Items 目录）
        自动清理同名旧实例，避免重复。

        返回: instanceID（后续操作用）
        """
        # 先卸载同名旧 item
        items = await self._send("ItemListRequest", {
            "includeAvailableItems": False,
            "includeItemInstancesInScene": True,
        })
        for inst in items.get("itemInstancesInScene", []):
            if inst.get("fileName") == file_name:
                try:
                    await self._send("ItemUnloadRequest", {
                        "itemInstanceID": inst["instanceID"],
                    })
                    logger.info(f"清理旧 Item: {file_name}")
                except Exception:
                    pass

        data = await self._send("ItemLoadRequest", {"fileName": file_name})
        item_id = data.get("instanceID", "")
        logger.info(f"已加载 Item: {file_name} (id={item_id[:12]}...)")
        return item_id

    async def move_item(self, instance_id: str,
                        position_x: float = 0.0, position_y: float = 0.0,
                        size: float = 0.5, rotation: float = 0.0,
                        order: int = 10, time_seconds: float = 0.0):
        """
        移动/缩放/旋转已加载的 Item

        参数:
            position_x:  X 偏移 (-1~1, 相对屏幕宽度)
            position_y:  Y 偏移 (-1~1, 相对屏幕高度, 正值=上)
            size:        缩放 (-1~1, 相对原始大小, 0.5=半大)
            rotation:    旋转角度
            order:       渲染顺序 (越大越靠前)
        """
        await self._send("ItemMoveRequest", {
            "itemInstanceID": instance_id,
            "positionX": position_x,
            "positionY": position_y,
            "size": size,
            "rotation": rotation,
            "order": order,
            "timeInSeconds": time_seconds,
        })

    async def unload_item(self, instance_id: str):
        """卸载 Item"""
        await self._send("ItemUnloadRequest", {
            "itemInstanceID": instance_id,
        })
        logger.info(f"已卸载 Item: {instance_id[:12]}...")

    async def list_items(self) -> list[dict]:
        """列出所有已加载的 Item"""
        data = await self._send("ItemListRequest", {
            "includeAvailableItems": False,
            "includeItemInstancesInScene": True,
        })
        return data.get("items", [])

    # ── 模型物理移动 ─────────────────────────────────────

    async def move_model(
        self,
        position_x: Optional[float] = None,
        position_y: Optional[float] = None,
        rotation: Optional[float] = None,
        size: Optional[float] = None,
        time_seconds: float = 0.3,
    ):
        """
        物理移动/旋转/缩放模型在屏幕上的位置

        参数:
            position_x: X 偏移 (-1.0 ~ 1.0, 相对屏幕宽度)
            position_y: Y 偏移 (-1.0 ~ 1.0, 相对屏幕高度)
            rotation:   旋转角度 (-360 ~ 360 度)
            size:       缩放 (-1.0 ~ 1.0, 相对原始大小)
            time_seconds: 移动到目标所需时间
        """
        data = {"timeInSeconds": time_seconds}
        if position_x is not None:
            data["positionX"] = position_x
        if position_y is not None:
            data["positionY"] = position_y
        if rotation is not None:
            data["rotation"] = rotation
        if size is not None:
            data["size"] = size
        await self._send("MoveModelRequest", data)
        logger.info(f"模型移动: {data}")

    # ══════════════════════════════════════════════════════════
    #  四、模型部件控制
    # ══════════════════════════════════════════════════════════

    async def fetch_art_meshes(self) -> list[ArtMesh]:
        """获取所有 ArtMesh（模型部件）"""
        data = await self._send("ArtMeshListRequest", {})
        meshes = []
        for item in data.get("artMeshList", []):
            meshes.append(ArtMesh(
                name=item.get("name", ""),
                enabled=item.get("enabled", True),
                group=item.get("group", ""),
            ))
        self._art_meshes = meshes
        return meshes

    async def list_art_meshes(self, refresh: bool = False) -> list[ArtMesh]:
        """获取 ArtMesh 列表"""
        if refresh or not self._art_meshes:
            await self.fetch_art_meshes()
        return self._art_meshes

    async def set_art_meshes(self, enabled: dict[str, bool]):
        """设置部件显示/隐藏: {"部件名": True/False}"""
        art_mesh_list = [{"name": n, "enabled": f} for n, f in enabled.items()]
        await self._send("ArtMeshSelectionRequest", {"artMeshList": art_mesh_list})

    # ══════════════════════════════════════════════════════════
    #  五、模型信息
    # ══════════════════════════════════════════════════════════

    async def get_model_info(self) -> dict:
        """获取当前模型信息"""
        data = await self._send("CurrentModelRequest", {})
        self._model_name = data.get("modelName", "未知")
        return data

    # ══════════════════════════════════════════════════════════
    #  六、综合展示
    # ══════════════════════════════════════════════════════════

    async def print_full_summary(self):
        """打印完整信息"""
        model = await self.get_model_info()
        expressions = await self.list_expressions()
        hotkeys = await self.list_hotkeys()
        params = await self.list_parameters()
        meshes = await self.list_art_meshes()

        model_name = model.get("modelName", "未知")
        print(f"\n{'=' * 60}")
        print(f"  模型: {model_name}")
        print(f"{'=' * 60}")

        print(f"\n  🎭 表情 ({len(expressions)} 个)  ← 可直接控制，无需热键:")
        for i, expr in enumerate(expressions):
            status = "🟢" if expr.active else "⚪"
            print(f"     [{i}] {status} {expr.name}  ({expr.file})")

        print(f"\n  ⌨ 热键 ({len(hotkeys)} 个)  ← 需在VTS中手动配置:")
        if hotkeys:
            for i, hk in enumerate(hotkeys):
                print(f"     [{i}] {hk}")
        else:
            print(f"     (无 — 如需要动作，请在 VTS 中为动作文件配置热键)")

        print(f"\n  📐 Live2D 参数 ({len(params)} 个):")
        for p in params[:20]:
            print(f"     {p}")
        if len(params) > 20:
            print(f"     ... 还有 {len(params) - 20} 个参数")

        print(f"\n  🧩 ArtMesh 部件 ({len(meshes)} 个):")
        for m in meshes[:15]:
            print(f"     {m}")
        if len(meshes) > 15:
            print(f"     ... 还有 {len(meshes) - 15} 个部件")

        print(f"\n{'=' * 60}")
        print("  常用操作:")
        print("    await vts.activate_expression_by_name('表情名')   激活")
        print("    await vts.deactivate_expression_by_name('表情名') 停用")
        print("    await vts.deactivate_all_expressions()          回默认")
        print("    await vts.activate_expression_by_index(0)       按索引激活")
        print("    await vts.inject_parameters({'MouthSmile': 0.8}) 控制参数")
        print(f"{'=' * 60}\n")


# ═══════════════════════════════════════════════════════════════
#  同步封装（不需要 async/await）
# ═══════════════════════════════════════════════════════════════

class VTSControllerSync:
    """
    VTSController 的同步封装

    用法:
        vts = VTSControllerSync()
        vts.connect()
        vts.activate_expression_by_name("Smile")
        vts.disconnect()
    """

    def __init__(self, host: str = "localhost", port: int = 8001):
        self._c = VTSController(host, port)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def connect(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._run(self._c.connect())

    def disconnect(self):
        if self._loop:
            self._run(self._c.disconnect())
            self._loop.close()
            self._loop = None

    # 代理 — 表情
    def list_expressions(self, refresh=False):
        return self._run(self._c.list_expressions(refresh))
    def activate_expression_by_name(self, name, active=True):
        return self._run(self._c.activate_expression_by_name(name, active))
    def deactivate_expression_by_name(self, name):
        return self._run(self._c.deactivate_expression_by_name(name))
    def activate_expression_by_index(self, index, active=True):
        return self._run(self._c.activate_expression_by_index(index, active))
    def deactivate_expression_by_index(self, index):
        return self._run(self._c.deactivate_expression_by_index(index))
    def deactivate_all_expressions(self):
        return self._run(self._c.deactivate_all_expressions())
    def play_all_expressions(self, delay=0.5):
        return self._run(self._c.play_all_expressions(delay))

    # 代理 — 热键
    def list_hotkeys(self, refresh=False):
        return self._run(self._c.list_hotkeys(refresh))
    def trigger_hotkey_by_name(self, name):
        return self._run(self._c.trigger_hotkey_by_name(name))
    def trigger_hotkey_by_index(self, idx):
        return self._run(self._c.trigger_hotkey_by_index(idx))

    # 代理 — 参数
    def list_parameters(self, refresh=False):
        return self._run(self._c.list_parameters(refresh))
    def search_parameters(self, keyword):
        return self._run(self._c.search_parameters(keyword))
    def inject_parameters(self, params: dict):
        return self._run(self._c.inject_parameters(params))
    def reset_parameters(self):
        return self._run(self._c.reset_parameters())
    def setup_all_control_params(self):
        return self._run(self._c.setup_all_control_params())

    # 代理 — 嘴巴/眼睛/身体
    def set_mouth_open(self, v):
        return self._run(self._c.set_mouth_open(v))
    def set_eye_open(self, v):
        return self._run(self._c.set_eye_open(v))
    def blink(self, duration=0.15):
        return self._run(self._c.blink(duration))
    def wink_left(self, duration=0.2):
        return self._run(self._c.wink_left(duration))
    def wink_right(self, duration=0.2):
        return self._run(self._c.wink_right(duration))
    def set_eye_smile(self, v):
        return self._run(self._c.set_eye_smile(v))
    def set_body_sway(self, x=0, y=0, z=0):
        return self._run(self._c.set_body_sway(x, y, z))
    def set_body_sway_x(self, v):
        return self._run(self._c.set_body_sway_x(v))
    def reset_body(self):
        return self._run(self._c.reset_body())
    def sway_animation(self, cycles=3, amplitude=0.5, speed=0.3):
        return self._run(self._c.sway_animation(cycles, amplitude, speed))
    def move_model(self, position_x=None, position_y=None, rotation=None, size=None, time_seconds=0.3):
        return self._run(self._c.move_model(position_x, position_y, rotation, size, time_seconds))

    # 代理 — 其他
    def list_art_meshes(self, refresh=False):
        return self._run(self._c.list_art_meshes(refresh))
    def set_art_meshes(self, enabled: dict):
        return self._run(self._c.set_art_meshes(enabled))
    def print_full_summary(self):
        return self._run(self._c.print_full_summary())

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()


# ═══════════════════════════════════════════════════════════════
#  状态监控
# ═══════════════════════════════════════════════════════════════

async def monitor_expressions(
    controller: VTSController,
    on_change: Callable[[str, str], Any],
    interval: float = 0.3,
):
    """轮询监控表情状态变化"""
    prev: dict[str, bool] = {}
    while True:
        try:
            states = await controller.list_expressions(refresh=True)
            current = {s.name: s.active for s in states}
            for name, active in current.items():
                old = prev.get(name)
                if old is not None and old != active:
                    on_change(name, "激活" if active else "停用")
            prev = current
        except Exception as e:
            logger.error(f"监控出错: {e}")
        await asyncio.sleep(interval)
