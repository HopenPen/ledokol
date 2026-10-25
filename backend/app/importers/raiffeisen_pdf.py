"""Текстовые рублёвые выписки Райффайзенбанка с 11-колоночной таблицей. OCR не используется."""
import io
import re

import pdfplumber
from pdfminer.pdfexceptions import PDFException
from pdfminer.psparser import PSException
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from app.domain.ingest import StatementFormatError
from app.domain.statements import BalancePeriod, BankPayment, BankStatement
from app.importers.common import account_number, bank_date, inn, money

_DATE = r"\d{2}\.\d{2}\.\d{4}"


def parse_pdf(raw: bytes) -> list[BankStatement]:
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if len(pdf.pages) > 100:
                raise StatementFormatError("PDF содержит больше 100 страниц; разделите выписку по периодам")
            texts, tables = [], []
            for page in pdf.pages:
                text = page.extract_text() or ""
                if not text.strip():
                    raise StatementFormatError("PDF содержит скан. Загрузите текстовую выписку или TXT из клиент-банка")
                texts.append(text)
                tables.extend(page.extract_tables())
        return [_read_tables("\n".join(texts), tables)]
    except StatementFormatError:
        raise
    except (PDFException, PSException, MalformedPDFException, PdfminerException, ValueError, TypeError, OSError):
        raise StatementFormatError("Не удалось прочитать PDF; проверьте, что файл не повреждён и не защищён паролем") from None


def _read_tables(text: str, tables: list) -> BankStatement:
    if "Account statement" not in text:
        raise StatementFormatError("Не найден заголовок текстовой PDF-выписки Account statement; используйте TXT или CSV")
    accounts = set(re.findall(r"Account number:\s*(\d{20})", text))
    if len(accounts) != 1 or not re.search(r"Account currency:\s*(810|643)\b", text):
        raise StatementFormatError("В PDF должен быть один рублёвый счёт")
    account = account_number(accounts.pop())
    period = re.search(r"for the period from\s*(" + _DATE + r").*?till\s*(" + _DATE + ")", text)
    single = re.search(r"as of\s*(" + _DATE + ")", text)
    if not period and not single:
        raise StatementFormatError("Не удалось определить период PDF-выписки")
    start, end = (bank_date(period[1]), bank_date(period[2])) if period else (bank_date(single[1]), bank_date(single[1]))
    operations, opening, closing, incoming, outgoing, counts = [], None, None, None, None, None
    for table in tables:
        current = None
        for row in table:
            cells = [cell or "" for cell in row]
            if len(cells) != 11:
                continue
            joined = " ".join(cells)
            if "Opening Balance:" in joined:
                value = re.search(r"Opening Balance:\s*([\d\s.,-]+)\s*\(([^)]+)\)", joined)
                if value:
                    opening = money(value[1]) * (-1 if "Dr" in value[2] or "Дб" in value[2] else 1)
                current = None
            elif "Operations quantity" in joined:
                counts = (int(cells[8]), int(cells[9]))
                current = None
            elif "Turnover" in joined:
                outgoing, incoming = money(cells[8]), money(cells[9])
                current = None
            elif "Closing" in joined:
                closing = money(cells[9] or cells[8])
                current = None
            elif "Available" in joined or "Posting" in joined or cells[:5] == ["1", "2", "3", "4", "5"]:
                current = None
            elif cells[0].isdigit() and re.fullmatch(_DATE, cells[1]):
                current = cells
                operations.append(current)
            elif current is not None:
                for index, cell in enumerate(cells):
                    if cell.strip():
                        current[index] += "\n" + cell
    if any(value is None for value in (opening, closing, incoming, outgoing, counts)):
        raise StatementFormatError("В PDF не найдены контрольные остатки, обороты или количество операций")
    payments = []
    for row in operations:
        debit, credit = money(row[8]) if row[8] else 0, money(row[9]) if row[9] else 0
        if bool(debit) == bool(credit):
            raise StatementFormatError("Не удалось определить направление платежа в PDF")
        direction = "out" if debit else "in"
        purpose, name = " ".join(row[10].split()), " ".join(row[5].split())
        # В графе корреспондента СБП бывает банк; фактический плательщик указан в назначении.
        party = "Получатель" if direction == "out" else "Плательщик"
        party_match = re.search(party + r"[:\s]+(.+?)(?=,?\s*ИНН|\.\s|$)", purpose)
        if party_match:
            name = party_match[1].strip(" ,.")
        tax = re.search(r"ИНН\s*:?\s*(\d{10,12})(?!\d)", purpose) or re.search(r"ИНН\s*:?\s*(\d{10,12})(?!\d)", name)
        payments.append(BankPayment(bank_date(row[1]), "".join(row[4].split()), debit or credit, direction,
                                    name, inn(tax[1]) if tax else "", "".join(row[6].split()), purpose))
    if counts != (sum(p.direction == "out" for p in payments), sum(p.direction == "in" for p in payments)):
        raise StatementFormatError("Не все платежи PDF распознаны: количество операций не совпало")
    client = re.search(r"Client:\s*(.*?)(?:ИНН|\n)", text)
    return BankStatement(account, client[1].strip() if client else "", payments,
                         [BalancePeriod(start, end, opening, closing, incoming, outgoing)])
