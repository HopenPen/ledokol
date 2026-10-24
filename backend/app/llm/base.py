from __future__ import annotations

from typing import Protocol


class LLMUnavailable(Exception):
    """Провайдер не ответил / отказал. Вызывающий код показывает шаблонный текст."""


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, max_tokens: int = 1024) -> str: ...
