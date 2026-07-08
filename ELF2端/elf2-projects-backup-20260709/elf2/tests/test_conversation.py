import asyncio
import pytest


@pytest.mark.asyncio
async def test_conversation_queue_flow(monkeypatch):
    import conversation
    class FakeChat:
        def __init__(self):
            self.history = []
        def chat(self, text):
            return "你好呀，今天想聊什么？"
    async def fake_run(dialog_q, tts_q):
        conv = FakeChat()
        while True:
            user_text = await dialog_q.get()
            reply = await asyncio.to_thread(conv.chat, user_text)
            await tts_q.put(reply)
    monkeypatch.setattr(conversation, "run", fake_run)
    dialog_queue = asyncio.Queue()
    tts_queue = asyncio.Queue()
    task = asyncio.create_task(conversation.run(dialog_queue, tts_queue))
    await dialog_queue.put("今天天气好吗")
    reply = await asyncio.wait_for(tts_queue.get(), timeout=2.0)
    assert reply == "你好呀，今天想聊什么？"
    task.cancel()


def test_conversation_history_management(monkeypatch):
    from conversation import Conversation
    call_count = 0
    class FakeResp:
        class Choice:
            class Message:
                content = "测试回复"
            message = Message()
        choices = [Choice()]
    def fake_create(*, model, messages, temperature, max_tokens, timeout, **kwargs):
        nonlocal call_count
        call_count += 1
        return FakeResp()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    conv = Conversation()
    conv.client.chat.completions.create = fake_create
    assert conv.history == []
    reply1 = conv.chat("第一句话")
    assert reply1 == "测试回复"
    assert len(conv.history) == 2
    reply2 = conv.chat("第二句话")
    assert len(conv.history) == 4
