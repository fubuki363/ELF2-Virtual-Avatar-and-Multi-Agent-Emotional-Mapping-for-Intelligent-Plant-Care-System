import os
import json
import base64
import hmac
import hashlib
import asyncio
import websockets
from datetime import datetime
from time import mktime
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time
from dotenv import load_dotenv
import sounddevice as sd
import numpy as np

load_dotenv()

# ================= 配置 =================
APPID = os.getenv("XFYUN_APPID")
APIKey = os.getenv("XFYUN_APIKEY")
APISecret = os.getenv("XFYUN_APISECRET")
XFYUN_URL = "wss://tts-api.xfyun.cn/v2/tts"
SIGN_HOST = "ws-api.xfyun.cn"   # 签名专用 host（与连接地址不同）
VOICE_NAME = "x4_yezi"  # 讯飞发音人（免费可用）


# ========================================

def build_auth_url(request_url, api_key, api_secret):
    """动态生成带有签名的鉴权 URL（签名 host 与连接 host 不同）"""
    parsed_url = urlparse(request_url)
    path = parsed_url.path

    # 1. 生成 RFC1123 格式时间戳
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))

    # 2. 拼接签名原始字符串（必须用 SIGN_HOST，非连接地址）
    signature_origin = f"host: {SIGN_HOST}\ndate: {date}\nGET {path} HTTP/1.1"

    # 3. HMAC-SHA256 加密
    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()

    # 4. Base64 编码
    signature_sha = base64.b64encode(signature_sha).decode('utf-8')

    # 5. 构建 Authorization 并 base64 编码
    authorization_origin = f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

    # 6. 拼接到 URL 参数中
    params = {
        "authorization": authorization,
        "date": date,
        "host": SIGN_HOST
    }
    return f"{request_url}?{urlencode(params)}"


async def get_xfyun_audio_bytes(text: str) -> bytes:
    """连接讯飞 WebSocket 接口并获取音频字节流（MP3格式）"""
    auth_url = build_auth_url(XFYUN_URL, APIKey, APISecret)

    # 构建请求 JSON 体
    request_data = {
        "common": {"app_id": APPID},
        "business": {
            "aue": "raw",  # raw PCM (与官方demo一致)
            "auf": "audio/L16;rate=16000",
            "vcn": VOICE_NAME,
            "tte": "utf8"
        },
        "data": {
            "status": 2,
            "text": str(base64.b64encode(text.encode('utf-8')), "UTF8")
        }
    }

    audio_buffer = bytearray()

    # 建立 WebSocket 连接
    async with websockets.connect(auth_url) as ws:
        await ws.send(json.dumps(request_data))

        while True:
            response = await ws.recv()
            res_data = json.loads(response)

            # code == 0 代表成功
            if res_data["code"] != 0:
                print(f"❌ 讯飞接口错误: {res_data['message']} (错误码: {res_data['code']})")
                break

            # 提取 base64 编码的音频片段并解码
            audio_base64 = res_data["data"]["audio"]
            if audio_base64:
                audio_buffer.extend(base64.b64decode(audio_base64))

            # status == 2 代表服务端合成完毕，可以断开
            if res_data["data"]["status"] == 2:
                break

    return bytes(audio_buffer)


def get_vb_cable_device():
    print("🔍 正在扫描系统音频输出设备...")
    devices = sd.query_devices()

    # 遍历寻找虚拟声卡
    for i, dev in enumerate(devices):
        # 只要是能输出声音的设备，我们就打印出来看看（方便排错）
        if dev['max_output_channels'] > 0:
            name_lower = dev["name"].lower()
            # 兼容大小写，同时增加对 vb-audio 的关键词匹配
            if "cable input" in name_lower or "vb-audio" in name_lower:
                print(f"🎯 成功锁定虚拟声卡：[{i}] {dev['name']}")
                return i

    return None


def ai_reply_to_voice(ai_reply: str):
    """主函数：获取内存字节流并推送到虚拟声卡"""
    if not ai_reply.strip():
        return

    try:
        print("⏳ 正在请求讯飞语音合成接口...")

        # 1. 直接获取讯飞的纯内存音频字节流
        audio_bytes = asyncio.run(get_xfyun_audio_bytes(ai_reply))

        if not audio_bytes:
            print("⚠️ 未收到音频数据。")
            return

        # 2. 原始 PCM 16kHz 16bit 单声道 → 直接播放
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)

        # 3. 获取声卡 ID
        device_id = get_vb_cable_device()
        if device_id is None:
            print("❌ 致命错误：找不到名为 'CABLE Input' 的虚拟声卡！")
            print("💡 请检查上方打印的设备列表，看看虚拟声卡到底叫什么名字。")
            return

        # 4. 播放到虚拟声卡 (16000Hz, 16bit PCM)
        print(f"🔊 正在将语音推入通道 ID [{device_id}]...")
        sd.play(audio_array, samplerate=16000, device=device_id)
        sd.wait()
        print("✅ 播放完毕！")

    except Exception as e:
        print(f"⚠️ 语音播放出错：{e}")