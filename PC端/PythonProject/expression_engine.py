"""
表情引擎 —— VTS 虚拟形象的表情调度中心

职责：
1. 将情绪标签映射到 Mina Girl 模型的具体表情和动画
2. 管理表情状态（同一时间只激活一个表情）
3. 环境数据 → 表情的映射（缺水/高温等触发）
4. 提供同步 + 异步接口，适配 main.py 的多线程架构

用法：
    from expression_engine import ExpressionEngine

    engine = ExpressionEngine()
    await engine.connect()
    await engine.set_mood("happy")
    await engine.disconnect()
"""

import asyncio
import logging
import random
import time
import threading
from typing import Optional

from vts_controller import VTSController

logger = logging.getLogger("expression_engine")

# ═══════════════════════════════════════════════════════════════
#  表情映射表：情绪 → (Mina Girl 表情文件, Live2D 参数, 动画)
# ═══════════════════════════════════════════════════════════════

MOOD_MAP = {
    "happy": {
        "expression": "Starry eyes.exp3.json",
        "params": {"ctrl_eye_smile_left": 0.8, "ctrl_eye_smile_right": 0.8},
        "animation": "sway",
        "description": "开心",
    },
    "excited": {
        "expression": "Love eyes.exp3.json",
        "params": {"ctrl_eye_smile_left": 1.0, "ctrl_eye_smile_right": 1.0},
        "animation": "nod",
        "description": "超开心/兴奋",
    },
    "shy": {
        "expression": "Blush.exp3.json",
        "params": {"ctrl_body_sway_x": 0.0},
        "animation": "sway_small",
        "description": "害羞/被夸奖",
    },
    "sad": {
        "expression": "Tears.exp3.json",
        "params": {"ctrl_body_sway_y": -0.3, "ctrl_eye_smile_left": 0.0, "ctrl_eye_smile_right": 0.0},
        "animation": None,
        "description": "难过/委屈",
    },
    "angry": {
        "expression": "angry.exp3.json",
        "params": {"ctrl_body_sway_z": 0.0},
        "animation": "shake",
        "description": "生气/不满",
    },
    "shocked": {
        "expression": "Swoon.exp3.json",
        "params": {},
        "animation": None,
        "description": "震惊/无语",
    },
    "curious": {
        "expression": "Glasses.exp3.json",
        "params": {"ctrl_body_sway_x": 0.0},
        "animation": None,
        "description": "好奇/科普中",
    },
    "neutral": {
        "expression": "Ponytail.exp3.json",
        "params": {"ctrl_body_sway_x": 0.0, "ctrl_body_sway_y": 0.0,
                   "ctrl_body_sway_z": 0.0, "ctrl_eye_smile_left": 0.3,
                   "ctrl_eye_smile_right": 0.3},
        "animation": "idle_blink",
        "description": "日常/中性",
    },
}

# 环境触发阈值
ENV_TRIGGERS = {
    "soil_moisture_low": {
        "threshold": 20,       # 土壤湿度低于 20% 触发
        "mood": "sad",
        "message": "唔…我的土壤好干呀，叶子都快没精神了…有人能帮我浇点水吗？",
    },
    "soil_moisture_ok": {
        "threshold": 60,       # 土壤湿度回到 60% 以上
        "mood": "happy",
        "message": "哇～喝饱水啦！感觉每一片叶子都在唱歌！谢谢你～",
    },
    "temperature_high": {
        "threshold": 35,       # 温度超过 35°C
        "mood": "shocked",
        "message": "好…好热！作为一株酢浆草，我要融化了！救命～",
    },
}


# ═══════════════════════════════════════════════════════════════
#  表情引擎（异步版）
# ═══════════════════════════════════════════════════════════════

