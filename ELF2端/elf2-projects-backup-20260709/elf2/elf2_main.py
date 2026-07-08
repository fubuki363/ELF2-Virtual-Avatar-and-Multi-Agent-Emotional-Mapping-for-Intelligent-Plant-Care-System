import asyncio
import signal
import sys

import database
import serial_reader
import intent_router
import hardware_control
import mqtt_bridge
import conversation
import tts_local


async def main():
    text_queue = asyncio.Queue()
    cmd_queue = asyncio.Queue()
    dialog_queue = asyncio.Queue()
    tts_queue = asyncio.Queue()

    print("=" * 40)
    print(" ELF2 酢酱酱本地分身启动中...")
    print("=" * 40)

    database.init_tables()

    async def shutdown():
        print("\n 正在关闭所有模块...")
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        await asyncio.sleep(0.5)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda: asyncio.create_task(shutdown())
        )

    try:
        await asyncio.gather(
            serial_reader.run(text_queue),
            intent_router.run(text_queue, cmd_queue, dialog_queue),
            hardware_control.run(cmd_queue),
            mqtt_bridge.run(),
            conversation.run(dialog_queue, tts_queue),
            tts_local.run(tts_queue),
        )
    except asyncio.CancelledError:
        print("[主程序] 已停止")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  ELF2 酢酱酱本地分身下班啦！")
        sys.exit(0)
