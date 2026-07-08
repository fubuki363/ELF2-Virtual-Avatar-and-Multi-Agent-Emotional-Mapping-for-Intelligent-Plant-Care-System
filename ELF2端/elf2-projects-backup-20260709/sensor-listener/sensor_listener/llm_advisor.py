"""LLM advisor — DeepSeek API integration for intelligent greenhouse decisions."""
import asyncio
import json
import time
from collections import namedtuple

LLMDecision = namedtuple("LLMDecision", ["commands", "reason", "confidence"])

SYSTEM_PROMPT = """你是一个智能温室控制器。根据传感器数据给出设备调节建议。

可用设备:
- fan(0-100): 散热风扇，占空比百分比
- heater(0-100): 加热片，占空比百分比
- pump(0-100): 水泵/浇水，占空比百分比
- humidifier(0-100): 加湿器，占空比百分比
- led(mode:"effect"|"white", effect:"rainbow"|"breathing"|"off", brightness:0-255): LED灯带

规则:
- 温度 18-28°C 理想，>30°C 开风扇，<18°C 开加热
- 土壤湿度 1000-2500 (ADC, 越低越湿)，>2500 考虑浇水
- 光照 <50 lux 时考虑补光
- 环境湿度 50-80% 理想
- 输出必须是 JSON: {"actions":[{"d":"fan","v":80}],"reason":"简短中文理由","confidence":0.0-1.0}
- 不确定时宁可保守，confidence 设低
- 只调整有问题的设备，正常的不要动"""


class LLMAdvisor:
    """Calls DeepSeek API on sensor threshold events for intelligent control decisions."""

    def __init__(self, api_key: str, model: str = "deepseek-chat",
                 max_failures: int = 3, pause_seconds: float = 300.0):
        self._api_key = api_key
        self._model = model
        self._max_failures = max_failures
        self._pause_seconds = pause_seconds
        self._failure_count = 0
        self._paused_until: float = 0.0
        self._client = None  # Lazy init

    def _ensure_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url="https://api.deepseek.com/v1",
            )
        return self._client

    def should_consult(self, trigger_type: str, data_history: list[dict]) -> bool:
        """Check if trigger conditions warrant LLM consultation."""
        if self._is_paused():
            return False
        if len(data_history) < 2:
            return False

        if trigger_type == "soil_dry":
            # Soil > 2500 for last 10 readings
            return all(d.get("soil", 0) > 2500 for d in data_history[-10:])
        elif trigger_type == "temp_rising":
            # Temperature rose > 3°C over the window
            if len(data_history) < 30:
                return False
            first_t = data_history[0].get("t")
            last_t = data_history[-1].get("t")
            if first_t is None or last_t is None:
                return False
            return (last_t - first_t) > 3.0
        elif trigger_type == "health_low":
            # Health score sustained below 60 — checked by AnalysisEngine
            return True
        return False

    async def consult(
        self, trigger_reason: str, data_history: list[dict], analysis_summary: dict
    ) -> LLMDecision | None:
        """Consult DeepSeek for control recommendations. Returns None on failure."""

        if self._is_paused():
            return None

        client = self._ensure_client()

        # Build user prompt from sensor history
        latest = data_history[-1] if data_history else {}
        history_text = "\n".join(
            f"t={d.get('t','?')}°C h={d.get('h','?')}% soil={d.get('soil','?')} "
            f"light={d.get('light','?')}lux eco2={d.get('eco2','?')}ppm"
            for d in data_history[-5:]  # Last 5 readings
        )

        user_prompt = f"""触发原因: {trigger_reason}

最近传感器数据:
{history_text}

分析摘要: 健康指数 {analysis_summary.get('health', '?')}/100
趋势: {analysis_summary.get('trends', {})}
告警: {analysis_summary.get('alerts', [])}

请给出设备调节建议（JSON格式）。"""

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=300,
                ),
                timeout=3.0,
            )

            content = response.choices[0].message.content
            # Extract JSON from response (may have markdown fences)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = json.loads(content)

            commands = result.get("actions", [])
            reason = result.get("reason", "LLM 建议")
            confidence = result.get("confidence", 0.5)

            self._failure_count = 0  # Reset on success
            return LLMDecision(commands=commands, reason=reason, confidence=confidence)

        except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
            self._failure_count += 1
            if self._failure_count >= self._max_failures:
                self._paused_until = time.time() + self._pause_seconds
                import sys
                print(f"[LLM] 连续失败 {self._failure_count} 次，暂停 {self._pause_seconds} 秒", file=sys.stderr)
            else:
                import sys
                print(f"[LLM] 调用失败 ({self._failure_count}/{self._max_failures}): {e}", file=sys.stderr)
            return None

    def _is_paused(self) -> bool:
        if self._paused_until > time.time():
            return True
        if self._paused_until > 0 and self._paused_until <= time.time():
            self._paused_until = 0.0
            self._failure_count = 0  # Resume
        return False
