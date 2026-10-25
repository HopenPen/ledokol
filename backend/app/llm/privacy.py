"""Обезличенная сводка прогноза для LLM. Единственное место, через которое данные уходят в модель —
поэтому его легко ревьюить: здесь видно ВСЁ, что видит провайдер."""
from __future__ import annotations

import json

from app.domain.categories import label
from app.domain.types import ForecastResult


def _round(x: float) -> int:
    """Округляем до тысяч: точная сумма не нужна для объяснения и сужает возможность сопоставления."""
    return int(round(x, -3))


def _action_types(actions: list[str]) -> list[str]:
    kinds = {"Перенести": "перенести необязательный платёж", "Напомнить": "напомнить клиенту об оплате",
             "Подключить овердрафт": "овердрафт в банке"}
    return [v for k, v in kinds.items() if any(a.startswith(k) for a in actions)]


def build_context(res: ForecastResult) -> str:
    ctx = {
        "as_of": res.as_of.isoformat(),
        "balance_now": _round(res.last_balance),
        "threshold": _round(res.threshold),
        # UI показывает текущую нехватку до копеек; этот текст не должен обходить округление агрегатов.
        "headline": ("Последний известный остаток ниже установленного порога."
                     if res.last_balance < res.threshold else res.headline),
        "first_recovery_date": next((p.day.isoformat() for p in res.points if p.p50 >= res.threshold), None)
                               if res.last_balance < res.threshold else None,
        "min_p50": _round(min(p.p50 for p in res.points)) if res.points else None,
        "gaps": [{
            "start": a.start.isoformat(), "end": a.end.isoformat(), "probability": round(a.probability, 2),
            "shortfall": _round(a.shortfall), "only_in_bad_case": bool(a.worst_case),
            "main_payments": [{"category": label(c.category), "amount": _round(c.amount),
                               "date": c.event_date.isoformat(), "source": c.source.value} for c in a.causes],
            # тексты рекомендаций не передаём: в них есть названия контрагентов. Только типы действий.
            "action_types": _action_types(a.actions),
        } for a in res.alerts],
        # будущие события — только категория, сумма, дата и источник; title не передаём (там имя контрагента)
        "upcoming": [{"date": e.event_date.isoformat(), "category": label(e.category), "direction": e.direction.value,
                      "amount": _round(e.amount), "probability": round(e.probability, 2), "source": e.source.value}
                     for e in res.events[:40]],
        "warnings": res.data_warnings,
    }
    return json.dumps(ctx, ensure_ascii=False)
