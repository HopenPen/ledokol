import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

pytest.importorskip("mcp.client.client")

from app import mcp_chat


@pytest.mark.parametrize("tool", ["list_companies", "delete_company"])
def test_tool_roundtrip(client, monkeypatch, tool):
    monkeypatch.setattr(mcp_chat, "get_settings", lambda: SimpleNamespace(
        llm_api_key=SecretStr("test-secret"), llm_model="test-model", llm_base_url="https://example.invalid/v1"))
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert {t["function"]["name"] for t in body["tools"]} == mcp_chat.ALLOWED
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call1", "type": "function", "function": {"name": tool, "arguments": "{}"}}]}
        else:
            result = body["messages"][-1]
            assert result["role"] == "tool" and result["tool_call_id"] == "call1"
            if tool == "delete_company":
                assert "не выполнил" in result["content"]
            else:
                assert "не выполнил" not in result["content"]
            message = {"role": "assistant", "content": "Готово"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    assert asyncio.run(mcp_chat.ask("Покажи компании", transport=httpx.MockTransport(respond))) == "Готово"
    assert len(requests) == 2


def test_provider_error_does_not_expose_body(client, monkeypatch):
    monkeypatch.setattr(mcp_chat, "get_settings", lambda: SimpleNamespace(
        llm_api_key=SecretStr("test-secret"), llm_model="test", llm_base_url="https://example.invalid/v1"))
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="private provider details"))
    with pytest.raises(RuntimeError, match="Ошибка MCP") as error:
        asyncio.run(mcp_chat.ask("Вопрос", transport=transport))
    assert "private" not in str(error.value)
