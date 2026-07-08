import datetime
import requests
from bs4 import BeautifulSoup
import urllib.parse
from typing import TypedDict
from langgraph.graph import StateGraph

from llm import llm
from skills import compose_system_prompt
from memory import load_summaries
from rag import retrieve_docs


# --- 1. 状态定义 ---
class AgentState(TypedDict):
    user_input: str
    current_user: str
    memory: str
    knowledge: str
    web_info: str
    answer: str


# --- 2. 核心节点函数 ---

def load_memory_node(state):
    """读取长期记忆的节点"""
    user_name = state.get("current_user", "user_001")
    state["memory"] = load_summaries(user_name)
    return state


def rag_node(state):
    """检索本地植物资料库的节点"""
    state["knowledge"] = retrieve_docs(state["user_input"])
    return state


def domestic_search_bing(query: str):
    """使用微软必应(Bing)国内版进行搜索，无需代理，国内直连"""
    try:
        print(f"🌐 酢酱酱正在必应(国内)搜索: {query}...")
        encoded_query = urllib.parse.quote(query)
        url = f"https://cn.bing.com/search?q={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        results = []
        for item in soup.select(".b_algo")[:2]:  # 只取前两条最相关的
            title_tag = item.select_one("h2")
            desc_tag = item.select_one(".b_caption p")
            title = title_tag.get_text() if title_tag else ""
            desc = desc_tag.get_text() if desc_tag else ""
            if title or desc:
                results.append(f"【{title}】: {desc}")

        return "\n".join(results) if results else "没有找到相关网页内容。"

    except Exception as e:
        print(f"⚠️ 搜索过程出错: {e}")
        return "酢酱酱刚才上网查了一下，但是没搜到呢..."


def web_search_node(state):
    """执行国内联网搜索的节点"""
    search_result = domestic_search_bing(state["user_input"])
    state["web_info"] = search_result
    return state


def answer_node(state):
    """综合信息生成最终回答的节点"""
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

⚠️ 核心响应规则：
1. 酢浆草相关的问题 → 优先参考本地资料库，以植物亲身体验的口吻回答
2. 其他领域的问题 → 用植物拟人化视角趣味回应，绝不拒绝、绝不说不懂
3. 互联网信息 → 用角色口吻自然融入，不说「我在网上看到」，而是说「听大家说」或「有人告诉我」
4. 始终保持元气满满、软萌可爱的 VTuber 风格，像朋友聊天而不是机器播报

当前用户问题：
{state['user_input']}
"""
    state["answer"] = llm.invoke(prompt).content
    return state


# --- 3. 构建工作流图 (Graph) ---
def build_agent():
    graph = StateGraph(AgentState)

    # 添加所有节点
    graph.add_node("memory", load_memory_node)
    graph.add_node("rag", rag_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("answer", answer_node)

    # 设定起点
    graph.set_entry_point("memory")

    # 梳理工作流的边：记忆 -> 本地库 -> 联网搜索 -> 回答
    graph.add_edge("memory", "rag")
    graph.add_edge("rag", "web_search")
    graph.add_edge("web_search", "answer")

    return graph.compile()