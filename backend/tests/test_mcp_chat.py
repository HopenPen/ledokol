import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

pytest.importorskip("mcp.client.client")

from app import mcp_chat, mcp_server
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login


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


def test_web_assistant_binds_authenticated_company(client, monkeypatch):
    from app.api.routes import planning

    own = _import(client, _login(client, "alice"), to_case_csv(make_company()))["company"]
    foreign = _import(client, _login(client, "bob"), to_case_csv(make_company(company_id="FOREIGN")))["company"]
    monkeypatch.setattr(planning, "get_settings", lambda: SimpleNamespace(llm_mcp_enabled=True, llm_model="test-opus"))
    calls = []

    async def answer(question, *, scope):
        calls.append(scope)
        token = mcp_server.request_scope.set(scope)
        try:
            assert mcp_server.list_companies() == [own["external_id"]]
            with pytest.raises(ValueError, match="Компания не найдена"):
                mcp_server.forecast_summary(foreign["external_id"])
        finally:
            mcp_server.request_scope.reset(token)
        return "Денег хватает."

    monkeypatch.setattr(mcp_chat, "ask", answer)
    response = client.post(f"/api/companies/{own['id']}/assistant/ask", headers=_login(client, "alice"),
                           json={"question": "Хватит ли денег?"})
    assert response.status_code == 200
    assert response.json() == {"answer": "Денег хватает.", "generated_by": "test-opus+mcp"}
    denied = client.post(f"/api/companies/{foreign['id']}/assistant/ask", headers=_login(client, "alice"),
                        json={"question": "Хватит ли денег?"})
    assert denied.status_code == 404
    assert calls == [("alice", own["external_id"])]


def test_mcp_request_scopes_are_isolated(client):
    from mcp import Client

    _import(client, _login(client, "alice"), to_case_csv(make_company(company_id="ALICE")))
    _import(client, _login(client, "bob"), to_case_csv(make_company(company_id="BOB")))

    async def exchange(login, company):
        token = mcp_server.request_scope.set((login, company))
        try:
            async with Client(mcp_server.mcp) as connection:
                result = await connection.call_tool("list_companies", {})
                assert not result.is_error
                text = "\n".join(block.text for block in result.content if block.type == "text")
                assert company in text
                assert ("BOB" if company == "ALICE" else "ALICE") not in text
        finally:
            mcp_server.request_scope.reset(token)

    async def both():
        await asyncio.gather(exchange("alice", "ALICE"), exchange("bob", "BOB"))

    asyncio.run(both())
    assert mcp_server.request_scope.get() is None
