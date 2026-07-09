"""用官方demo + 真实凭证直接测试讯飞TTS"""
import sys
sys.path.insert(0, r'C:\Users\Lenovo\Desktop\嵌赛\代码\tts_ws_python3_demo (1)\tts_ws_python3_demo\tts_ws_python3_demo')

import os
from dotenv import load_dotenv
load_dotenv()

from tts_ws_python3_demo import Ws_Param
import websocket
import ssl

APPID = os.getenv("XFYUN_APPID")
APIKey = os.getenv("XFYUN_APIKEY")
APISecret = os.getenv("XFYUN_APISECRET")

print(f"APPID: {APPID}")
print(f"APIKey: {APIKey[:10]}...")
print(f"APISecret: {APISecret[:10]}...")

wsParam = Ws_Param(APPID=APPID, APISecret=APISecret, APIKey=APIKey,
                   Text="这是一个语音合成测试")
wsUrl = wsParam.create_url()
print(f"\n生成的URL参数:")
print(f"  date: ...")
print(f"  host: ws-api.xfyun.cn")

# 简化的接收回调
import base64, json
def on_message(ws, message):
    msg = json.loads(message)
    code = msg.get("code", -1)
    if code != 0:
        print(f"\n❌ 错误: {msg.get('message')} (code={code})")
        print(f"   sid: {msg.get('sid')}")
    else:
        print(f"\n✅ 成功! sid={msg.get('sid')}, status={msg['data']['status']}")

def on_error(ws, error):
    print(f"\n⚠️ WebSocket error: {error}")

def on_close(ws, *_):
    print("连接关闭")

def on_open(ws):
    import _thread, json
    def run():
        d = {"common": wsParam.CommonArgs,
             "business": wsParam.BusinessArgs,
             "data": wsParam.Data}
        ws.send(json.dumps(d))
        print("已发送请求...")
    _thread.start_new_thread(run, ())

websocket.enableTrace(False)
ws = websocket.WebSocketApp(wsUrl, on_message=on_message,
                            on_error=on_error, on_close=on_close)
ws.on_open = on_open
print("\n正在连接...")
ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
