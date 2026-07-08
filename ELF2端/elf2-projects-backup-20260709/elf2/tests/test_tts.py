import asyncio
import pytest


@pytest.mark.asyncio
async def test_tts_queue_flow():
    import tts_local
    original_speak = tts_local.speak_espeak
    call_log = []
    async def fake_speak(text):
        call_log.append(text)
    tts_local.speak_espeak = fake_speak
    tts_local.HAS_PIPER = False
    tts_queue = asyncio.Queue()
    task = asyncio.create_task(tts_local.run(tts_queue))
    await tts_queue.put("你好世界")
    await asyncio.sleep(1.5)
    assert len(call_log) == 1
    assert call_log[0] == "你好世界"
    tts_local.speak_espeak = original_speak
    task.cancel()


@pytest.mark.asyncio
async def test_vtube_client_mock():
    from vtube_client import VTubeClient
    client = VTubeClient()
    assert client._ws is None
    assert client._request_id == 0
    await client.connect()
    assert client._ws is None
