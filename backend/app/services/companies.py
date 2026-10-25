"""Удаление компании вместе с историей; связанные записи удаляются внешними ключами БД."""
from sqlalchemy.orm import Session

from app.db.models import Company
from app.services.balances import lock_company
from app.services.forecasting import forget_company_model


def delete_company(session: Session, company: Company) -> None:
    lock_company(session, company)
    session.delete(company)
    session.commit()
    forget_company_model(company.id)
