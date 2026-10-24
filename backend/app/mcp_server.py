"""MCP-сервер поверх тех же сервисов (опционально, задел на развитие).

Идея для презентации: ассистент банка (или любой MCP-клиент) отвечает на «хватит ли мне денег до зарплаты?»,
вызывая наши инструменты, а не пересказывая выписку. Наружу отдаём только агрегаты прогноза — та же
обезличенная сводка, что и для LLM (app.llm.privacy).

Запуск: CASHFLOW_MCP_USER=demo python -m app.mcp_server   (stdio-транспорт, локально)
Запись (добавление события) намеренно не открыта: изменение данных — только через UI с подтверждением.
"""
from __future__ import annotations

import json
import os

from sqlalchemy import select

from app.db.models import Company, User
from app.db.session import SessionLocal
from app.domain.scenarios import Scenario
from app.llm.privacy import build_context
from app.services.forecasting import run_forecast

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit('Установите опциональную зависимость: pip install ".[mcp]"') from exc

mcp = FastMCP("cashflow")
_USER = os.environ.get("CASHFLOW_MCP_USER", "demo")


def _company(session, external_id: str) -> Company:
    user = session.scalar(select(User).where(User.login == _USER))
    company = session.scalar(select(Company).where(Company.owner_id == user.id, Company.external_id == external_id)) \
        if user else None
    if company is None:
        raise ValueError("Компания не найдена")
    return company


@mcp.tool()
def list_companies() -> list[str]:
    """Список компаний пользователя (внешние id из выписки)."""
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.login == _USER))
        return list(s.scalars(select(Company.external_id).where(Company.owner_id == user.id))) if user else []


@mcp.tool()
def forecast_summary(company: str) -> str:
    """Обезличенная сводка прогноза остатка на 30 рабочих дней: разрывы, их вероятность и причины."""
    with SessionLocal() as s:
        res, _ = run_forecast(s, _company(s, company))
    return build_context(res)


@mcp.tool()
def what_if(company: str, revenue_drop_pct: float = 0.0, fixed_cost_increase_pct: float = 0.0) -> str:
    """Сценарий «что если»: падение выручки и рост постоянных расходов, в процентах."""
    sc = Scenario(revenue_drop_pct=max(0, min(revenue_drop_pct, 90)),
                  fixed_cost_increase_pct=max(0, min(fixed_cost_increase_pct, 100)))
    with SessionLocal() as s:
        res, _ = run_forecast(s, _company(s, company), scenario=sc)
    return json.dumps({"headline": res.headline, "gaps": len(res.alerts)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
