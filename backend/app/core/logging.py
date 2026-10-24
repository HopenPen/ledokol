"""Логи без чувствительных данных (NFR-S3): ИНН, ФИО, назначения, суммы с контрагентом и токены не пишем.

Защита в два слоя: (1) в логи передаём только id и коды событий; (2) фильтр-маскировщик на корневом логгере
вырезает всё, что похоже на ИНН/счёт/карту/токен, даже если кто-то ошибся в коде. Тест проверяет второй слой.
"""
from __future__ import annotations

import json
import logging
import re

_PATTERNS = [
    (re.compile(r"\b\d{20}\b"), "[ACCOUNT]"),             # расчётный счёт
    (re.compile(r"\b\d{16}\b"), "[CARD]"),
    (re.compile(r"\b\d{12}\b|\b\d{10}\b"), "[INN]"),
    (re.compile(r"(?i)bearer\s+[\w\-.~+/]+=*"), "Bearer [TOKEN]"),
    (re.compile(r"(?i)\b(sk-[\w\-]{10,}|eyJ[\w\-.]{10,})"), "[SECRET]"),   # API-ключи и JWT
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
]
_ALLOWED_EXTRA = {"company_id", "event", "status", "duration_ms", "path", "method", "request_id", "rows", "file",
                  "reason", "count", "provider", "version"}


def redact(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Сначала собираем итоговую строку (msg % args), потом маскируем её целиком. Если маскировать args
        # по отдельности, сломаются форматы вроде %d в сторонних библиотеках (httpx так логирует статус).
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg, record.args = redact(message), ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update({k: redact(str(v)) for k, v in record.__dict__.items() if k in _ALLOWED_EXTRA})
        if record.exc_info:
            payload["exc"] = record.exc_info[0].__name__ if record.exc_info[0] else None  # без текста исключения
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(isinstance(f, RedactingFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root.handlers = [handler]
    root.setLevel(level)
