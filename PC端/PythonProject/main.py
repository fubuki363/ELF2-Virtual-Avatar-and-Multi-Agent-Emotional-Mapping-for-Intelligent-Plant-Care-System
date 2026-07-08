import asyncio
import threading
import time
import os
import random
import ctypes
import json
import queue
import mysql.connector
import paho.mqtt.client as mqtt
import ssl
import importlib
import websockets
import music_player
import traceback
from dotenv import load_dotenv
from bilibili_api import live, Credential
from wxauto import WeChat

# 导入项目核心模块
from agent import build_agent
from memory import save_message, count_messages, generate_summary
from llm import llm
from tts import ai_reply_to_voice
from emotion_analyzer import analyze_user_message, analyze_reply_emotion

# VTS 表情引擎（延迟初始化，避免启动时 VTS 未运行导致崩溃）
vts_engine = None

# ==========================================
# 1. 基础配置与统一加载
# ==========================================
load_dotenv()

ROOM_ID = 1896547944  # 直播间号
WS_URL = "ws://127.0.0.1:3001"  # NapCatQQ WebSocket 地址
BOT_QQ = "3499867199"  # 你的机器人 QQ 号


DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", 3307)),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "123456"),
    "database": os.getenv("MYSQL_DB", "ai_agent_memory2")
}

credential = Credential(
    sessdata=os.getenv("BILI_SESSDATA"),
    bili_jct=os.getenv("BILI_JCT"),
    buvid3=os.getenv("BILI_BUVID3"),
    dedeuserid=os.getenv("BILI_DEDEUSERID")
)

IDLE_THRESHOLD = 60
IDLE_QUESTIONS = [
    "讲讲怎么护理酢浆草？",
    "为什么我的酢浆草晚上会闭合叶子？",
    "酢浆草多久浇一次水比较好？",
    "介绍一下什么是‘爱之芽’品种吧。",
    "酢浆草夏天休眠了怎么办？",
    "酢浆草有哪些特点？",
    "酢浆草的生物学演化路径是怎样的？"
]

try:
    with open("commands.json", "r", encoding="utf-8") as f:
        COMMANDS_CONFIG = json.load(f)
except FileNotFoundError:
    print("❌ 找不到 commands.json，请检查配置文件！")
    COMMANDS_CONFIG = {}

print("⚙️ 正在初始化 LangGraph Agent 工作流...")
global_agent = build_agent()

# 🎭 传感器数据 → VTS 表情联动
def _check_sensor_expression(payload: str):
    """
    从 MQTT 传感器回传数据中提取数值，触发环境表情。

    支持的格式：
    - JSON: {"soil_moisture": 15.5} 或 {"temperature": 38}
    - 纯文本: "soil_moisture:15.5" 或 "temperature=38"
    """
    try:
        # 尝试 JSON 格式
        data = json.loads(payload)
        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                if any(kw in key_lower for kw in ("soil", "moisture", "湿度", "temperature", "温度")):
                    try:
                        vts_engine.react_to_sensor(key, float(value))
                    except Exception:
                        pass
        return
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试纯文本格式
    payload_lower = payload.lower()
    if "soil" in payload_lower or "moisture" in payload_lower or "湿度" in payload_lower:
        try:
            import re
            nums = re.findall(r"[\d.]+", payload)
            if nums:
                vts_engine.react_to_sensor("soil_moisture", float(nums[0]))
        except Exception:
            pass
    elif "temperature" in payload_lower or "温度" in payload_lower:
        try:
            import re
            nums = re.findall(r"[\d.]+", payload)
            if nums:
                vts_engine.react_to_sensor("temperature", float(nums[0]))
        except Exception:
            pass


# ==========================================
# 2. MQTT 消息路由隔离系统 (核心修改区)
# ==========================================
MQTT_BROKER = "p8c59112.ala.cn-hangzhou.emqxsl.cn"
MQTT_PORT = 8883
MQTT_USERNAME = "rpi_user"
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "your_mqtt_password_here")
MQTT_CA_CRT = "emqxsl-ca.crt"