class ExpressionEngine:
    """
    表情调度中心 —— 管理 VTS 虚拟形象的表情状态。

    核心规则：
    - 同一时间只有一个表情激活
    - 切换表情时自动停用旧表情
    - 表情持续一段时间后自动回到 neutral
    """

    def __init__(self, host: str = "localhost", port: int = 8001):
        self._vts = VTSController(host, port)
        self._current_mood: str = "neutral"
        self._expression_active: Optional[str] = None
        self._expression_timer: Optional[asyncio.Task] = None
        self._expression_duration: float = 8.0  # 表情持续时间（秒）

    # ── 连接管理 ──────────────────────────────────────────

    async def connect(self):
        """连接 VTube Studio 并初始化表情"""
        await self._vts.connect()
        # 获取表情列表以填充缓存
        await self._vts.fetch_expressions()
        logger.info("ExpressionEngine 已连接 VTS ✓")

    async def disconnect(self):
        """断开连接，先回到默认表情"""
        try:
            await self._reset_expression()
        except Exception:
            pass
        await self._vts.disconnect()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    @property
    def current_mood(self) -> str:
        return self._current_mood

    # ── 核心方法 ──────────────────────────────────────────

    async def set_mood(self, mood: str, duration: float = None):
        """
        设置表情 mood。

        参数:
            mood: 情绪标签 (happy/excited/shy/sad/angry/shocked/curious/neutral)
            duration: 表情持续时间（秒），None 则使用默认 8 秒
        """
        if mood not in MOOD_MAP:
            logger.warning(f"未知情绪 '{mood}'，使用 neutral")
            mood = "neutral"

        config = MOOD_MAP[mood]

        # 如果和当前一样，不重复激活
        if mood == self._current_mood and self._expression_active == config["expression"]:
            return

        # 1. 停用旧表情
        await self._reset_expression()

        # 2. 注入 Live2D 参数
        params = config.get("params", {})
        if params:
            try:
                await self._vts.inject_parameters(params)
            except Exception as e:
                logger.debug(f"参数注入失败（可忽略）: {e}")

        # 3. 激活新表情
        try:
            await self._vts.activate_expression(config["expression"], active=True)
            self._expression_active = config["expression"]
            self._current_mood = mood
            logger.info(f"表情: {config['description']} ({mood})")
        except Exception as e:
            logger.warning(f"表情激活失败 '{config['expression']}': {e}")
            return

        # 4. 执行动画
        animation = config.get("animation")
        if animation:
            await self._play_animation(animation)

        # 5. 设置自动恢复定时器
        dur = duration if duration is not None else self._expression_duration
        if self._expression_timer:
            self._expression_timer.cancel()
        self._expression_timer = asyncio.ensure_future(
            self._auto_reset(dur)
        )

    async def react_to_message(self, user_text: str) -> dict:
        """
        对用户消息做出表情反应。

        返回: 分析结果 dict
        """
        from emotion_analyzer import analyze_user_message
        result = analyze_user_message(user_text)
        mood = result.get("emotion", "neutral")
        await self.set_mood(mood)
        return result

    async def react_to_reply(self, reply_text: str) -> dict:
        """
        根据 AI 回复内容调整表情。

        返回: 分析结果 dict
        """
        from emotion_analyzer import analyze_reply_emotion
        result = analyze_reply_emotion(reply_text)
        mood = result.get("emotion", "neutral")
        await self.set_mood(mood)
        return result

    async def react_to_sensor(self, sensor_type: str, value: float) -> Optional[dict]:
        """
        根据传感器数据触发环境表情。
        仅在阈值跨越时触发，避免频繁变化。

        返回: 触发信息 dict，未触发则返回 None
        """
        # 检查土壤湿度
        if sensor_type in ("soil_moisture", "soil_moisture.get"):
            if value < ENV_TRIGGERS["soil_moisture_low"]["threshold"]:
                if self._current_mood != "sad":
                    trigger = ENV_TRIGGERS["soil_moisture_low"]
                    await self.set_mood(trigger["mood"], duration=12.0)
                    return {"triggered": True, "message": trigger["message"]}
            elif value >= ENV_TRIGGERS["soil_moisture_ok"]["threshold"]:
                if self._current_mood == "sad":
                    trigger = ENV_TRIGGERS["soil_moisture_ok"]
                    await self.set_mood(trigger["mood"], duration=10.0)
                    return {"triggered": True, "message": trigger["message"]}

        # 检查温度
        if sensor_type in ("temperature", "temperature.get", "sys.cpu.temp"):
            if value > ENV_TRIGGERS["temperature_high"]["threshold"]:
                if self._current_mood != "shocked":
                    trigger = ENV_TRIGGERS["temperature_high"]
                    await self.set_mood(trigger["mood"], duration=10.0)
                    return {"triggered": True, "message": trigger["message"]}

        return None

    async def reset(self):
        """手动回到默认表情"""
        await self._reset_expression()
        self._current_mood = "neutral"
        self._expression_active = None
        if self._expression_timer:
            self._expression_timer.cancel()
            self._expression_timer = None

    # ── 内部方法 ──────────────────────────────────────────

    async def _reset_expression(self):
        """停用当前激活的表情"""
        if self._expression_active:
            try:
                await self._vts.activate_expression(self._expression_active, active=False)
            except Exception as e:
                logger.debug(f"停用表情失败（可忽略）: {e}")
            self._expression_active = None

    async def _play_animation(self, animation: str):
        """播放动画"""
        try:
            if animation == "sway":
                await self._vts.sway_animation(cycles=2, amplitude=0.5, duration=0.4)
            elif animation == "sway_small":
                await self._vts.sway_animation(cycles=1, amplitude=0.25, duration=0.5)
            elif animation == "nod":
                await self._vts.head_nod(count=3, amplitude=0.5, duration=0.3)
            elif animation == "shake":
                await self._vts.head_shake(count=3, amplitude=0.5, duration=0.35)
            elif animation == "idle_blink":
                await self._vts.blink(duration=0.1)
        except Exception as e:
            logger.debug(f"动画播放失败: {e}")

    async def _auto_reset(self, delay: float):
        """延迟后自动回到 neutral"""
        await asyncio.sleep(delay)
        if self._current_mood != "neutral":
            await self.set_mood("neutral")


