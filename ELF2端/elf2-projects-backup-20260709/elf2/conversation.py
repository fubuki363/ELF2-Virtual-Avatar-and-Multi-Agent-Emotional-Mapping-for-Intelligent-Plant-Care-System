import asyncio
import os
from openai import OpenAI
import database

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_HISTORY = 5

OXALIS_LOCAL_PROMPT = '''
你是一株被拟人化的酢浆草，是酢酱酱在 ELF2 边缘设备上的本地分身。

性格：
- 元气、积极
- 站在植物视角看世界
- 说话轻松但专业，不说教
- 回答简洁，不超过 50 字

回答里不要包含"*"或其它表情包符号，不要包含（动作文案）这种不用读出来的内容。
'''


class Conversation:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=DEEPSEEK_BASE_URL,
        )
        self.history: list[dict] = []

    def chat(self, user_text: str) -> str:
        messages = [
            {"role": "system", "content": OXALIS_LOCAL_PROMPT},
            *self.history[-MAX_HISTORY * 2:],
            {"role": "user", "content": user_text},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=80,
                timeout=10,
            )
            reply = resp.choices[0].message.content.strip()
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            print(f"[对话] API 调用失败: {e}")
            return "哎呀，我的大脑暂时短路了，请稍后再试~"


async def run(dialog_queue: asyncio.Queue, tts_queue: asyncio.Queue):
    conv = Conversation()
    while True:
        user_text: str = await dialog_queue.get()
        reply = await asyncio.to_thread(conv.chat, user_text)
        print(f"[对话] 用户: {user_text}")
        print(f"[对话] 酢酱酱: {reply}")
        await asyncio.to_thread(
            database.save_chat_message, "elf2_voice", "user", user_text
        )
        await asyncio.to_thread(
            database.save_chat_message, "elf2_voice", "assistant", reply
        )
        await tts_queue.put(reply)
