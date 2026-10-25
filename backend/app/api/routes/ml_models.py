"""Сравнение всех моделей по одной компании: гибрид, CatBoost, ансамбль, TabPFN."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession, OwnedCompany
from app.services.ml_models import compare_models

router = APIRouter(prefix="/companies/{company_id}", tags=["ml"])


@router.get("/models")
def models(company: OwnedCompany, session: DbSession) -> dict:
    try:
        return compare_models(session, company)
    except LookupError:
        raise HTTPException(404, "Нет операций: загрузите выписку.") from None
