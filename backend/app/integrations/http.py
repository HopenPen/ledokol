"""Общий HTTP-клиент для интеграций: таймаут, повторы с экспоненциальной задержкой и джиттером.

Правила (как с настоящими 1С/ФНС):
- 429 → ждём Retry-After и повторяем; 5xx и обрыв соединения → повторяем (состояние неизвестно, запросы у нас
  только читающие, поэтому повтор безопасен);
- остальные 4xx → не повторяем, это наша ошибка;
- токен — только в заголовке, никогда в URL (URL попадает в логи прокси).
"""
from __future__ import annotations

import logging
import random
import time

import httpx

log = logging.getLogger("cashflow.integrations")


class IntegrationError(Exception):
    """Внешняя система недоступна или ответила ошибкой. Прогноз при этом строится по выписке."""


class ResilientClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 5.0, max_attempts: int = 4,
                 sleep=time.sleep, transport: httpx.BaseTransport | None = None) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)
        self._max_attempts, self._sleep = max_attempts, sleep

    def get_json(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = self._client.get(path, params=params)
            except httpx.TransportError:
                if attempt == self._max_attempts:
                    raise IntegrationError("connection_failed") from None
                self._backoff(attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self._max_attempts:
                    raise IntegrationError(f"http_{resp.status_code}")
                retry_after = resp.headers.get("Retry-After")
                self._backoff(attempt, float(retry_after) if retry_after and retry_after.isdigit() else None)
                continue
            if resp.status_code >= 400:
                raise IntegrationError(f"http_{resp.status_code}")
            return resp.json()
        raise IntegrationError("unreachable")

    def _backoff(self, attempt: int, retry_after: float | None = None) -> None:
        delay = retry_after if retry_after is not None else min(8.0, 0.25 * 2 ** (attempt - 1))
        delay *= random.uniform(0.8, 1.2)
        log.info("integration_retry", extra={"count": attempt})
        self._sleep(delay)

    def close(self) -> None:
        self._client.close()
