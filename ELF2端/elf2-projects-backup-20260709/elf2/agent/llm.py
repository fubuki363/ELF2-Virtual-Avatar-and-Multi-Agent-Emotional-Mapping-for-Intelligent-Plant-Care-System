"""
统一 LLM 客户端 —— 从 PC 端迁移至 ELF2。
提供同步 (invoke) 和异步 (ainvoke) 两种调用方式。
"""
import os
from dotenv import load_dotenv

load_dotenv()

# 同步客户端（用于 LangGraph 同步节点）
from openai import OpenAI as SyncOpenAI

_sync_client = SyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
)


class LLM:
    """ELF2 本地 LLM 客户端封装，兼容 LangChain 接口风格。

    支持两种模式:
    - sync: 标准同步调用 (OpenAI SDK)
    - async: asyncio 异步调用 (需配合 AsyncOpenAI)
    """

    def invoke(self, prompt: str, model: str = "deepseek-chat",
               temperature: float = 0.7, max_tokens: int = 300) -> "LLMResponse":
        """同步调用 DeepSeek API。"""
        resp = _sync_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=15,
        )
        return LLMResponse(resp.choices[0].message.content.strip())

    async def ainvoke(self, prompt: str, model: str = "deepseek-chat",
                      temperature: float = 0.7, max_tokens: int = 300) -> "LLMResponse":
        """异步调用 DeepSeek API。"""
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1",
        )
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=15,
        )
        return LLMResponse(resp.choices[0].message.content.strip())


class LLMResponse:
    """兼容 LangChain AIMessage 的最小包装。"""

    def __init__(self, content: str):
        self.content = content

    def __str__(self):
        return self.content


# 模块级实例（兼容旧代码 `from llm import llm`）
llm = LLM()
