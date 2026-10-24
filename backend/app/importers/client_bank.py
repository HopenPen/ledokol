"""Адаптер текстовой выписки 1CClientBankExchange (UTF-8, Windows-1251, DOS)."""
from app.domain.ingest import StatementFormatError
from app.domain.statements import BalancePeriod, BankPayment, BankStatement
from app.importers.common import account_number, bank_date, inn, money


def parse_client_bank(raw: bytes) -> list[BankStatement]:
    text = None
    for encoding in ("utf-8-sig", "cp1251", "cp866"):
        try:
            candidate = raw.decode(encoding)
            if "КонецФайла" in candidate and "СекцияРасчСчет" in candidate:
                text = candidate
                break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise StatementFormatError("Ожидается TXT в формате 1CClientBankExchange")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines[0] != "1CClientBankExchange" or lines[-1] != "КонецФайла":
        raise StatementFormatError("TXT-выписка повреждена или обрезана")
    sections, documents, current = [], [], None
    for line in lines[1:-1]:
        if line == "СекцияРасчСчет" or line.startswith("СекцияДокумент="):
            if current is not None:
                raise StatementFormatError("Незавершённая секция TXT-выписки")
            current = ("account" if line == "СекцияРасчСчет" else "document", {})
        elif line in {"КонецРасчСчет", "КонецДокумента"}:
            expected = "account" if line == "КонецРасчСчет" else "document"
            if current is None or current[0] != expected:
                raise StatementFormatError("Неверная структура TXT-выписки")
            (sections if expected == "account" else documents).append(current[1])
            current = None
        elif current is not None:
            key, sep, value = line.partition("=")
            if not sep or key in current[1]:
                raise StatementFormatError("Некорректное или повторное поле TXT-выписки")
            current[1][key] = value
    if current is not None or not sections:
        raise StatementFormatError("В TXT-выписке отсутствует завершённая секция счёта")
    try:
        accounts = {}
        for section in sections:
            number = account_number(section["РасчСчет"])
            entry = accounts.setdefault(number, {"periods": [], "payments": [], "name": ""})
            entry["periods"].append(BalancePeriod(bank_date(section["ДатаНачала"]), bank_date(section["ДатаКонца"]),
                                                  money(section["НачальныйОстаток"]), money(section["КонечныйОстаток"]),
                                                  money(section["ВсегоПоступило"]) if "ВсегоПоступило" in section else None,
                                                  money(section["ВсегоСписано"]) if "ВсегоСписано" in section else None))
        for doc in documents:
            matched = False
            for side, other, direction, posted in (("Плательщик", "Получатель", "out", "ДатаСписано"),
                                                     ("Получатель", "Плательщик", "in", "ДатаПоступило")):
                entry = accounts.get(doc.get(side + "Счет"))
                if entry is None or not doc.get(posted):
                    continue
                matched = True
                entry["name"] = doc.get(side + "1") or doc.get(side, "")
                entry["payments"].append(BankPayment(
                    bank_date(doc[posted]), doc["Номер"], money(doc["Сумма"]), direction,
                    doc.get(other + "1") or doc.get(other, ""), inn(doc.get(other + "ИНН", "")),
                    doc.get(other + "Счет", ""), doc.get("НазначениеПлатежа", "")))
            if not matched:
                raise StatementFormatError("В TXT есть платёж без даты проведения по указанному счёту")
        return [BankStatement(number, data["name"], data["payments"], data["periods"])
                for number, data in accounts.items()]
    except KeyError:
        raise StatementFormatError("В TXT-выписке не хватает обязательных реквизитов") from None
