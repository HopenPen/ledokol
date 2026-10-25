from types import SimpleNamespace

import pytest

from app.llm.chat_files import MAX_BYTES, content_part
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login


def test_text_file_is_context_not_instruction():
    result = content_part("../notes.txt", "Оплата 12500 рублей".encode())
    assert result["type"] == "text"
    assert "12500" in result["text"]
    assert "../" not in result["text"]
    assert "не инструкции" in result["text"]


@pytest.mark.parametrize("name,raw", [("x.exe", b"MZ"), ("x.png", b"not an image"),
                                      ("x.txt", b""), ("x.txt", b"a" * (MAX_BYTES + 1))],
                         ids=["unsupported", "bad-image", "empty", "oversize"])
def test_rejects_invalid_files(name, raw):
    with pytest.raises(ValueError):
        content_part(name, raw)


def test_upload_requires_consent_and_company_ownership(client, monkeypatch):
    from app import mcp_chat
    from app.api.routes import planning

    alice = _login(client, "alice")
    own = _import(client, alice, to_case_csv(make_company()))["company"]
    foreign = _import(client, _login(client, "bob"), to_case_csv(make_company(company_id="FOREIGN")))["company"]
    monkeypatch.setattr(planning, "get_settings", lambda: SimpleNamespace(llm_mcp_enabled=True, llm_model="test"))
    calls = []

    async def answer(question, *, scope, attachments):
        calls.append((question, scope, attachments))
        return "В файле сумма 12500 рублей."

    monkeypatch.setattr(mcp_chat, "ask", answer)
    def upload(cid, consent):
        return client.post(f"/api/companies/{cid}/assistant/ask-with-files", headers=alice,
                           data={"question": "Какая сумма?", "consent": consent},
                           files=[("files", ("note.txt", b"Amount: 12500 RUB", "text/plain"))])

    assert upload(own["id"], "false").status_code == 422
    assert upload(foreign["id"], "true").status_code == 404
    assert calls == []
    result = upload(own["id"], "true")
    assert result.status_code == 200
    assert len(calls) == 1
    assert calls[0][1] == ("alice", own["external_id"])
    assert "12500" in calls[0][2][0]["text"]
