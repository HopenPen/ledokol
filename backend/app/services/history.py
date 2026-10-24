"""Обновление категорий, качества и план-факта при поступлении фактических платежей."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, PlannedEvent
from app.domain.pipeline import prepare_company
from app.domain.planfact import match_events
from app.services.classifier import get_classifier
from app.services.company_data import load_operations_frame
from app.services.events_mapping import to_domain_event


def refresh_history(session: Session, company: Company):
    frame, rows = load_operations_frame(session, company, with_rows=True)
    prep = prepare_company(frame, get_classifier())
    by_source = prep.ops.set_index("operation_id")
    for op in rows:
        lab = by_source.loc[op.source_operation_id]
        op.quality = lab["quality"]
        if op.category_source != "user":
            op.category, op.category_source, op.confidence = lab["category"], lab["category_source"], float(lab["confidence"])
    as_of = prep.panel["date"].iloc[-1].date()
    due = list(session.scalars(select(PlannedEvent).where(
        PlannedEvent.company_id == company.id, PlannedEvent.status.in_(["expected", "missed"]),
        PlannedEvent.event_date <= as_of)))
    by_id = {e.id: e for e in due}
    for match in match_events([to_domain_event(e) for e in due], prep.ops, as_of):
        if match.status != "pending":
            by_id[match.event.ref].status = match.status
    return prep.quality
