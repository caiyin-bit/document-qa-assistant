"""Tests for GeminiClient — mocks the underlying AsyncOpenAI."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.llm.gemini_client import GeminiClient, LlmResponse, ToolCall


@pytest.fixture()
def fake_client(monkeypatch):
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    return fake


async def test_plain_text_response(fake_client):
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="你好", tool_calls=None, role="assistant")
            )
        ]
    )
    client = GeminiClient(openai_client=fake_client, model_id="gemini-2.5-flash")
    resp: LlmResponse = await client.chat(
        messages=[{"role": "user", "content": "hi"}], tools=[]
    )
    assert resp.content == "你好"
    assert resp.tool_calls == []


async def test_tool_call_response(fake_client):
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    role="assistant",
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="search_documents",
                                arguments='{"query":"张三 画像"}',
                            ),
                        )
                    ],
                )
            )
        ]
    )
    client = GeminiClient(openai_client=fake_client, model_id="gemini-2.5-flash")
    resp = await client.chat(messages=[], tools=[])
    assert resp.content is None
    assert len(resp.tool_calls) == 1
    tc: ToolCall = resp.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.name == "search_documents"
    assert tc.arguments == {"query": "张三 画像"}


async def test_retries_on_transient_error(monkeypatch):
    # 让 create 头两次抛,第三次返回正常
    call_count = {"n": 0}

    async def flaky(**kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("boom")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None, role="assistant")
                )
            ]
        )

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=flaky))
    )
    client = GeminiClient(openai_client=fake, model_id="k", max_retries=3)
    resp = await client.chat(messages=[], tools=[])
    assert resp.content == "ok"
    assert call_count["n"] == 3
