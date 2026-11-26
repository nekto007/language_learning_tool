"""Project chapter text with the allowance configured for this edition."""

from hashlib import sha256

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from app.books.models import Book


def _effective_text_percent(book: Book, *, admin: bool) -> int:
    if admin or book.rights_status == 'public_domain' or book.allowed_text_percent is None:
        return 100
    return book.allowed_text_percent


def book_allows_text(book: Book, *, admin: bool) -> bool:
    return _effective_text_percent(book, admin=admin) != 0


def book_allows_learner_text() -> ColumnElement[bool]:
    return or_(Book.rights_status == 'public_domain', Book.allowed_text_percent.is_(None), Book.allowed_text_percent > 0)


def visible_chapter_text(book: Book, text: str, *, admin: bool = False) -> tuple[str, bool]:
    return _clip_chapter_text(text, _effective_text_percent(book, admin=admin))


def chapter_text_with_access(
    book: Book, text: str, *, admin: bool = False,
) -> tuple[str, bool, dict[str, int | str]]:
    percent = _effective_text_percent(book, admin=admin)
    visible, truncated = _clip_chapter_text(text, percent)
    return visible, truncated, {
        'book_id': book.id,
        'policy_revision': str(book.text_policy_revision),
        'effective_percent': percent,
        'projection': 'admin' if admin else 'reader',
    }


def chapter_text_revision(text: str, access: dict[str, int | str]) -> str:
    """Opaque equality token for the visible text and its access mode."""
    mode = f"{access['projection']}:{access['effective_percent']}"
    digest = sha256(f'chapter-text-v1:{mode}\0'.encode('ascii'))
    digest.update(text.encode('utf-8'))
    return f'v1:{digest.hexdigest()}'


def _clip_chapter_text(text: str, percent: int) -> tuple[str, bool]:
    if not text or percent >= 100:
        return text, False
    cut = len(text) * max(0, percent) // 100
    if cut == 0:
        return '', True
    excerpt = text[:cut]
    boundary = max(excerpt.rfind('\n\n'), excerpt.rfind('\\n\\n'))
    if boundary <= cut / 2:
        boundary = excerpt.rfind(' ')
        if boundary <= 0:
            boundary = cut
    return excerpt[:boundary], True
