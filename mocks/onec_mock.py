"""Имитатор 1С (OData «standard.odata»): неоплаченные счета на дату as_of.

Откуда счета: из самой выписки. В назначениях B2B-оплат есть «по счету № N от ДД.ММ.ГГГГ» (EDA: так
восстанавливается дебиторка). Счёт, выставленный до as_of и оплаченный после, — это ровно то, что бухгалтер
видел бы в 1С как «выставлен, не оплачен». Так демо честное: модель не знает будущего, а 1С знает только
то, что знала бы в реальности.

Поведение как у настоящей интеграции: токен в заголовке, постраничная выдача, задержки, иногда 429 и 503.
Запуск: MOCK_DATA_DIR=../data/statements MOCK_TOKEN=... uvicorn onec_mock:app --port 8101
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query, Request

app = FastAPI(title="1С mock")
DATA_DIR = Path(os.environ.get("MOCK_DATA_DIR", "data/statements"))
TOKEN = os.environ.get("MOCK_TOKEN", "")
FAIL_EVERY = int(os.environ.get("MOCK_FAIL_EVERY", "7"))       # каждый N-й запрос — 503
DOC_RX = re.compile(r"(?:сч[её]т[ау]?|УПД)\s*№\s*([\w/-]+)\s*от\s*(\d{2}\.\d{2}\.\d{4})", re.I)
_counter = {"n": 0}


@lru_cache(maxsize=32)
def _invoices(company: str) -> pd.DataFrame:
    path = DATA_DIR / f"{company}.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    m = df["payment_purpose"].str.extract(DOC_RX)
    df = df.assign(number=m[0], issued=pd.to_datetime(m[1], format="%d.%m.%Y", errors="coerce"),
                   paid=pd.to_datetime(df["operation_date"]), amount=pd.to_numeric(df["amount"]))
    df = df[df["issued"].notna()]
    # Частичные оплаты одного счёта складываем: в 1С это один документ.
    return (df.groupby(["direction", "counterparty_inn", "counterparty_name", "number", "issued"], as_index=False)
              .agg(amount=("amount", "sum"), paid=("paid", "max")))


def _auth_and_chaos(authorization: str | None) -> None:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "unauthorized")
    _counter["n"] += 1
    time.sleep(random.uniform(0.05, 0.3))
    if FAIL_EVERY and _counter["n"] % FAIL_EVERY == 0:
        raise HTTPException(503, "1C is busy")
    if _counter["n"] % 13 == 0:
        raise HTTPException(429, "rate limited", headers={"Retry-After": "1"})


@app.get("/odata/standard.odata/{doc}")
def list_docs(doc: str, request: Request, company: str, as_of: date, top: int = Query(100, alias="$top", le=500),
              skip: int = Query(0, alias="$skip", ge=0), authorization: str | None = Header(default=None)) -> dict:
    _auth_and_chaos(authorization)
    direction = {"Document_СчетНаОплатуПокупателю": "Поступление", "Document_СчетНаОплатуПоставщика": "Списание"}.get(doc)
    if direction is None:
        raise HTTPException(404, "unknown document")
    inv = _invoices(company)
    if inv.empty:
        return {"value": []}
    cut = pd.Timestamp(as_of)
    open_ = inv[(inv["direction"] == direction) & (inv["issued"] <= cut) & (inv["paid"] > cut)].sort_values("issued")
    page = open_.iloc[skip: skip + top]
    value = [{
        "Ref_Key": hashlib.md5(f"{company}|{r.number}|{r.issued:%Y-%m-%d}|{r.counterparty_inn}".encode()).hexdigest(),
        "Номер": r.number, "Дата": f"{r.issued:%Y-%m-%d}T00:00:00",
        "СрокОплаты": f"{(r.issued + timedelta(days=14)):%Y-%m-%d}T00:00:00",   # типовая отсрочка по договору
        "СуммаДокумента": round(float(r.amount), 2), "Оплачен": False,
        "Контрагент": {"ИНН": r.counterparty_inn, "Наименование": r.counterparty_name},
    } for r in page.itertuples()]
    out: dict = {"value": value}
    if skip + top < len(open_):
        out["odata.nextLink"] = (f"{request.url.path}?company={company}&as_of={as_of}&$top={top}&$skip={skip + top}")
    return out
