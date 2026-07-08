"""
ELF2 本地 Agent 包 —— 从 PC 端迁移至 ELF2 的 AI 核心模块。

包含:
- skills/: 角色人设提示词系统
- llm.py: 统一的 LLM 客户端 (DeepSeek)
- agent.py: LangGraph 工作流 (记忆 → RAG → 联网 → 回答)
- rag.py: 植物知识库向量检索
- emotion.py: LLM 情绪分析
- memory.py: 长期记忆管理
"""
