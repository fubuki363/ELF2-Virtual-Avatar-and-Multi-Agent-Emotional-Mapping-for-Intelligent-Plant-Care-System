"""
情绪分析器 —— 从 PC 端迁移至 ELF2。
利用 LLM 分类对话文本中的情绪，用于驱动 VTS 虚拟形象表情。
"""
import json
from .llm import llm

EMOTION_LABELS = [
    "happy", "excited", "shy", "sad", "angry",
    "shocked", "curious", "neutral",
]


def analyze_emotion(text: str, context: str = "user_message") -> dict:
    """分析文本中的情绪。

    Args:
        text: 要分析的文本
        context: "user_message" 或 "ai_reply"

    Returns:
        {"emotion": str, "intensity": float, "reason": str}
    """
    prompt = f"""
你是一个情绪分析器。请分析以下文本所表达的情绪。

情绪标签（只能从以下选择一个）：
{", ".join(EMOTION_LABELS)}

分析场景：{"用户发来的消息" if context == "user_message" else "AI的回复内容"}

文本内容："{text[:200]}"

请返回 JSON 格式（不要包含其他内容）：
{{"emotion": "情绪标签", "intensity": 0.0~1.0, "reason": "简短原因(5字以内)"}}

注意：
- 如果用户骂人或嘲讽，emotion 应为 "angry"
- 如果是普通问题，emotion 应为 "neutral" 或 "curious"
- AI回复如果是科普内容，emotion 应为 "curious"
"""
    try:
        response = llm.invoke(prompt, max_tokens=100)
        result = json.loads(response.content.strip())
        if result.get("emotion") not in EMOTION_LABELS:
            result["emotion"] = "neutral"
        result.setdefault("intensity", 0.5)
        result.setdefault("reason", "")
        return result
    except Exception:
        return {"emotion": "neutral", "intensity": 0.3, "reason": "默认"}


def analyze_user_message(text: str) -> dict:
    """快捷方法：分析用户消息情绪。"""
    return analyze_emotion(text, context="user_message")


def analyze_reply_emotion(text: str) -> dict:
    """快捷方法：分析 AI 回复情绪。"""
    return analyze_emotion(text, context="ai_reply")
