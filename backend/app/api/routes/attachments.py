"""HTTP-контракт документов операции: владение проверяется до обращения к данным."""
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import DbSession, OwnedAttachment, OwnedOperation
from app.api.schemas import AttachmentOut
from app.core.config import get_settings
from app.domain.attachments import MAX_FILE_BYTES, MAX_FILES, AttachmentError, document
from app.services.attachments import (
    AttachmentConflict,
    delete_attachment,
    list_attachments,
    upload_attachments,
)

router = APIRouter(tags=['attachments'])


@router.get('/operations/{operation_id}/attachments', response_model=list[AttachmentOut])
def list_documents(operation: OwnedOperation, session: DbSession):
    return list_attachments(session, operation)


@router.post('/operations/{operation_id}/attachments', response_model=list[AttachmentOut], status_code=201)
async def upload_documents(operation: OwnedOperation, session: DbSession,
                           kind: Annotated[Literal['receipt', 'related'], Form()],
                           files: Annotated[list[UploadFile], File()]):
    if not 1 <= len(files) <= MAX_FILES or (kind == 'receipt' and len(files) != 1):
        raise HTTPException(422, 'Прикрепите один чек или до 10 сопутствующих файлов за раз')
    documents = []
    total = 0
    try:
        for file in files:
            raw = await file.read(MAX_FILE_BYTES + 1)
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or total > get_settings().max_upload_mb * 1024 * 1024:
                raise HTTPException(413, 'Превышен размер файла (10 МБ) или общий размер загрузки')
            documents.append(document(file.filename or '', raw))
        return await run_in_threadpool(upload_attachments, session, operation, kind, documents)
    except AttachmentError as exc:
        raise HTTPException(422, str(exc)) from None
    except AttachmentConflict as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        for file in files:
            await file.close()


@router.get('/attachments/{attachment_id}/file')
def read_document(attachment: OwnedAttachment, inline: bool = False) -> Response:
    if inline and not attachment.previewable:
        raise HTTPException(415, 'Этот файл можно только скачать')
    disposition = 'inline' if inline else 'attachment'
    return Response(attachment.content, media_type=attachment.content_type, headers={
        'Content-Disposition': f"{disposition}; filename*=UTF-8''{quote(attachment.filename, safe='')}",
        'Cache-Control': 'no-store',
    })


@router.delete('/attachments/{attachment_id}', status_code=204)
def remove_document(attachment: OwnedAttachment, session: DbSession) -> Response:
    delete_attachment(session, attachment)
    return Response(status_code=204)
