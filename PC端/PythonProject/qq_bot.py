import asyncio
import websockets
import json

# 引入你构建好的 LangGraph Agent 工作流
from agent import build_agent

WS_URL = "ws://127.0.0.1:3001"
BOT_QQ = "3499867199"

# 在全局初始化并编译好 LangGraph 工作流
print("⚙️ 正在初始化 LangGraph Agent 工作流...")
agent_app = build_agent()


async def send_group_msg(websocket, group_id, text):
    """构造并发送群消息"""
    payload = {
        "action": "send_group_msg",
        "params": {
            "group_id": group_id,
            "message": text
        }
    }
    await websocket.send(json.dumps(payload))


async def send_private_msg(websocket, user_id, text):
    """构造并发送私聊消息"""
    payload = {
        "action": "send_private_msg",
        "params": {
            "user_id": user_id,
            "message": text
        }
    }
    await websocket.send(json.dumps(payload))


def run_agent_sync(user_text, user_id):
    """
    【核心桥接函数】
    由于 agent.py 里的 requests.get 等操作是同步阻塞的，
    我们需要将 invoke 封装成普通函数，以便抛到后台线程运行。
    """
    initial_state = {
        "user_input": user_text,
        "current_user": str(user_id),  # 直接将 QQ 号作为当前用户，方便记忆系统隔离
        "memory": "",
        "knowledge": "",
        "web_info": "",
        "answer": ""
    }
    result = agent_app.invoke(initial_state)
    return result.get("answer", "哎呀，系统好像开小差了~")


async def bot_loop():
    while True:
        try:
            print(f"🔗 正在连接到 NapCatQQ: {WS_URL} ...")
            async for websocket in websockets.connect(WS_URL):
                print("✅ QQ Bot 已成功连接！酢酱酱开始营业！")

                try:
                    async for message in websocket:
                        data = json.loads(message)

                        if data.get("post_type") != "message":
                            continue

                        msg_type = data.get("message_type")
                        raw_msg = data.get("raw_message", "")
                        sender_id = data.get("sender", {}).get("user_id")

                        # ==========================================
                        # 1. 处理群聊消息
                        # ==========================================
                        if msg_type == "group":
                            group_id = data.get("group_id")
                            cq_at = f"[CQ:at,qq={BOT_QQ}]"

                            if cq_at in raw_msg:
                                user_text = raw_msg.replace(cq_at, "").strip()
                                print(f"👀 [群 {group_id}] {sender_id} 提问: {user_text}")

                                try:
                                    # 将同步的 LangGraph 丢到后台线程执行，防止卡死 WebSocket
                                    ai_reply = await asyncio.to_thread(run_agent_sync, user_text, sender_id)
                                    print(f"🧠 [Agent回复]: {ai_reply}")

                                    reply_msg = f"[CQ:at,qq={sender_id}] {ai_reply}"
                                    await send_group_msg(websocket, group_id, reply_msg)

                                except Exception as e:
                                    print(f"❌ LangGraph 执行出错: {e}")
                                    await send_group_msg(websocket, group_id, "大脑短路啦，请稍后再试哦~")

                        # ==========================================
                        # 2. 处理私聊消息
                        # ==========================================
                        elif msg_type == "private":
                            user_text = raw_msg.strip()
                            print(f"👀 [私聊] {sender_id} 提问: {user_text}")

                            try:
                                ai_reply = await asyncio.to_thread(run_agent_sync, user_text, sender_id)
                                print(f"🧠 [Agent回复]: {ai_reply}")
                                await send_private_msg(websocket, sender_id, ai_reply)

                            except Exception as e:
                                print(f"❌ LangGraph 执行出错: {e}")
                                await send_private_msg(websocket, sender_id, "大脑短路啦，请稍后再试哦~")

                except websockets.ConnectionClosed:
                    print("⚠️ WebSocket 连接断开，准备重连...")
                    break

        except Exception as e:
            print(f"❌ 连接失败，3秒后重试: {e}")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(bot_loop())