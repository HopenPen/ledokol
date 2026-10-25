"""Выбор адаптера; приложение получает одинаковые строки независимо от формата файла."""
from dataclasses import dataclass, field
from pathlib import PurePath

import pandas as pd

from app.domain.ingest import StatementFormatError, normalize, read_statement
from app.importers.client_bank import parse_client_bank


@dataclass
class ParsedImport:
    frame: pd.DataFrame
    accounts: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)


def parse_statement(raw: bytes, filename: str = "statement.csv") -> ParsedImport:
    extension = PurePath(filename).suffix.lower()
    if raw.startswith(b"%PDF-"):
        from app.importers.raiffeisen_pdf import parse_pdf
        statements = parse_pdf(raw)
    elif raw.lstrip(b"\xef\xbb\xbf \r\n").startswith(b"1CClientBankExchange"):
        statements = parse_client_bank(raw)
    elif extension in {".csv", ""}:
        frame = read_statement(raw)
        if frame.empty:
            raise StatementFormatError("В файле нет подходящих платежей")
        return ParsedImport(frame)
    else:
        raise StatementFormatError("Поддерживаются CSV, TXT 1CClientBankExchange и текстовые PDF-выписки совместимого формата")
    rows = [row for statement in statements for row in statement.operation_rows()]
    if not rows:
        raise StatementFormatError("В выписке нет платежей")
    return ParsedImport(normalize(pd.DataFrame(rows)),
                        {"bank:" + s.account: s.account for s in statements},
                        {"bank:" + s.account: s.name for s in statements})
