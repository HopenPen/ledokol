"""Налоговые сроки РФ на 2026 год для МСП: что и когда платится. Используется прогнозом (подписи событий),
UI (объяснение «почему 28-го списание») и имитатором ФНС.

Сверено по открытым источникам на 24.10.2026 (Точка, Главбух, Контур, buh.ru — ссылки в docs/ru_regulatory_basis.md).
Это не юридическая консультация; перед защитой сверить с НК РФ и сайтом ФНС.

Главное для прогноза:
- ЕНП: единый срок — 28-е число; выпал на выходной → ближайший рабочий день;
- УСН: авансы до 28 апреля / июля / октября, налог за год: ООО — до 28 марта, ИП — до 28 апреля;
- НДС (с 2026 основная ставка 22%; на УСН 5% / 7% при доходе выше 20 млн ₽): за квартал тремя равными
  долями до 28-го в каждом из трёх следующих месяцев;
- НДФЛ (налоговый агент): удержанный 1–22 числа — до 28-го того же месяца, 23-го — конца месяца —
  до 5-го следующего; за 23–31 декабря — до последнего рабочего дня года;
- страховые взносы с зарплаты — до 28-го следующего месяца;
- взносы ИП «за себя»: фиксированные 57 390 ₽ — до 28 декабря, 1% с дохода свыше 300 тыс. ₽ — до 1 июля
  следующего года.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.calendar import is_working_day, next_working_day

VAT_RATE_2026 = 0.22
USN_VAT_EXEMPTION_LIMIT_2026 = 20_000_000
IP_FIXED_CONTRIBUTIONS_2026 = 57_390


@dataclass(frozen=True, slots=True)
class TaxDeadline:
    due: date
    code: str        # enp | usn_advance | usn_year | vat_part | ndfl_28 | ndfl_5 | insurance | ip_fixed | ip_1pct
    title: str


def _d(y: int, m: int, day: int) -> date:
    return next_working_day(date(y, m, day))


def _last_working_day(y: int) -> date:
    d = date(y, 12, 31)
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def deadlines(year: int, regime: str, legal_form: str, has_employees: bool = True,
              vat_payer: bool = False) -> list[TaxDeadline]:
    """Все сроки года. regime: usn | osno | eskhn | unknown; legal_form: ООО | ИП."""
    out: list[TaxDeadline] = []
    for m in range(1, 13):
        out.append(TaxDeadline(_d(year, m, 28), "enp", "Единый налоговый платёж (ЕНП)"))
        if has_employees:
            out.append(TaxDeadline(_d(year, m, 28), "ndfl_28", "НДФЛ за сотрудников (1–22 число)"))
            out.append(TaxDeadline(_d(year, m, 5) if m > 1 else _d(year, 1, 12), "ndfl_5",
                                   "НДФЛ за сотрудников (23 число — конец прошлого месяца)"))
            out.append(TaxDeadline(_d(year, m, 28), "insurance", "Страховые взносы с зарплаты"))
    if has_employees:
        out.append(TaxDeadline(_last_working_day(year), "ndfl_dec", "НДФЛ за 23–31 декабря"))
    if regime in ("usn", "unknown"):
        for m, q in ((4, "I квартал"), (7, "полугодие"), (10, "9 месяцев")):
            out.append(TaxDeadline(_d(year, m, 28), "usn_advance", f"Аванс по УСН за {q}"))
        out.append(TaxDeadline(_d(year, 3 if legal_form == "ООО" else 4, 28), "usn_year",
                               f"УСН за {year - 1} год"))
    if regime == "osno" or vat_payer:
        for m in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
            out.append(TaxDeadline(_d(year, m, 28), "vat_part", "НДС: треть суммы за прошлый квартал"))
    if legal_form == "ИП":
        out.append(TaxDeadline(_d(year, 7, 1), "ip_1pct", f"Взносы ИП 1% с дохода свыше 300 тыс. ₽ за {year - 1} год"))
        out.append(TaxDeadline(_d(year, 12, 28), "ip_fixed", "Фиксированные взносы ИП за себя"))
    return sorted(out, key=lambda t: t.due)


def explain_enp(due: date, regime: str, legal_form: str) -> str:
    """Подпись к прогнозному списанию 28-го: из чего обычно состоит ЕНП в этом месяце."""
    parts = [t.title for t in deadlines(due.year, regime, legal_form) if t.due == due and t.code != "enp"]
    return "ЕНП: " + ", ".join(parts).lower() if parts else "Единый налоговый платёж"
