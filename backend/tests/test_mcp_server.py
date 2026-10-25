"""MCP читает прогноз без снимков и не раскрывает контрагентов ассистенту."""
import asyncio
import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import event

pytest.importorskip("mcp")

from app import mcp_server as server
from app.db.models import Company, ForecastRun
from app.db.session import SessionLocal, engine
from app.domain.types import ForecastResult, GapAlert
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login


def test_mcp_registers_read_tools():
    tools = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == {"list_companies", "list_clients", "forecast_summary", "what_if"}


@pytest.fixture
def owned(client, monkeypatch):
    monkeypatch.setattr(server, "_USER", "alice")
    data = _import(client, _login(client, "alice"), to_case_csv(make_company()))
    return data["company"]


def test_mcp_forecasts_do_not_write_and_http_still_saves(owned):
    writes = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert json.loads(server.forecast_summary(owned["external_id"]))["as_of"]
        result = json.loads(server.what_if(owned["external_id"], revenue_drop_pct=20))
        assert set(result) == {"headline", "gaps", "before", "after"}
        assert isinstance(server.list_clients(owned["external_id"]), list)
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", record)
    from app.services.forecasting import run_forecast
    with SessionLocal() as session:
        assert session.query(ForecastRun).count() == 0
        run_forecast(session, session.get(Company, owned["id"]))
        assert session.query(ForecastRun).count() == 1


def test_mcp_rejects_foreign_company(owned, monkeypatch):
    monkeypatch.setattr(server, "_USER", "bob")
    assert server.list_companies() == []
    for tool in (server.forecast_summary, server.what_if, server.list_clients):
        with pytest.raises(ValueError, match="Компания не найдена"):
            tool(owned["external_id"])


def test_real_operation_details_never_leave_mcp(client, monkeypatch):
    monkeypatch.setattr(server, "_USER", "alice")
    frame = make_company()
    frame["counterparty_name"] = frame["counterparty_name"] + " СекретКонтрагентаЖ41"
    frame["payment_purpose"] = frame["payment_purpose"] + " НепубличноеНазначениеЖ41"
    imported = _import(client, _login(client, "alice"), to_case_csv(frame))
    company = imported["company"]["external_id"]
    summary = json.loads(server.forecast_summary(company))
    clients = server.list_clients(company)
    assert clients, "Синтетическая история должна содержать крупнейшего клиента"
    scenario = json.loads(server.what_if(company, client_ref=clients[0]["client_ref"], client_delay_weeks=2))
    payload = json.dumps({"summary": summary, "clients": clients, "scenario": scenario}, ensure_ascii=False)
    private = set(frame["counterparty_name"]) | set(frame["payment_purpose"]) | set(frame["counterparty_inn"])
    for value in private - {""}:
        assert value not in payload
    assert "СекретКонтрагентаЖ41" not in payload and "НепубличноеНазначениеЖ41" not in payload
    assert all(set(item) == {"client_ref", "share"} for item in clients)


def test_zero_scenario_matches_actual_base_forecast(owned):
    result = json.loads(server.what_if(owned["external_id"]))
    summary = json.loads(server.forecast_summary(owned["external_id"]))
    first = summary["gaps"][0] if summary["gaps"] else None
    assert result["before"] == result["after"] == {
        "first_gap_date": first["start"] if first else None,
        "shortfall": first["shortfall"] if first else 0,
        "probability": first["probability"] if first else 0,
        "gaps": len(summary["gaps"]),
    }
    assert result["headline"] == summary["headline"]


def test_list_companies_excludes_foreign_and_missing_look_identical(owned, client):
    foreign = _import(client, _login(client, "bob"), to_case_csv(make_company(company_id="FOREIGN")))
    assert server.list_companies() == [owned["external_id"]]
    for tool in (server.forecast_summary, server.what_if, server.list_clients):
        messages = []
        for external_id in (foreign["company"]["external_id"], "MISSING"):
            with pytest.raises(ValueError) as failure:
                tool(external_id)
            messages.append(str(failure.value))
        assert messages == ["Компания не найдена", "Компания не найдена"]


@pytest.mark.parametrize("kwargs", [
    {"revenue_drop_pct": -1}, {"revenue_drop_pct": 91}, {"revenue_drop_pct": float("nan")},
    {"fixed_cost_increase_pct": float("inf")}, {"fixed_cost_increase_pct": 101},
    {"client_delay_weeks": 1}, {"client_delay_weeks": 5}, {"client_delay_weeks": 2.5},
    {"client_delay_weeks": 2}, {"client_ref": "a" * 16},
    {"client_delay_weeks": 2, "client_ref": "ИНН 1234567890"},
])
def test_mcp_validates_scenario_before_opening_database(kwargs, monkeypatch):
    def no_session():
        pytest.fail("Некорректный сценарий не должен обращаться к БД")
    monkeypatch.setattr(server, "SessionLocal", no_session)
    with pytest.raises(ValueError):
        server.what_if("T001", **kwargs)


def test_client_delay_uses_anonymous_selected_client_and_compares_gaps(owned, monkeypatch):
    key, name = "1234567890", "ООО Секретный контрагент"
    model = SimpleNamespace(fitted=SimpleNamespace(top_clients=[(key, name, .75)]))
    monkeypatch.setattr(server, "company_model", lambda session, company: model)
    clients = server.list_clients(owned["external_id"])
    assert clients == [{"client_ref": server._client_ref(owned["id"], key), "share": .75}]
    assert key not in json.dumps(clients) and name not in json.dumps(clients, ensure_ascii=False)
    calls = []
    base = ForecastResult(as_of=date(2026, 1, 1), last_balance=-125.5, threshold=0, points=[], events=[],
                          alerts=[], headline="Денег уже не хватает: 125,50 ₽")
    negative = deepcopy(base)
    negative.alerts = [GapAlert(start=date(2026, 1, 15), end=date(2026, 1, 16), probability=.753,
                               shortfall=12345.67, worst_case=False, level="вероятно")]

    def forecast(session, company, scenario=None, *, save=True):
        assert save is False
        calls.append(scenario)
        return (negative if scenario else base), model

    monkeypatch.setattr(server, "run_forecast", forecast)
    result = json.loads(server.what_if(owned["external_id"], revenue_drop_pct=20,
                                      client_delay_weeks=3, client_ref=clients[0]["client_ref"]))
    assert calls[0] is None
    assert calls[1].client_delays[0].counterparty_key == key
    assert calls[1].client_delays[0].weeks == 3 and calls[1].revenue_drop_pct == 20
    assert result["before"] == {"first_gap_date": None, "shortfall": 0, "probability": 0, "gaps": 0}
    assert result["after"] == {"first_gap_date": "2026-01-15", "shortfall": 12000, "probability": .75, "gaps": 1}
    assert name not in json.dumps(result, ensure_ascii=False) and key not in json.dumps(result)
    assert "125,50" not in result["headline"]
    calls.clear()
    with pytest.raises(ValueError, match="Клиент не найден"):
        server.what_if(owned["external_id"], client_delay_weeks=2, client_ref="0" * 16)
    assert calls == []
