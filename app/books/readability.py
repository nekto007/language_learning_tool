"""Shared definition of a stored chapter that can be opened for reading."""

from sqlalchemy import exists, func
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.books.models import Chapter


def chapter_has_text() -> ColumnElement[bool]:
    text = Chapter.text_raw
    for separator in ('\\n', '\n', '\r', '\t', '\u00a0'):
        text = func.replace(text, separator, '')
    return func.trim(text) != ''


def book_has_text(book_id: int | InstrumentedAttribute) -> ColumnElement[bool]:
    return exists().where(Chapter.book_id == book_id, chapter_has_text())
