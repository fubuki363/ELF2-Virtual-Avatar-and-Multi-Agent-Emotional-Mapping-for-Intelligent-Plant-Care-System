"""
长期记忆管理 —— 从 PC 端迁移至 ELF2。
复用 ELF2 本地 MySQL 数据库，存储对话记录与摘要。
"""
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3307")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "your_mysql_password_here"),
    "database": os.getenv("MYSQL_DB", "ai_agent_memory2"),
    "charset": "utf8mb4",
}


def get_conn():
    return pymysql.connect(**DB_CONFIG)


def save_message(session_id: str, role: str, content: str) -> None:
    """保存单条对话消息。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_memory (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, role, content),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Memory] 保存失败: {e}")


def load_summaries(session_id: str, limit: int = 5) -> str:
    """加载最近的记忆摘要。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT summary FROM memory_summary WHERE session_id=%s ORDER BY id DESC LIMIT %s",
            (session_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return "\n".join(r[0] for r in rows)
    except Exception as e:
        print(f"[Memory] 加载摘要失败: {e}")
        return ""


def count_messages(session_id: str) -> int:
    """统计会话消息数量。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM chat_memory WHERE session_id=%s",
            (session_id,),
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception:
        return 0


def generate_summary(session_id: str) -> str:
    """为最近对话生成记忆摘要（调用 LLM）。"""
    from .llm import llm

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM chat_memory "
            "WHERE session_id=%s ORDER BY id DESC LIMIT 10",
            (session_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return ""

        text = "\n".join(f"{r}:{c}" for r, c in rows)
        response = llm.invoke(
            f"请总结以下对话，保留用户偏好和关键信息：\n{text}",
            max_tokens=150,
        )
        summary = response.content

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO memory_summary (session_id, summary) VALUES (%s, %s)",
            (session_id, summary),
        )
        conn.commit()
        cur.close()
        conn.close()

        return summary
    except Exception as e:
        print(f"[Memory] 生成摘要失败: {e}")
        return ""
