import asyncio
import pytest
from shared_types import VoiceEvent


class FakeReader:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks
        self._idx = 0

    async def read(self, n: int) -> bytes:
        if self._idx >= len(self._chunks):
            raise ConnectionError("EOF")
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


@pytest.mark.asyncio
async def test_serial_reader_decode_gbk(monkeypatch):
    import serial_reader
    fake_reader = FakeReader([
        "请说出一级口令\r\n".encode("gbk"),
        "打开灯光\r\n".encode("gbk"),
    ])
    async def fake_open(*args, **kwargs):
        return fake_reader, None
    monkeypatch.setattr(serial_reader.serial_asyncio, "open_serial_connection", fake_open)
    queue = asyncio.Queue()
    task = asyncio.create_task(serial_reader.run(queue))
    event1 = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event1.text == "请说出一级口令"
    event2 = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event2.text == "打开灯光"
    task.cancel()


@pytest.mark.asyncio
async def test_serial_reader_skips_empty_lines(monkeypatch):
    import serial_reader
    fake_reader = FakeReader([
        "\r\n".encode("gbk"),
        "   \r\n".encode("gbk"),
        "浇水\r\n".encode("gbk"),
    ])
    async def fake_open(*args, **kwargs):
        return fake_reader, None
    monkeypatch.setattr(serial_reader.serial_asyncio, "open_serial_connection", fake_open)
    queue = asyncio.Queue()
    task = asyncio.create_task(serial_reader.run(queue))
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event.text == "浇水"
    task.cancel()
