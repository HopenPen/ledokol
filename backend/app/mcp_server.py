"""MCP-сервер поверх тех же сервисов (опционально, задел на развитие).

Идея для презентации: ассистент банка (или любой MCP-клиент) отвечает на «хватит ли мне денег до зарплаты?»,
вызывая наши инструменты, а не пересказывая выписку. Наружу отдаём только агрегаты прогноза — та же
обезличенная сводка, что и для LLM (app.llm.privacy).

Запуск: CASHFLOW_MCP_USER=demo python -m app.mcp_server   (stdio-транспорт, локально)
Запись (добавление события) намеренно не открыта: изменение данных — только через UI с подтверждением.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.db.models import Company, User
from app.db.session import SessionLocal
from app.domain.scenarios import ClientDelay, Scenario
from app.llm.privacy import build_context
from app.services.forecasting import company_model, run_forecast

try:
    from mcp.types import ToolAnnotations

    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:  # SDK 1.x, который также допускает optional extra.
        from mcp.server.fastmcp import FastMCP as MCPServer
except ImportError as exc:  # pragma: no cover
    raise SystemExit('Установите опциональную зависимость: pip install ".[mcp]"') from exc

mcp = MCPServer("cashflow")
_USER = os.environ.get("CASHFLOW_MCP_USER", "demo")
request_scope: ContextVar[tuple[str, str] | None] = ContextVar("mcp_request_scope", default=None)
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _company(session, external_id: str) -> Company:
    scope = request_scope.get()
    if scope and external_id != scope[1]:
        raise ValueError("Компания не найдена")
    user = session.scalar(select(User).where(User.login == (scope[0] if scope else _USER)))
    company = session.scalar(select(Company).where(Company.owner_id == user.id, Company.external_id == external_id)) \
        if user else None
    if company is None:
        raise ValueError("Компания не найдена")
    return company


@mcp.tool(annotations=_READ_ONLY)
def list_companies() -> list[str]:
    """Список компаний пользователя (внешние id из выписки)."""
    with SessionLocal() as s:
        scope = request_scope.get()
        user = s.scalar(select(User).where(User.login == (scope[0] if scope else _USER)))
        if not user:
            return []
        query = select(Company.external_id).where(Company.owner_id == user.id)
        if scope:
            query = query.where(Company.external_id == scope[1])
        return list(s.scalars(query))


@mcp.tool(annotations=_READ_ONLY)
def forecast_summary(company: str) -> str:
    """Обезличенная сводка прогноза остатка на 30 рабочих дней: разрывы, их вероятность и причины."""
    with SessionLocal() as s:
        res, _ = run_forecast(s, _company(s, company), save=False)
    return build_context(res)


def _client_ref(company_id: str, key: str) -> str:
    # Не передаём ассистенту ИНН или имя; ссылка имеет смысл только в этой компании.
    return hashlib.sha256(f"{company_id}:{key}".encode()).hexdigest()[:16]


@mcp.tool(annotations=_READ_ONLY)
def list_clients(company: str) -> list[dict]:
    """Крупнейшие клиенты: обезличенная ссылка для what_if и доля поступлений, без имён и ИНН."""
    with SessionLocal() as s:
        owned = _company(s, company)
        cm = company_model(s, owned)
        return [{"client_ref": _client_ref(owned.id, key), "share": round(share, 2)}
                for key, _, share in cm.fitted.top_clients]


class _WhatIf(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    revenue_drop_pct: float = Field(default=0, ge=0, le=90)
    fixed_cost_increase_pct: float = Field(default=0, ge=0, le=100)
    client_delay_weeks: int = Field(default=0, strict=True, ge=0, le=4)
    client_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")

    @model_validator(mode="after")
    def _delay_has_client(self):
        if self.client_delay_weeks == 1 or bool(self.client_delay_weeks) != bool(self.client_ref):
            raise ValueError("Для задержки выберите клиента из list_clients и срок от 2 до 4 недель")
        return self


def _gap_summary(result) -> dict:
    # Тот же фильтр обезличивания, что и для LLM, включая округление сумм.
    context = json.loads(build_context(result))
    first = context["gaps"][0] if context["gaps"] else None
    return {"first_gap_date": first["start"] if first else None,
            "shortfall": first["shortfall"] if first else 0,
            "probability": first["probability"] if first else 0,
            "gaps": len(context["gaps"])}


@mcp.tool(annotations=_READ_ONLY)
def what_if(company: str, revenue_drop_pct: float = 0.0, fixed_cost_increase_pct: float = 0.0,
            client_delay_weeks: int = 0, client_ref: str | None = None) -> str:
    """Было → стало: дата, сумма и вероятность разрыва. Задержка клиента — 2–4 недели, ссылка из list_clients.

    Падение выручки: 0–90%, рост расходов: 0–100%. Ничего не сохраняет.
    """
    args = _WhatIf(revenue_drop_pct=revenue_drop_pct, fixed_cost_increase_pct=fixed_cost_increase_pct,
                   client_delay_weeks=client_delay_weeks, client_ref=client_ref)
    with SessionLocal() as s:
        owned = _company(s, company)
        delays = ()
        if args.client_ref:
            cm = company_model(s, owned)
            key = next((key for key, _, _ in cm.fitted.top_clients
                        if _client_ref(owned.id, key) == args.client_ref), None)
            if key is None:
                raise ValueError("Клиент не найден в списке крупнейших клиентов компании")
            delays = (ClientDelay(key, args.client_delay_weeks),)
        sc = Scenario(revenue_drop_pct=args.revenue_drop_pct,
                      fixed_cost_increase_pct=args.fixed_cost_increase_pct, client_delays=delays)
        base, _ = run_forecast(s, owned, save=False)
        res, _ = run_forecast(s, owned, scenario=sc, save=False)
    return json.dumps({"headline": json.loads(build_context(res))["headline"], "gaps": len(res.alerts),
                       "before": _gap_summary(base), "after": _gap_summary(res)}, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