TOPIC_PUB = "rpi5/cloud/command"
TOPIC_SUB_DATA = "rpi5/cloud/data"
TOPIC_SUB_FILE = "rpi5/cloud/file"

incoming_file_name = None

# ✅ 双队列与路由追踪系统
live_mqtt_queue = queue.Queue()  # B站专属队列
qq_mqtt_queue = queue.Queue()  # QQ专属队列
hardware_request_lock = threading.Lock()
wechat_mqtt_queue = queue.Queue()

# 记录当前下发指令的平台源，确保数据精准送回
current_hardware_caller = {"type": "live", "target": None}


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ 主机已成功连接 EMQX Cloud!")
        client.subscribe(TOPIC_SUB_DATA)
        client.subscribe(TOPIC_SUB_FILE)
    else:
        print(f"❌ MQTT 连接失败，状态码: {reason_code}")


def on_message(client, userdata, msg):
    global incoming_file_name, current_hardware_caller
    if msg.topic == TOPIC_SUB_DATA:
        payload = msg.payload.decode('utf-8')
        print(f"\n📥 [收到树莓派回传文本]: {payload}")
        if payload.startswith("[FILE_META]"):
            try:
                file_info = json.loads(payload.replace("[FILE_META]", "").strip())
                incoming_file_name = file_info.get("filename", "unknown_file.bin")
            except Exception as e:
                print(f"❌ 解析文件元数据失败: {e}")
        else:
            # 🎭 VTS 环境触发：解析传感器数据，触发对应表情
            if vts_engine:
                try:
                    _check_sensor_expression(payload)
                except Exception:
                    pass

            # ✅ 路由分发逻辑：将回传数据派发给对应的平台队列
            with hardware_request_lock:
                caller = current_hardware_caller.copy()
                # 收到数据后，状态重置回直播间默认态，防串台
                current_hardware_caller = {"type": "live", "target": None}

            if caller["type"] == "live":
                live_mqtt_queue.put(payload)
            else:
                qq_mqtt_queue.put((payload, caller))

    elif msg.topic == TOPIC_SUB_FILE:
        file_name = incoming_file_name if incoming_file_name else f"file_{int(time.time())}.bin"
        try:
            with open(file_name, 'wb') as f:
                f.write(msg.payload)
        except Exception as e:
            print(f"❌ 文件保存失败: {e}")


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.tls_set(ca_certs=MQTT_CA_CRT, tls_version=ssl.PROTOCOL_TLSv1_2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


# ==========================================
# 3. 意图识别
# ==========================================
def detect_hardware_intent(user_content):
    available_commands = list(COMMANDS_CONFIG.keys())
    intent_prompt = f"""
    你是一个意图识别专家。现在有以下硬件指令列表：
    {available_commands}
    用户的输入是："{user_content}"
    请判断用户的输入是否在询问上述指令相关的状态。
    1. 如果匹配，请【只返回】指令字符串（例如：/sensor.temperature.get）。
    2. 如果不匹配，请【只返回】字符串：NONE。
    注意：不要返回任何多余的解释。
    """
    try:
        response = llm.invoke(intent_prompt)
        intent = response.content.strip()
        if intent in available_commands:
            return intent
        return None
    except Exception as e:
        print(f"⚠️ 意图识别出错: {e}")
        return None


# ==========================================
# 4. QQ 机器人专属后台模块
# ==========================================
async def send_qq_group_msg(websocket, group_id, text):
    payload = {"action": "send_group_msg", "params": {"group_id": group_id, "message": text}}
    await websocket.send(json.dumps(payload))


async def send_qq_private_msg(websocket, user_id, text):
    payload = {"action": "send_private_msg", "params": {"user_id": user_id, "message": text}}
    await websocket.send(json.dumps(payload))


# ✅ 为QQ独立编写的MQTT监控循环
async def process_qq_mqtt_queue(websocket):
    while True:
        try:
            payload, caller = qq_mqtt_queue.get_nowait()
            reply_text = f"📡 收到树莓派数据啦：\n{payload}"
            if caller["type"] == "qq_group":
                await send_qq_group_msg(websocket, caller["target"], reply_text)
            elif caller["type"] == "qq_private":
                await send_qq_private_msg(websocket, caller["target"], reply_text)
        except queue.Empty:
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"❌ [QQ端] 队列推送错误: {e}")
            await asyncio.sleep(0.5)


