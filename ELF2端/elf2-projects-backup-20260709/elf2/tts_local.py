import asyncio
import shutil
import subprocess
import os
from vtube_client import VTubeClient

_HAS_PIPER_CLI = shutil.which("piper") is not None
try:
    import piper.voice
    _HAS_PIPER_BINDING = True
except ImportError:
    _HAS_PIPER_BINDING = False

HAS_PIPER = _HAS_PIPER_CLI and _HAS_PIPER_BINDING


async def speak_piper(text: str) -> bytes:
    model_path = os.path.expanduser("~/.local/share/piper-tts/zh_CN-huayan-medium.onnx")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Piper 模型不存在: {model_path}")
    proc = await asyncio.create_subprocess_exec(
        "piper", "--model", model_path, "--output-raw",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate(text.encode("utf-8"))
    return stdout


async def speak_espeak(text: str):
    proc = await asyncio.create_subprocess_exec(
        "espeak-ng", "-v", "zh", "-s", "150", text,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def run(tts_queue: asyncio.Queue):
    vtube = VTubeClient()
    await vtube.connect()
    if vtube._ws:
        await vtube.authenticate()

    while True:
        text: str = await tts_queue.get()
        print(f"[TTS] 开始合成: {text[:30]}...")
        try:
            if HAS_PIPER:
                audio = await speak_piper(text)
                proc = await asyncio.create_subprocess_exec(
                    "aplay", "-f", "S16_LE", "-r", "16000", "-c", "1",
                    stdin=asyncio.subprocess.PIPE,
                )
                await proc.communicate(audio)
            else:
                await speak_espeak(text)

            await vtube.set_mouth_open(1.0)
            duration = max(len(text) * 0.15, 0.5)
            await asyncio.sleep(duration)
            await vtube.set_mouth_close()
        except Exception as e:
            print(f"[TTS] 错误: {e}")
            await vtube.set_mouth_close()
