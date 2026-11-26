"""Project chapter text with the allowance configured for this edition."""

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from app.books.models import Book


def book_allows_text(book: Book, *, admin: bool) -> bool:
    return admin or book.rights_status == 'public_domain' or book.allowed_text_percent != 0


def book_allows_learner_text() -> ColumnElement[bool]:
    return or_(Book.rights_status == 'public_domain', Book.allowed_text_percent.is_(None), Book.allowed_text_percent > 0)


def visible_chapter_text(book: Book, text: str, *, admin: bool = False) -> tuple[str, bool]:
    if admin or book.rights_status == 'public_domain' or not text:
        return text, False
    percent = book.allowed_text_percent
    if percent is None or percent >= 100:
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
