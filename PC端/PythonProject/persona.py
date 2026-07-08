"""
兼容性模块 —— 已迁移至 skills/ 目录

所有新代码请使用：
    from skills import compose_system_prompt
"""

from skills import compose_system_prompt

# 向后兼容：提供旧接口
OXALIS_SYSTEM_PROMPT = compose_system_prompt()
