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
import soundfile as sf
import sounddevice as sd
import io

load_dotenv()

# ================= 配置 =================
APPID = os.getenv("XFYUN_APPID")
APIKey = os.getenv("XFYUN_APIKEY")
APISecret = os.getenv("XFYUN_APISECRET")
XFYUN_URL = "wss://tts-api.xfyun.cn/v2/tts"
VOICE_NAME = "x4_lingxiaoyu_emo"  # 讯飞发音人


# ========================================

def build_auth_url(request_url, api_key, api_secret):
    """动态生成带有签名的鉴权 URL"""
    parsed_url = urlparse(request_url)
    host = parsed_url.netloc
    path = parsed_url.path

    # 1. 生成当前时间的 RFC1123 格式字符串
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))

    # 2. 拼接签名原始字符串
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"

    # 3. HMAC-SHA256 加密
    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()

    # 4. Base64 编码
    signature_sha = base64.b64encode(signature_sha).decode('utf-8')

    # 5. 构建 Authorization (v2 接口不需要 base64 编码)
    authorization_origin = f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'

    # 6. 拼接到 URL 参数中 (v2: authorization 直接传原始字符串)
    params = {
        "authorization": authorization_origin,
        "date": date,
        "host": host
    }
    return f"{request_url}?{urlencode(params)}"


async def get_xfyun_audio_bytes(text: str) -> bytes:
    """连接讯飞 WebSocket 接口并获取音频字节流（MP3格式）"""
    auth_url = build_auth_url(XFYUN_URL, APIKey, APISecret)

    # 构建请求 JSON 体
    request_data = {
        "common": {"app_id": APPID},
        "business": {
            "aue": "lame",  # 音频编码格式：lame 表示要求返回 MP3 格式
            "sfl": 1,  # 开启流式返回
            "vcn": VOICE_NAME,
            "speed": 55,  # 语速 0-100
            "volume": 100,  # 音量 0-100
            "pitch": 60,  # 音高 0-100
            "bgs": 0,  # 背景音 0或1
            "tte": "utf8"  # 文本编码格式
        },
        "data": {
            "status": 2,  # 2代表只有一段文本请求
            "text": base64.b64encode(text.encode('utf-8')).decode('utf-8')
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

        # 2. 用 io.BytesIO 将内存数据伪装成文件供播放
        data, sr = sf.read(io.BytesIO(audio_bytes))

        # 3. 获取声卡 ID 并施加严格拦截
        device_id = get_vb_cable_device()
        if device_id is None:
            # 如果找不到，直接拦截播放，坚决不让你听到机器音！
            print("❌ 致命错误：找不到名为 'CABLE Input' 的虚拟声卡！")
            print("💡 请检查上方打印的设备列表，看看虚拟声卡到底叫什么名字。")
            return

        # 4. 播放到虚拟声卡
        print(f"🔊 正在将语音推入通道 ID [{device_id}]...")
        sd.play(data, sr, device=device_id)
        sd.wait()
        print("✅ 播放完毕！")

    except Exception as e:
        print(f"⚠️ 语音播放出错：{e}")