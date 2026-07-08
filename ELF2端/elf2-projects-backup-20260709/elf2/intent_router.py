import asyncio
import json
import os
from shared_types import VoiceEvent, CommandEvent
import database

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "voice_commands.json")


def load_commands() -> dict[str, list[dict]]:
    with open(COMMANDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def run(
    text_queue: asyncio.Queue,
    cmd_queue: asyncio.Queue,
    dialog_queue: asyncio.Queue,
):
    commands_map = load_commands()
    while True:
        event: VoiceEvent = await text_queue.get()
        text = event.text
        matched = False
        for keyword, cmds in commands_map.items():
            if keyword in text:
                cmd_event = CommandEvent(commands=cmds, source="voice")
                await cmd_queue.put(cmd_event)
                print(f"[意图] '{text}' -> 硬件指令: {cmds}")
                await asyncio.to_thread(
                    database.save_command, text, keyword, cmds, "voice"
                )
                matched = True
                break
        if not matched:
            await dialog_queue.put(text)
            print(f"[意图] '{text}' -> 对话管线")
