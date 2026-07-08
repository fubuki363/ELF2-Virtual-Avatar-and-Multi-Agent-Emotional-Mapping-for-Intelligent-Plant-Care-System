import os
import json
from dotenv import load_dotenv
import pymysql

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", 3307)),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "your_mysql_password_here"),
    "database": os.getenv("MYSQL_DB", "ai_agent_memory2"),
    "charset": "utf8mb4",
}


def get_conn():
    return pymysql.connect(**DB_CONFIG)


def init_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sensor_log (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            temperature FLOAT,
            humidity FLOAT,
            light FLOAT,
            eco2 INT,
            tvoc INT,
            gas FLOAT,
            soil INT,
            sensor_ts BIGINT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS command_log (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            voice_text VARCHAR(500),
            keyword VARCHAR(100),
            udp_commands JSON,
            source VARCHAR(50) DEFAULT 'voice',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    conn.commit()
    cur.close()
    conn.close()
    print("[数据库] 表已就绪: sensor_log, command_log, chat_memory (复用PC端)")


def save_sensor(sensor_data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sensor_log (temperature, humidity, light, eco2, tvoc, gas, soil, sensor_ts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (sensor_data.get("t"), sensor_data.get("h"), sensor_data.get("light"), sensor_data.get("eco2"), sensor_data.get("tvoc"), sensor_data.get("gas"), sensor_data.get("soil"), sensor_data.get("ts")),
    )
    conn.commit()
    cur.close()
    conn.close()


def save_command(voice_text: str, keyword: str, udp_commands: list[dict], source: str = "voice"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO command_log (voice_text, keyword, udp_commands, source) VALUES (%s, %s, %s, %s)",
        (voice_text, keyword, json.dumps(udp_commands, ensure_ascii=False), source),
    )
    conn.commit()
    cur.close()
    conn.close()


def save_chat_message(session_id: str, role: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_memory (session_id, role, content) VALUES (%s, %s, %s)",
        (session_id, role, content),
    )
    conn.commit()
    cur.close()
    conn.close()
