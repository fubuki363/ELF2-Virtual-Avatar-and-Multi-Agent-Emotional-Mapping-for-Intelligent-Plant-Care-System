"""
情绪分析器 —— 分析对话文本中的情绪

利用 LLM 快速分类用户消息和 AI 回复中的情绪，
用于驱动 VTS 虚拟形象的表情变化。
"""

from llm import llm

# 情绪标签集
EMOTION_LABELS = [
    "happy",      # 开心/喜悦
    "excited",    # 兴奋/激动
    "shy",        # 害羞/不好意思
    "sad",        # 难过/悲伤
    "angry",      # 生气/不满
    "shocked",    # 震惊/惊讶
    "curious",    # 好奇/求知
    "neutral",    # 中性/日常
]


def analyze_emotion(text: str, context: str = "user_message") -> dict:
    """
    分析文本中的情绪。

    参数:
        text: 要分析的文本
        context: 场景类型 — "user_message" 或 "ai_reply"

    返回:
        dict: {"emotion": str, "intensity": float, "reason": str}
                emotion: 情绪标签
                intensity: 强度 0.0~1.0
                reason: 简短的原因说明
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
- 如果用户骂人或嘲讽（如"你好笨""滚"），emotion 应为 "angry"
- 如果用户夸奖或表达喜欢，emotion 应为 "happy" 或 "shy"
- 如果是普通问题，emotion 应为 "neutral" 或 "curious"
- AI回复如果是科普内容，emotion 应为 "curious"
- 如果是安慰或温暖的话，emotion 应为 "happy"
"""

    try:
        response = llm.invoke(prompt)
        import json
        result = json.loads(response.content.strip())
        # 验证返回值
        if result.get("emotion") not in EMOTION_LABELS:
            result["emotion"] = "neutral"
        result.setdefault("intensity", 0.5)
        result.setdefault("reason", "")
        return result
    except Exception:
        # 解析失败时返回中性
        return {"emotion": "neutral", "intensity": 0.3, "reason": "默认"}


def analyze_user_message(text: str) -> dict:
    """分析用户消息的情绪（快捷方法）"""
    return analyze_emotion(text, context="user_message")


def analyze_reply_emotion(text: str) -> dict:
    """分析 AI 回复的情绪（快捷方法）"""
    return analyze_emotion(text, context="ai_reply")
