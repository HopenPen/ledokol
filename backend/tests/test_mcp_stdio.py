"""Проверяем настоящий stdio-процесс, а не только прямой вызов Python-функций."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.client.client")

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from app.db.models import ForecastRun
from app.db.session import SessionLocal, engine
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login


def _value(result):
    assert not result.is_error, result.content
    structured = result.structured_content
    if structured is not None:
        return structured.get("result", structured)
    text = next(block.text for block in result.content if block.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def test_stdio_handshake_and_read_tools(client):
    own = _import(client, _login(client, "alice"), to_case_csv(make_company()))["company"]["external_id"]
    foreign = _import(client, _login(client, "bob"), to_case_csv(make_company(company_id="FOREIGN")))["company"]["external_id"]
    # Абсолютный адрес не зависит от рабочего каталога дочернего процесса.
    database_url = engine.url
    assert database_url.drivername == "sqlite" and database_url.database not in {None, ":memory:"}
    database_url = database_url.set(database=str(Path(database_url.database).resolve()))
    env = {**os.environ, "CASHFLOW_DATABASE_URL": database_url.render_as_string(hide_password=False),
           "CASHFLOW_ENV": "test", "CASHFLOW_MCP_USER": "alice", "PYTHONIOENCODING": "utf-8"}
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"],
                                       cwd=Path(__file__).resolve().parents[1], env=env)

    async def exchange():
        async with Client(parameters, read_timeout_seconds=30) as connection:
            # Вход в контекст выполняет initialize и initialized по реальному stdio.
            tools = (await connection.list_tools()).tools
            assert {tool.name for tool in tools} == {"list_companies", "list_clients", "forecast_summary", "what_if"}
            for tool in tools:
                hints = tool.annotations.model_dump(by_alias=True)
                assert hints["readOnlyHint"] is True and hints["destructiveHint"] is False
                assert hints["idempotentHint"] is True and hints["openWorldHint"] is False
            assert _value(await connection.call_tool("list_companies")) == [own]
            summary = _value(await connection.call_tool("forecast_summary", {"company": own}))
            if isinstance(summary, str):
                summary = json.loads(summary)
            assert summary["as_of"] and "gaps" in summary
            assert isinstance(_value(await connection.call_tool("list_clients", {"company": own})), list)
            scenario = _value(await connection.call_tool("what_if", {"company": own}))
            if isinstance(scenario, str):
                scenario = json.loads(scenario)
            assert scenario["before"] == scenario["after"]
            for name in ("forecast_summary", "what_if", "list_clients"):
                denied = await connection.call_tool(name, {"company": foreign})
                missing = await connection.call_tool(name, {"company": "MISSING"})
                assert denied.is_error
                assert missing.is_error and denied.content == missing.content
                assert foreign not in str(denied.content)
            invalid = await connection.call_tool("what_if", {"company": own, "revenue_drop_pct": 101})
            assert invalid.is_error

    asyncio.run(asyncio.wait_for(exchange(), timeout=60))
    with SessionLocal() as session:
        assert session.query(ForecastRun).count() == 0
