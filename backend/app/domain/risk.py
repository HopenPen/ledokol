"""Кассовые разрывы: дата, сумма, вероятность, причина и что делать — человеческими словами (US-2, US-3)."""
from __future__ import annotations

from datetime import date

import numpy as np

from app.domain.categories import CATEGORIES, label
from app.domain.types import Direction, ForecastPoint, GapAlert, PlannedEvent

ALERT_MIN_PROB = 0.2
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
           "ноября", "декабря"]


def human_date(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]}"


def rub(x: float) -> str:
    a = abs(x)
    if a >= 1e6:
        return f"{x / 1e6:.1f} млн ₽".replace(".", ",")
    if a >= 1e3:
        return f"{x / 1e3:.0f} тыс. ₽"
    return f"{x:.0f} ₽"


def level_words(p: float) -> str:
    return "почти наверняка" if p >= 0.8 else "вероятно" if p >= 0.5 else "возможно"


def detect_gaps(days: list[date], paths: np.ndarray, events: list[PlannedEvent], threshold: float) -> list[GapAlert]:
    """Эпизод = подряд идущие дни, где ≥ 20% траекторий ниже порога."""
    below = paths < threshold
    p_day = below.mean(axis=0)
    flagged = p_day >= ALERT_MIN_PROB
    alerts: list[GapAlert] = []
    i = 0
    while i < len(days):
        if not flagged[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(days) and flagged[j + 1]:
            j += 1
        window_min = paths[:, i: j + 1].min(axis=1)
        prob = float((window_min < threshold).mean())
        p50, p10 = np.quantile(window_min, [0.5, 0.1])
        worst_case = p50 >= threshold
        shortfall = float(threshold - (p10 if worst_case else p50))
        causes = _causes(days, i, j, events)
        alert = GapAlert(start=days[i], end=days[j], probability=prob, shortfall=round(shortfall, -3) or shortfall,
                         worst_case=worst_case, level=level_words(prob), causes=causes)
        alert.actions = _actions(alert, days, j, events)
        alert.explanation = explain(alert)
        alerts.append(alert)
        i = j + 1
    return alerts


def _causes(days: list[date], i: int, j: int, events: list[PlannedEvent]) -> list[PlannedEvent]:
    lo = days[max(0, i - 5)]
    outs = sorted((e for e in events if e.direction is Direction.OUT and lo <= e.event_date <= days[j]),
                  key=lambda e: e.amount, reverse=True)
    unique, seen = [], set()
    for e in outs:                      # одна строка на платёж: две зарплатные выплаты не повторяем
        if e.title not in seen:
            seen.add(e.title)
            unique.append(e)
    return unique[:3]


def _actions(a: GapAlert, days: list[date], j: int, events: list[PlannedEvent]) -> list[str]:
    acts: list[str] = []
    after = days[j + 1] if j + 1 < len(days) else None
    movable = [e for e in a.causes if not CATEGORIES.get(e.category, CATEGORIES["other"]).mandatory]
    if movable and after:
        e = movable[0]
        acts.append(f"Перенести «{e.title}» ({rub(e.amount)}) на {human_date(after)} или позже")
    unsure_in = [e for e in events if e.direction is Direction.IN and e.probability < 1 and e.event_date <= a.start]
    if unsure_in:
        e = max(unsure_in, key=lambda x: x.amount)
        acts.append(f"Напомнить об оплате: «{e.title}» ({rub(e.amount)})")
    acts.append(f"Подключить овердрафт на {rub(a.shortfall * 1.1)} — заявка в приложении банка")
    return acts


def explain(a: GapAlert) -> str:
    """Шаблонное объяснение без LLM — работает всегда, в том числе на скрытом датасете."""
    when = human_date(a.start)
    scope = "в плохом сценарии " if a.worst_case else ""
    head = f"{when.capitalize()} {scope}может не хватить {rub(a.shortfall)} ({a.level}, {a.probability:.0%})."
    if a.causes:
        why = ", ".join(f"{label(c.category)} {rub(c.amount)}" for c in a.causes[:2])
        head += f" Главные платежи в эти дни: {why}."
    return head


def build_headline(points: list[ForecastPoint], alerts: list[GapAlert], threshold: float) -> str:
    if not points:
        return "Недостаточно данных для прогноза"
    if alerts:
        a = alerts[0]
        if a.worst_case:   # в медианном сценарии денег хватает — так и говорим, без паники
            return f"Скорее всего денег хватит, но в плохом сценарии с {human_date(a.start)} не хватит {rub(a.shortfall)}"
        return f"Денег хватит до {human_date(a.start)}: дальше {a.level} не хватит {rub(a.shortfall)}"
    return f"На ближайшие {len(points)} рабочих дней денег хватает: минимум {rub(min(p.p50 for p in points))}"
