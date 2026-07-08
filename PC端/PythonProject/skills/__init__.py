"""
Skills 组合器 —— 将各技能模块拼接为完整的系统提示词

用法：
    from skills import compose_system_prompt
    prompt = compose_system_prompt()
"""

from skills.persona import PERSONA_PROMPT
from skills.expertise import EXPERTISE_PROMPT
from skills.conversation import CONVERSATION_PROMPT


def compose_system_prompt() -> str:
    """
    组合所有技能模块，生成完整的系统提示词。

    返回拼接后的完整 Prompt 字符串。
    各模块按「身份 → 知识 → 表达」的顺序组合，
    形成层层递进的角色定义体系。
    """
    parts = [
        PERSONA_PROMPT.strip(),
        EXPERTISE_PROMPT.strip(),
        CONVERSATION_PROMPT.strip(),
    ]
    return "\n\n".join(parts)