# ✅ 增加了 msg_type 和 group_id 参数以记录来源
def process_qq_message_sync(user_text, user_id, msg_type, group_id=None):
    global current_hardware_caller
    smart_command = user_text if user_text.startswith("/") else detect_hardware_intent(user_text)

    if smart_command and smart_command.startswith("/"):
        matched_cmd_key = None
        cmd_args = ""
        for cmd_key in COMMANDS_CONFIG.keys():
            if smart_command.startswith(cmd_key):
                matched_cmd_key = cmd_key
                cmd_args = smart_command[len(cmd_key):].strip()
                break

        if matched_cmd_key:
            cmd_info = COMMANDS_CONFIG[matched_cmd_key]
            target_module = cmd_info.get("module")
            target_class = cmd_info.get("class")

            if target_module == "cmd_live":
                return f"🎵 滴滴！【{matched_cmd_key}】是直播间专属的整活指令哦！快来我的 B站直播间发弹幕试试吧！"
            elif target_module == "cmd_qq":
                try:
                    module = importlib.import_module(target_module)
                    command_class = getattr(module, target_class)
                    command_instance = command_class()
                    return command_instance.execute(cmd_args, user_id)
                except Exception as e:
                    return f"❌ QQ指令执行异常: {e}"
            else:
                # ✅ 给本次 MQTT 发送贴上“QQ请求”标签
                with hardware_request_lock:
                    current_hardware_caller = {
                        "type": "qq_group" if msg_type == "group" else "qq_private",
                        "target": group_id if msg_type == "group" else user_id
                    }
                    mqtt_client.publish(TOPIC_PUB, smart_command)
                return "📡 指令已下发给树莓派！请稍候，数据回来后会直接发在这里~"

    result = global_agent.invoke({
        "user_input": user_text,
        "current_user": f"QQ_{user_id}"
    })
    # 🎭 VTS 表情：根据用户消息和 AI 回复调整表情
    if vts_engine:
        try:
            vts_engine.react_to_message(user_text)
            vts_engine.react_to_reply(result["answer"])
        except Exception:
            pass
    return result["answer"]


async def qq_bot_loop():
    while True:
        try:
            async for websocket in websockets.connect(WS_URL):
                print("✅ [QQ端] 成功连接 NapCat，开始监听群聊/私聊！")

                # ✅ 建立连接后立刻启动 QQ专属的MQTT回调监听器
                mqtt_task = asyncio.create_task(process_qq_mqtt_queue(websocket))

                try:
                    async for message in websocket:
                        data = json.loads(message)
                        if data.get("post_type") != "message":
                            continue

                        msg_type = data.get("message_type")
                        raw_msg = data.get("raw_message", "")
                        sender_id = data.get("sender", {}).get("user_id")

                        if msg_type == "group":
                            group_id = data.get("group_id")
                            cq_at = f"[CQ:at,qq={BOT_QQ}]"
                            if cq_at in raw_msg:
                                user_text = raw_msg.replace(cq_at, "").strip()
                                try:
                                    ai_reply = await asyncio.to_thread(
                                        process_qq_message_sync, user_text, sender_id, "group", group_id
                                    )
                                    reply_msg = f"[CQ:at,qq={sender_id}] {ai_reply}"
                                    await send_qq_group_msg(websocket, group_id, reply_msg)
                                except Exception as e:
                                    print("❌ [QQ端] 群聊处理崩溃:")
                                    traceback.print_exc()
                                    await send_qq_group_msg(websocket, group_id,
                                                            f"[CQ:at,qq={sender_id}] 哎呀，我的大脑短路了！")

                        elif msg_type == "private":
                            user_text = raw_msg.strip()
                            try:
                                ai_reply = await asyncio.to_thread(
                                    process_qq_message_sync, user_text, sender_id, "private"
                                )
                                await send_qq_private_msg(websocket, sender_id, ai_reply)
                            except Exception as e:
                                print("❌ [QQ端] 私聊处理崩溃:")
                                traceback.print_exc()
                                await send_qq_private_msg(websocket, sender_id, "哎呀，我的大脑短路了！")

                except websockets.ConnectionClosed:
                    print("⚠️ [QQ端] WebSocket 断开，准备重连...")
                    mqtt_task.cancel()  # 断开时销毁任务防止内存泄漏
                    break
        except Exception as e:
            print(f"❌ [QQ端] 严重连接错误，3秒后重连: {e}")
            await asyncio.sleep(3)


