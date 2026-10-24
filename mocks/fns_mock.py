"""Имитатор реестров ФНС (ЕГРЮЛ/ЕГРИП + сведения о задолженности) по ИНН.

Статус детерминирован от ИНН (одинаковый при каждом запросе): ~4% контрагентов «в ликвидации», ~6% — с долгом
перед бюджетом. Этого хватает, чтобы на демо показать, как риск контрагента снижает вероятность оплаты счёта.
Запуск: MOCK_TOKEN=... uvicorn fns_mock:app --port 8102
"""
from __future__ import annotations

import hashlib
import os
import random
import time

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="ФНС mock")
TOKEN = os.environ.get("MOCK_TOKEN", "")


@app.get("/api/v1/egr/{inn}")
def egr(inn: str, authorization: str | None = Header(default=None)) -> dict:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "unauthorized")
    if not inn.isdigit() or len(inn) not in (10, 12):
        raise HTTPException(400, "bad inn")
    time.sleep(random.uniform(0.02, 0.15))
    h = int(hashlib.sha256(inn.encode()).hexdigest(), 16) % 100
    status = "liquidating" if h < 4 else "active"
    return {"inn": inn, "status": status, "tax_debt": 4 <= h < 10,
            "kind": "ЮЛ" if len(inn) == 10 else "ИП", "source": "mock-egr"}
