import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB")
    )

def save_message(session_id, role, content):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_memory (session_id, role, content) VALUES (%s,%s,%s)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()

def load_summaries(session_id, limit=5):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT summary FROM memory_summary WHERE session_id=%s ORDER BY id DESC LIMIT %s",
        (session_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return "\n".join(r[0] for r in rows)

def count_messages(session_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM chat_memory WHERE session_id=%s",
        (session_id,)
    )
    count = cur.fetchone()[0]
    conn.close()
    return count

def generate_summary(llm, session_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM chat_memory "
        "WHERE session_id=%s ORDER BY id DESC LIMIT 10",
        (session_id,)
    )
    rows = cur.fetchall()

    text = "\n".join(f"{r}:{c}" for r, c in rows)

    summary = llm.invoke(
        f"请总结以下对话，保留用户偏好和关键信息：\n{text}"
    ).content

    cur.execute(
        "INSERT INTO memory_summary (session_id, summary) VALUES (%s,%s)",
        (session_id, summary)
    )
    conn.commit()
    conn.close()
