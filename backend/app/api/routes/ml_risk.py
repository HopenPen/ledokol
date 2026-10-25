"""ML-оценка риска кассового разрыва (TabPFN): отдельный необязательный эндпоинт."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DbSession, OwnedCompany
from app.services.ml_risk import MlUnavailable, ml_gap_risk

router = APIRouter(prefix="/companies/{company_id}", tags=["ml"])


class HorizonRisk(BaseModel):
    days: int
    probability: float                    # оценка вероятности разрыва в ближайшие `days` рабочих дней
    alert: bool | None                    # тревога при пороге, лучшем по F1 (баланс precision и recall)
    alert_high_recall: bool | None        # тревога при пороге «находить не меньше 80% разрывов»


class MlRiskOut(BaseModel):
    available: bool
    reason: str | None = None             # почему недоступно (если available = false)
    state: str | None = None              # ok | already_negative
    model: dict | None = None
    horizons: list[HorizonRisk] = []
    note: str = ("Оценка отдельной ML-моделью TabPFN. Она дополняет основной прогноз и не заменяет его. "
                 "Если отрасль компании не задана, качество оценки ниже.")


@router.get("/ml-risk", response_model=MlRiskOut)
def ml_risk(company: OwnedCompany, session: DbSession) -> MlRiskOut:
    try:
        data = ml_gap_risk(session, company)
    except MlUnavailable as exc:
        return MlRiskOut(available=False, reason=str(exc))
    except LookupError:
        return MlRiskOut(available=False, reason="Нет операций: загрузите выписку.")
    return MlRiskOut(available=True, **data)
