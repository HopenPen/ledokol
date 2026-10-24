"""Провайдер для любого OpenAI-совместимого API (Chat Completions).

Подходит для OpenAI, YandexGPT / GigaChat через совместимый шлюз, локальной модели в контуре банка (vLLM,
Ollama) — меняются только CASHFLOW_LLM_BASE_URL, CASHFLOW_LLM_MODEL и ключ. Для боевого режима по 152-ФЗ
выбираем модель в контуре или с хранением в РФ; в любом случае сюда приходит только обезличенная сводка.
"""
from __future__ import annotations

import logging

from app.llm.base import LLMUnavailable

log = logging.getLogger("cashflow.llm")


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None, timeout: float = 30.0) -> None:
        import openai  # опциональная зависимость: pip install ".[llm]"

        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url or None, timeout=timeout, max_retries=2)
        self._model = model

    def complete(self, system: str, user: str, *, max_tokens: int = 1024) -> str:
        o = self._openai
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
            )
        except o.RateLimitError as exc:
            raise LLMUnavailable("rate_limited") from exc
        except o.APIStatusError as exc:
            raise LLMUnavailable(f"status_{exc.status_code}") from exc
        except o.APIConnectionError as exc:
            raise LLMUnavailable("connection") from exc
        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content or "").strip() if choice else ""
        if not text:
            raise LLMUnavailable("empty")
        log.info("llm_call", extra={"provider": self.name, "status": choice.finish_reason})
        return text
