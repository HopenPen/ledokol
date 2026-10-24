"""Атомарное хранение документов в БД; содержимое не используется прогнозом и LLM."""
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Operation, OperationAttachment
from app.domain.attachments import MAX_FILES, AttachmentError, Document


class AttachmentConflict(Exception):
    pass


def list_attachments(session: Session, operation: Operation) -> list[OperationAttachment]:
    return list(session.scalars(select(OperationAttachment).where(OperationAttachment.operation_id == operation.id)
                               .order_by(OperationAttachment.created_at, OperationAttachment.id)))


def upload_attachments(session: Session, operation: Operation, kind: Literal['receipt', 'related'],
                       documents: list[Document]) -> list[OperationAttachment]:
    if not 1 <= len(documents) <= MAX_FILES or (kind == 'receipt' and len(documents) != 1):
        raise AttachmentError('Прикрепите один чек или до 10 сопутствующих файлов за раз')
    # Сериализуем замену чека на PostgreSQL. Уникальный индекс сохраняет инвариант и на SQLite.
    session.execute(select(Operation.id).where(Operation.id == operation.id).with_for_update())
    if kind == 'receipt':
        previous = session.scalar(select(OperationAttachment).where(
            OperationAttachment.operation_id == operation.id, OperationAttachment.kind == 'receipt'))
        if previous is not None:
            session.delete(previous)
            session.flush()
    session.add_all([OperationAttachment(operation_id=operation.id, kind=kind, filename=item.filename,
                                        content_type=item.content_type, size_bytes=len(item.content), content=item.content)
                     for item in documents])
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise AttachmentConflict('Документы уже изменились. Обновите список и повторите загрузку') from None
    return list_attachments(session, operation)


def delete_attachment(session: Session, attachment: OperationAttachment) -> None:
    session.delete(attachment)
    session.commit()