def run_qq_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(qq_bot_loop())


# ==========================================
# 5 & 6. B 站弹幕数据库模块与监听线程 (未变动)
# ==========================================
def save_to_db(user_name, content):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO danmaku (user_name, session_id, content, is_answered) VALUES (%s, %s, %s, %s)",
                       (user_name, "default_live_session", content, 0))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ 数据库写入失败: {e}")


def get_next_question():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, user_name, content FROM danmaku WHERE is_answered = 0 ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE danmaku SET is_answered = 1 WHERE id = %s", (row['id'],))
            conn.commit()
        cursor.close()
        conn.close()
        return row
    except Exception:
        return None


async def async_bilibili_listener():
    live_room = live.LiveDanmaku(ROOM_ID, credential=credential)

    @live_room.on('DANMU_MSG')
    async def on_danmaku(event):
        try:
            u_name = event['data']['info'][2][1]
            msg = event['data']['info'][1]
            save_to_db(u_name, msg)
        except Exception as e:
            pass

    print(f"📡 [B站端] 监听就绪！正在连接房间: {ROOM_ID}")
    await live_room.connect()


def run_listener_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_bilibili_listener())


# ==========================================
# 7. 主线程：直播间大脑与发声系统
# ==========================================
def run_live_agent():
    global current_hardware_caller
    print("\n" + "=" * 40)
    print("🌱 酢酱酱全域大脑启动！已开启【多核处理】模式。")
    print("正在后台监听 [B站弹幕] / [QQ群聊] / [MQTT指令] ...")
    print("=" * 40 + "\n")

    last_speak_time = time.time()

    while True:
        # ---------- 模块 A：处理树莓派回传数据 ----------
        try:
            # ✅ 只从直播间专属队列拿数据
            hardware_data = live_mqtt_queue.get_nowait()
            hardware_prompt = f"树莓派传回了硬件数据：{hardware_data}。请简短分析并用主播口吻播报。"
            result = global_agent.invoke({"user_input": hardware_prompt, "current_user": "System_Live"})
            ai_reply_to_voice(result["answer"])
            last_speak_time = time.time()

            # 🎭 VTS 环境表情：传感器数据触发
            if vts_engine:
                try:
                    _check_sensor_expression(hardware_data)
                except Exception:
                    pass
            continue
        except queue.Empty:
            pass

        # ---------- 模块 B：处理 B站弹幕 ----------
        danmaku = get_next_question()
        if danmaku:
            name = danmaku.get('user_name', "热心观众")
            content = danmaku.get('content', "").strip()

            smart_command = content if content.startswith("/") else detect_hardware_intent(content)

            if smart_command and smart_command.startswith("/"):
                matched_cmd_key = None
                cmd_args = ""
                for cmd_key in COMMANDS_CONFIG.keys():
                    if smart_command.startswith(cmd_key):
                        matched_cmd_key = cmd_key
                        cmd_args = smart_command[len(cmd_key):].strip()
                        break

                if matched_cmd_key:
                    cmd_info = COMMANDS_CONFIG[matched_cmd_key]
                    target_module = cmd_info.get("module")
                    target_class = cmd_info.get("class")

                    if target_module == "cmd_live":
                        try:
                            module = importlib.import_module(target_module)
                            command_class = getattr(module, target_class)
                            command_instance = command_class()
                            command_instance.execute(cmd_args, name, ai_reply_to_voice)
                        except Exception as e:
                            print(f"❌ 本地指令执行异常: {e}")
                    elif target_module == "cmd_qq":
                        ai_reply_to_voice(f"{name}，这是QQ群专属的指令哦，我在直播间没法用呢！")
                    else:
                        # ✅ 给本次 MQTT 发送贴上“B站请求”标签
                        with hardware_request_lock:
                            current_hardware_caller = {"type": "live", "target": None}
                            mqtt_client.publish(TOPIC_PUB, smart_command)

                        if "soil_moisture" in matched_cmd_key:
                            ai_reply_to_voice(f"{name}，正在帮你查看土壤湿度，请稍候！")
                        elif "illumination" in matched_cmd_key:
                            ai_reply_to_voice(f"{name}，正在检查当前光照强度，马上回来~")
                        else:
                            ai_reply_to_voice(f"{name}，指令已下发给树莓派，正在执行！")

                    last_speak_time = time.time()
                    continue

            result = global_agent.invoke({
                "user_input": content,
                "current_user": f"Bili_{name}"
            })
            ai_reply_to_voice(result["answer"])
            last_speak_time = time.time()

            # 🎭 VTS 表情：根据 AI 回复内容调整表情
            if vts_engine:
                try:
                    vts_engine.react_to_reply(result["answer"])
                except Exception as e:
                    pass  # 表情切换失败不影响主流程

        # ---------- 模块 C：闲置科普逻辑 ----------
        if not danmaku and live_mqtt_queue.empty():
            current_time = time.time()
            if current_time - last_speak_time > IDLE_THRESHOLD:
                if music_player.check_is_singing():
                    last_speak_time = time.time()
                else:
                    idle_question = random.choice(IDLE_QUESTIONS)
                    result = global_agent.invoke({
                        "user_input": f"直播间很安静，请主动发起科普：{idle_question}",
                        "current_user": "System_Idle"
                    })
                    ai_reply_to_voice(result["answer"])
                    last_speak_time = time.time()

                    # 🎭 VTS 表情：科普时切换到 curious
                    if vts_engine:
                        try:
                            vts_engine.set_mood("curious")
                        except Exception:
                            pass

        time.sleep(0.5)


