"""Signed previews for the editorial metadata of one book edition."""
from collections.abc import Mapping
from hashlib import file_digest, sha256
from json import dumps
from pathlib import Path
from urllib.parse import urlsplit

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.admin.services.book_processing_service import ALLOWED_BOOK_EXTENSIONS, MAX_BOOK_UPLOAD_BYTES
from app.books.models import Book

PASSPORT_FIELDS = ('source_edition_id', 'source_format', 'source_url', 'permission_document')
PASSPORT_FORMATS = ('epub', 'fb2', 'txt', 'docx', 'pdf', 'text')
_BOOK_FORM_FIELDS = (
    'title', 'author', 'level', 'description', 'rights_status', 'audio_rights_status', 'license_type',
    'allowed_text_percent', 'territory', 'expiration_date', 'commercial_use_allowed',
)
_BOOK_REVISION_FIELDS = (
    *PASSPORT_FIELDS, 'title', 'author', 'level', 'summary', 'is_published', 'rights_status',
    'audio_rights_status', 'license_type', 'allowed_text_percent', 'territory', 'expiration_date',
    'commercial_use_allowed', 'text_policy_revision',
)


def _digest(value: object) -> str:
    return sha256(dumps(value, default=str, ensure_ascii=False).encode()).hexdigest()


def passport_revision(book: Book | None) -> str:
    return _digest([getattr(book, field) for field in _BOOK_REVISION_FIELDS]) if book is not None else ''


def has_passport_form(form: Mapping[str, str]) -> bool:
    return any(key in form for key in ('passport_revision', 'passport_token', *PASSPORT_FIELDS[:2]))


def passport_changed(book: Book | None, form: Mapping[str, str]) -> bool:
    return any(field in form and (form[field].strip() or None) != getattr(book, field, None)
               for field in PASSPORT_FIELDS)


def _source_file(file: FileStorage | None, text: str) -> tuple[str | None, str]:
    if file is None or not file.filename:
        return ('text', _digest(text)) if text.strip() else (None, '')
    extension = Path(secure_filename(file.filename)).suffix.lower().removeprefix('.')
    if extension not in ALLOWED_BOOK_EXTENSIONS:
        raise ValueError('Проверьте расширение файла книги.')
    stream = file.stream
    start = stream.tell()
    try:
        size = stream.seek(0, 2)
        if not 0 < size <= MAX_BOOK_UPLOAD_BYTES:
            raise ValueError('Выберите непустой файл книги размером до 50 МБ.')
        stream.seek(0)
        return extension, file_digest(stream, 'sha256').hexdigest()
    finally:
        stream.seek(start)


def passport_draft(
    book: Book | None, form: Mapping[str, str], file: FileStorage | None,
) -> tuple[dict[str, str | None], str]:
    values = {field: (form[field].strip() or None) if field in form else getattr(book, field, None)
              for field in PASSPORT_FIELDS}
    file_hash = ''
    if book is None:
        values['source_format'], file_hash = _source_file(file, form.get('content', ''))
        if not values['source_format']:
            raise ValueError('Загрузите файл или введите текст книги.')
    for field, limit in (('source_edition_id', 255), ('source_url', 2000), ('permission_document', 4000)):
        value = values[field]
        if value and (len(value) > limit or '\x00' in value):
            raise ValueError('Проверьте длину и символы в полях паспорта издания.')
    if values['source_format'] and values['source_format'] not in PASSPORT_FORMATS:
        raise ValueError('Выберите поддерживаемый формат источника.')
    url = values['source_url']
    if url and url != getattr(book, 'source_url', None):
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
                    or any(char.isspace() or ord(char) < 32 for char in url)):
                raise ValueError
        except ValueError as error:
            raise ValueError('Укажите действительный HTTP(S) адрес источника.') from error
    return values, _digest([values, file_hash, [form.get(field) for field in _BOOK_FORM_FIELDS]])


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt='admin-book-passport')


def passport_token(user_id: int, book: Book | None, digest: str) -> str:
    return _signer().dumps([user_id, book.id if book else None, passport_revision(book), digest])


def confirm_passport(token: str, user_id: int, book: Book | None, digest: str) -> None:
    expected = [user_id, book.id if book else None, passport_revision(book), digest]
    if not token or len(token) > 1024 or _signer().loads(token, max_age=1800) != expected:
        raise BadSignature('stale book passport')
