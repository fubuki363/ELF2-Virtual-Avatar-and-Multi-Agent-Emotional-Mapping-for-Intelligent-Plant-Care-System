import asyncio
import json
import pytest
from shared_types import VoiceEvent, CommandEvent


@pytest.mark.asyncio
async def test_intent_router_hardware_command(monkeypatch, tmp_path):
    import intent_router
    monkeypatch.setattr(intent_router.database, "save_command", lambda *a, **kw: None)
    test_commands = {"开灯": [{"d": "led", "mode": "white", "brightness": 200}], "浇水": [{"d": "pump", "v": 80}]}
    cmd_file = tmp_path / "voice_commands.json"
    cmd_file.write_text(json.dumps(test_commands), encoding="utf-8")
    monkeypatch.setattr(intent_router, "COMMANDS_FILE", str(cmd_file))
    text_queue = asyncio.Queue()
    cmd_queue = asyncio.Queue()
    dialog_queue = asyncio.Queue()
    task = asyncio.create_task(intent_router.run(text_queue, cmd_queue, dialog_queue))
    await text_queue.put(VoiceEvent(text="开灯", timestamp=1.0))
    cmd = await asyncio.wait_for(cmd_queue.get(), timeout=1.0)
    assert cmd.commands == [{"d": "led", "mode": "white", "brightness": 200}]
    assert cmd.source == "voice"
    task.cancel()


@pytest.mark.asyncio
async def test_intent_router_dialog_fallback(monkeypatch, tmp_path):
    import intent_router
    cmd_file = tmp_path / "voice_commands.json"
    cmd_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(intent_router, "COMMANDS_FILE", str(cmd_file))
    text_queue = asyncio.Queue()
    cmd_queue = asyncio.Queue()
    dialog_queue = asyncio.Queue()
    task = asyncio.create_task(intent_router.run(text_queue, cmd_queue, dialog_queue))
    await text_queue.put(VoiceEvent(text="今天天气真好", timestamp=1.0))
    dialog_text = await asyncio.wait_for(dialog_queue.get(), timeout=1.0)
    assert dialog_text == "今天天气真好"
    task.cancel()


@pytest.mark.asyncio
async def test_intent_router_partial_match(monkeypatch, tmp_path):
    import intent_router
    monkeypatch.setattr(intent_router.database, "save_command", lambda *a, **kw: None)
    test_commands = {"开灯": [{"d": "led", "v": 100}]}
    cmd_file = tmp_path / "voice_commands.json"
    cmd_file.write_text(json.dumps(test_commands), encoding="utf-8")
    monkeypatch.setattr(intent_router, "COMMANDS_FILE", str(cmd_file))
    text_queue = asyncio.Queue()
    cmd_queue = asyncio.Queue()
    dialog_queue = asyncio.Queue()
    task = asyncio.create_task(intent_router.run(text_queue, cmd_queue, dialog_queue))
    await text_queue.put(VoiceEvent(text="帮我开灯", timestamp=1.0))
    cmd = await asyncio.wait_for(cmd_queue.get(), timeout=1.0)
    assert cmd.commands == [{"d": "led", "v": 100}]
    task.cancel()