wechat_client = None


def send_wechat_msg(target_name, text):
    """
    通过 wxauto 发送微信消息。
    注意：target_name 必须是微信聊天列表里显示的“群名”或“好友昵称/备注名”。
    """
    global wechat_client
    if wechat_client:
        try:
            wechat_client.SendMsg(text, target_name)
        except Exception as e:
            print(f"❌ [微信端] 发送消息给 {target_name} 失败: {e}")


def process_wechat_mqtt_queue():
    """
    监听从树莓派传回来的 MQTT 消息，并转发给对应的微信聊天窗口。
    """
    while True:
        try:
            # 阻塞等待硬件回传数据，超时时间1秒
            payload, caller = wechat_mqtt_queue.get(timeout=1)
            reply_text = f"📡 收到树莓派传回的数据啦：\n{payload}"

            # caller["target"] 此时保存的是聊天窗口的名字
            send_wechat_msg(caller["target"], reply_text)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ [微信端] 硬件队列推送错误: {e}")


def process_wechat_message_sync(user_text, sender_name, chat_window_name):
    """
    同步处理单条微信消息：解析指令、分发硬件任务、调用大模型
    """
    global current_hardware_caller
    global mqtt_client

    # target_name 是我们要回复的窗口名字
    target_name = chat_window_name

    # 1. 拦截智能硬件指令 (假设 detect_hardware_intent 是你定义的意图识别函数)
    smart_command = user_text if user_text.startswith("/") else detect_hardware_intent(user_text)

    if smart_command and smart_command.startswith("/"):
        matched_cmd_key = None
        for cmd_key in COMMANDS_CONFIG.keys():
            if smart_command.startswith(cmd_key):
                matched_cmd_key = cmd_key
                break

        if matched_cmd_key:
            cmd_info = COMMANDS_CONFIG[matched_cmd_key]
            target_module = cmd_info.get("module")

            if target_module == "cmd_live":
                return "🎵 滴滴！这是直播间专属的整活指令哦，微信暂不支持！"
            elif target_module == "cmd_qq":
                return "❌ 这是QQ专属指令，微信无法使用。"
            else:
                # ✅ 给本次 MQTT 发送贴上“微信请求”的溯源标签
                with hardware_request_lock:
                    current_hardware_caller = {
                        "type": "wechat_ui",
                        "target": target_name  # 保存当前聊天窗口名称，方便回调寻找目标
                    }
                    mqtt_client.publish(TOPIC_PUB, smart_command)
                return "📡 指令已下发给树莓派！请稍候..."

    # 2. 如果不是硬件指令，则调用全局大模型 Agent
    try:
        result = global_agent.invoke({
            "user_input": user_text,
            "current_user": f"WeChat_{sender_name}"  # 给大模型做记忆区分
        })
        return result["answer"]
    except Exception as e:
        print(f"❌ [微信端] 大模型调用崩溃: {e}")
        return "🧠 哎呀，我的大脑暂时短路了，请稍后再试~"