# ═══════════════════════════════════════════════════════════════
#  同步封装（供 main.py 的多线程架构使用）
# ═══════════════════════════════════════════════════════════════

class ExpressionEngineSync:
    """
    ExpressionEngine 的同步封装。

    用于 main.py 中的非 async 上下文（如 process_qq_message_sync 等）。
    内部维护独立的 event loop 线程。
    """

    def __init__(self, host: str = "localhost", port: int = 8001):
        self._engine = ExpressionEngine(host, port)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def _run_loop(self):
        """在独立线程中运行 event loop"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._engine.connect())
        self._ready.set()
        # 保持 loop 运行以处理后续任务
        try:
            self._loop.run_forever()
        except Exception:
            pass

    def start(self):
        """启动 VTS 连接（在后台线程中）"""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=30)  # 等待连接完成

    def stop(self):
        """停止并断开连接"""
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._engine.disconnect(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self, coro):
        """在后台 loop 中执行协程"""
        if not self._loop or not self._loop.is_running():
            logger.warning("VTS event loop 未运行")
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=10)
        except Exception as e:
            logger.warning(f"VTS 操作超时或失败: {e}")
            return None

    # ── 代理方法 ──────────────────────────────────────────

    def set_mood(self, mood: str, duration: float = None):
        """设置表情（同步）"""
        return self._run(self._engine.set_mood(mood, duration))

    def react_to_message(self, user_text: str) -> dict:
        """对用户消息做出反应（同步）"""
        return self._run(self._engine.react_to_message(user_text))

    def react_to_reply(self, reply_text: str) -> dict:
        """根据 AI 回复调整表情（同步）"""
        return self._run(self._engine.react_to_reply(reply_text))

    def react_to_sensor(self, sensor_type: str, value: float) -> Optional[dict]:
        """传感器触发（同步）"""
        return self._run(self._engine.react_to_sensor(sensor_type, value))

    def reset(self):
        """重置表情（同步）"""
        return self._run(self._engine.reset())

    def blink(self):
        """眨眼一次"""
        return self._run(self._engine._vts.blink())

    def idle_animation(self):
        """随机闲时小动作"""
        actions = [
            lambda: self._engine._vts.blink(),
            lambda: self._engine._vts.sway_animation(cycles=1, amplitude=0.2, duration=0.6),
        ]
        action = random.choice(actions)
        return self._run(action())

    @property
    def current_mood(self) -> str:
        return self._engine.current_mood
