"""Правила документов операции, без HTTP и хранения."""
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 10
MEDIA_TYPES = {
    '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.heic': 'image/heic', '.txt': 'text/plain', '.csv': 'text/csv',
    '.xml': 'application/xml', '.doc': 'application/msword', '.xls': 'application/vnd.ms-excel',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.odt': 'application/vnd.oasis.opendocument.text', '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
}
PREVIEW_TYPES = frozenset({'application/pdf', 'image/png', 'image/jpeg', 'image/webp'})


class AttachmentError(ValueError):
    pass


@dataclass(frozen=True)
class Document:
    filename: str
    content_type: str
    content: bytes


def document(filename: str, content: bytes) -> Document:
    name = filename.replace('\\', '/').rsplit('/', 1)[-1].strip()
    if not name or len(name) > 255 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise AttachmentError('Некорректное имя файла')
    extension = PurePosixPath(name).suffix.lower()
    if extension not in MEDIA_TYPES:
        raise AttachmentError('Этот формат вложения не поддерживается')
    if not content:
        raise AttachmentError('Нельзя прикрепить пустой файл')
    if len(content) > MAX_FILE_BYTES:
        raise AttachmentError('Размер одного файла не должен превышать 10 МБ')
    signatures = {
        '.pdf': content.lstrip().startswith(b'%PDF-'),
        '.png': content.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg': content.startswith(b'\xff\xd8\xff'), '.jpeg': content.startswith(b'\xff\xd8\xff'),
        '.webp': content.startswith(b'RIFF') and content[8:12] == b'WEBP',
    }
    if extension in signatures and not signatures[extension]:
        raise AttachmentError('Содержимое файла не соответствует его формату')
    return Document(name, MEDIA_TYPES[extension], content)
