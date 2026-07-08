"""
ELF2 本地 AI 对话管线 —— 已升级为完整 Agent 架构。

从简单内联 Prompt 升级为:
  记忆加载 → RAG 植物知识检索 → 联网搜索 → 角色化回答

使用从 PC 端迁移至 ELF2 的 agent 包。
"""
import asyncio
import database
from agent.agent import elf2_agent


async def run(dialog_queue: asyncio.Queue, tts_queue: asyncio.Queue):
    """对话协程: 从 dialog_queue 取用户文本 → Agent → TTS队列。

    dialog_queue 中的文本来自 intent_router (未匹配硬件指令的语音输入)。
    """
    while True:
        user_text: str = await dialog_queue.get()

        # === 使用 ELF2 本地 Agent (从 PC 端迁移的完整 AI 大脑) ===
        reply = await asyncio.to_thread(
            elf2_agent.chat,
            user_text,
            user_id="elf2_voice",  # 语音用户独立记忆
        )

        print(f"[对话] 用户: {user_text}")
        print(f"[对话] 酢酱酱: {reply}")

        # 持久化到 MySQL
        await asyncio.to_thread(
            database.save_chat_message, "elf2_voice", "user", user_text
        )
        await asyncio.to_thread(
            database.save_chat_message, "elf2_voice", "assistant", reply
        )

        # 推送到 TTS 队列
        await tts_queue.put(reply)