def run_wechat_bot_thread():
    """
    微信监听的主循环线程
    """
    global wechat_client
    ctypes.windll.ole32.CoInitialize(None)
    try:
        print("⏳ [微信端] 正在尝试接管屏幕上的微信窗口...")
        wechat_client = WeChat()
        print("✅ [微信端] 成功接管 PC 微信！")

        # 启动 MQTT 硬件数据回传的监听子线程
        threading.Thread(target=process_wechat_mqtt_queue, daemon=True).start()

        # 持续轮询获取新消息
        while True:
            # GetAllNewMessage 返回字典结构：{ '聊天窗口名': [['发信人', '消息内容', '消息ID'], ...] }
            new_msgs = wechat_client.GetAllNewMessage()

            for chat_window_name, msg_list in new_msgs.items():
                for msg in msg_list:
                    sender_name = msg[0]
                    content = msg[1]

                    # 过滤掉不需要回复的系统消息、撤回提示以及自己发出的消息
                    if sender_name not in ['Self', 'SYS', '系统消息', '撤回了一条消息']:
                        try:
                            # 处理消息并获取回复
                            ai_reply = process_wechat_message_sync(content, sender_name, chat_window_name)
                            # 将回复发送回对应的聊天窗口
                            if ai_reply:
                                send_wechat_msg(chat_window_name, ai_reply)
                        except Exception as e:
                            print(f"❌ [微信端] 处理单条消息崩溃: {e}")
                            traceback.print_exc()

            # 💡 极其重要：必须增加短暂休眠，防止死循环把 CPU 跑满并导致微信卡死
            time.sleep(1)

    except Exception as e:
        print(f"❌ [微信端] 启动失败，请检查：1. 微信是否已打开？ 2. 微信窗口是否被最小化到了托盘？")
        print(f"具体报错: {e}")

# ==========================================
# 8. 启动总入口
# ==========================================
if __name__ == "__main__":
    try:
        print("⏳ 正在连接 MQTT 云端...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()

        # --- VTS 表情引擎初始化 ---
        try:
            from expression_engine import ExpressionEngineSync
            vts_engine = ExpressionEngineSync()
            vts_engine.start()
            print("🎭 VTS 表情引擎已就绪")
        except Exception as e:
            print(f"⚠️ VTS 表情引擎启动失败（VTube Studio 可能未运行）: {e}")
            vts_engine = None

        threading.Thread(target=run_listener_thread, daemon=True).start()
        threading.Thread(target=run_qq_bot_thread, daemon=True).start()
        threading.Thread(target=run_wechat_bot_thread, daemon=True).start()
        time.sleep(2)
        run_live_agent()

    except KeyboardInterrupt:
        print("\n👋 收到停止指令，准备断开连接...")
        if vts_engine:
            vts_engine.stop()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("酢酱酱下班啦！")