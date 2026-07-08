"""
ELF2 本地 LangGraph Agent —— 从 PC 端迁移至 ELF2。

在 ELF2 上运行完整的 AI 大脑:
  记忆加载 → RAG检索 → 联网搜索 → 回答生成

PC 端降级为纯交互终端 (通过 MQTT 转发消息)。
"""
import datetime
import urllib.parse

import requests
from bs4 import BeautifulSoup

from .llm import llm
from .memory import load_summaries, save_message, count_messages, generate_summary
from .rag import retrieve_docs
from .skills import compose_system_prompt

# ── LangGraph (纯 Python, 可在 ELF2 上运行) ──
from langgraph.graph import StateGraph
from typing import TypedDict

MAX_HISTORY = 5  # 简易对话历史轮数


class AgentState(TypedDict):
    user_input: str
    current_user: str
    memory: str
    knowledge: str
    web_info: str
    sensor_context: str   # ← ELF2 特有: 传感器数据上下文
    answer: str


# ═══════════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════════

def load_memory_node(state: AgentState) -> AgentState:
    """读取长期记忆。"""
    user_name = state.get("current_user", "elf2_local")
    state["memory"] = load_summaries(user_name)
    return state


def rag_node(state: AgentState) -> AgentState:
    """检索本地植物资料库。"""
    state["knowledge"] = retrieve_docs(state["user_input"])
    return state


def domestic_search_bing(query: str) -> str:
    """必应国内版搜索（ELF2 Linux 直连，无需代理）。"""
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://cn.bing.com/search?q={encoded_query}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for item in soup.select(".b_algo")[:2]:
            title_tag = item.select_one("h2")
            desc_tag = item.select_one(".b_caption p")
            title = title_tag.get_text() if title_tag else ""
            desc = desc_tag.get_text() if desc_tag else ""
            if title or desc:
                results.append(f"【{title}】: {desc}")
        return "\n".join(results) if results else "没有找到相关网页内容。"
    except Exception:
        return ""


def web_search_node(state: AgentState) -> AgentState:
    """执行国内联网搜索。"""
    state["web_info"] = domestic_search_bing(state["user_input"])
    return state


def answer_node(state: AgentState) -> AgentState:
    """综合信息生成最终回答。"""
    user_name = state.get("current_user", "这位朋友")
    current_time = datetime.datetime.now().strftime("%Y年%m月%d日 %A %H:%M")

    prompt = f"""
{compose_system_prompt()}

【系统实时时间（极高优先级）】
现在的现实时间是：{current_time}。如果用户问现在几点、今天几号、星期几，请毫不犹豫地直接依据此时间回答！

你当前正在和用户【{user_name}】对话。
以下是你关于【{user_name}】的专属长期记忆（如果没有则为空）：
{state['memory']}

【本地植物资料库】（植物科普的最高优先级参考）
{state['knowledge']}

【刚刚通过手机查到的互联网信息】（用于回答天气、新闻、游戏、最新梗等）
{state['web_info']}

【温室传感器实时数据】（仅当用户问到环境/植物状态时参考）
{state.get('sensor_context', '')}

⚠️ 核心响应规则：
1. 酢浆草相关的问题 → 优先参考本地资料库，以植物亲身体验的口吻回答
2. 其他领域的问题 → 用植物拟人化视角趣味回应，绝不拒绝、绝不说不懂
3. 互联网信息 → 用角色口吻自然融入，不说「我在网上看到」，而是说「听大家说」或「有人告诉我」
4. 始终保持元气满满、软萌可爱的 VTuber 风格，像朋友聊天而不是机器播报
5. 传感器数据 → 用植物的感受来描述，如「我现在感觉土壤有点干干的～」

当前用户问题：
{state['user_input']}
"""
    response = llm.invoke(prompt, max_tokens=300)
    state["answer"] = response.content
    return state


# ═══════════════════════════════════════════════════════════
# 构建工作流图
# ═══════════════════════════════════════════════════════════

def build_agent():
    """构建 LangGraph 工作流 (与 PC 端完全相同的图结构)。"""
    graph = StateGraph(AgentState)

    graph.add_node("memory", load_memory_node)
    graph.add_node("rag", rag_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("answer", answer_node)

    graph.set_entry_point("memory")
    graph.add_edge("memory", "rag")
    graph.add_edge("rag", "web_search")
    graph.add_edge("web_search", "answer")

    return graph.compile()


# ═══════════════════════════════════════════════════════════
# 高层 API
# ═══════════════════════════════════════════════════════════

class Elf2Agent:
    """ELF2 本地 AI Agent —— 替代 PC 端 global_agent。

    集成 LangGraph 完整工作流 + 传感器上下文注入。
    """

    def __init__(self):
        self._workflow = build_agent()

    def chat(self, user_text: str, user_id: str = "elf2_local",
             sensor_context: str = "") -> str:
        """完整 Agent 对话 (记忆 → RAG → 搜索 → 回答)。

        Args:
            user_text: 用户输入文本
            user_id: 用户标识 (用于记忆区分)
            sensor_context: 可选的传感器数据上下文
        """
        result = self._workflow.invoke({
            "user_input": user_text,
            "current_user": user_id,
            "memory": "",
            "knowledge": "",
            "web_info": "",
            "sensor_context": sensor_context,
            "answer": "",
        })
        answer = result.get("answer", "")

        # 保存对话到 MySQL（异步化，失败不影响主流程）
        try:
            save_message(user_id, "user", user_text)
            save_message(user_id, "assistant", answer)
        except Exception:
            pass

        # 每 10 条消息生成一次摘要
        try:
            if count_messages(user_id) % 10 == 0:
                generate_summary(user_id)
        except Exception:
            pass

        return answer

    def quick_chat(self, user_text: str) -> str:
        """轻量聊天 (跳过 RAG + 搜索，用于简单对话)。"""
        current_time = datetime.datetime.now().strftime("%Y年%m月%d日 %A %H:%M")
        prompt = f"""
{compose_system_prompt()}

【系统实时时间】{current_time}

用户说："{user_text}"

请用酢酱酱的口吻简短回复（不超过50字），不要使用星号或markdown。
"""
        response = llm.invoke(prompt, max_tokens=100)
        return response.content


# 全局单例
elf2_agent = Elf2Agent()
