"""Ассистент «спроси о своих деньгах» и объяснения предупреждений.

Если LLM выключен или упал — отвечаем шаблоном из домена. Ответ всегда помечен, откуда он: пользователь
должен понимать, что текст сгенерирован моделью, а цифры — из прогноза.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import get_settings
from app.domain.types import ForecastResult
from app.llm.base import LLMProvider, LLMUnavailable
from app.llm.privacy import build_context

SYSTEM_PROMPT = """Ты — помощник предпринимателя в банковском приложении. Объясняешь прогноз денег на счёте
простым языком, без финансовых терминов. Отвечай по-русски, коротко (до 5 предложений).

Опирайся только на JSON с прогнозом из сообщения пользователя: не придумывай суммы, даты и события,
которых там нет. Если данных не хватает для ответа — так и скажи и предложи, что добавить (например,
ожидаемую оплату от клиента через «Добавить событие»). Вероятности называй словами: «почти наверняка»,
«вероятно», «возможно». Суммы округляй до тысяч рублей."""


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    generated_by: str   # "template" | имя провайдера


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider | None:
    s = get_settings()
    if s.llm_provider == "openai" and s.llm_api_key:
        from app.llm.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(s.llm_api_key.get_secret_value(), s.llm_model, s.llm_base_url)
    return None


def ask(res: ForecastResult, question: str) -> Answer:
    provider = get_provider()
    if provider is not None:
        try:
            user = f"Прогноз (JSON):\n{build_context(res)}\n\nВопрос предпринимателя: {question.strip()[:500]}"
            return Answer(provider.complete(SYSTEM_PROMPT, user, max_tokens=600), provider.name)
        except LLMUnavailable:
            pass
    return Answer(_template_answer(res), "template")


def _template_answer(res: ForecastResult) -> str:
    parts = [res.headline + "."]
    for a in res.alerts[:2]:
        parts.append(a.explanation)
        if a.actions:
            parts.append("Что можно сделать: " + "; ".join(a.actions[:2]) + ".")
    return " ".join(parts)
