"""Validate reader selections and locate saved quotes across client layouts."""

from hashlib import sha256
import re
from typing import Any

from bs4 import BeautifulSoup

from app.books.access import can_user_access_book
from app.books.models import Book, Chapter
from app.books.text_access import visible_chapter_text
from app.utils.db import db
from app.utils.template_utils import format_chapter_text


def book_context_allowed(book: Book | None) -> bool:
    # This is the book-identity policy already used by native reader sync.
    return bool(book and book.is_published and (
        book.rights_status == 'public_domain' or (
            book.rights_status == 'licensed' and book.is_free_access and not book.license_is_expired
        )
    ))


def reader_source(book_id: int, chapter_num: int, user: Any) -> tuple[Book, str] | None:
    book = db.session.get(Book, book_id)
    if not book_context_allowed(book) or not can_user_access_book(user, book):
        return None
    chapter = Chapter.query.filter_by(book_id=book_id, chap_num=chapter_num).first()
    if chapter is None:
        return None
    visible, _ = visible_chapter_text(book, chapter.text_raw)
    return (book, visible) if visible else None


def plain_paragraphs(text: str) -> list[str]:
    html = BeautifulSoup(str(format_chapter_text(text)), 'html.parser')
    return [p.get_text() for p in html.find_all('p')]


def _normalized(value: str) -> str:
    return ' '.join(value.replace('’', "'").split()).casefold()


def _source_lines(text: str) -> list[tuple[int, str]]:
    """Map the common LF-based native positions to web paragraphs."""
    text = text.replace('\\n', '\n').replace('\r\n', '\n').replace('\r', '\n')
    groups = text.split('\n\n') if '\n\n' in text else [text]
    return [
        (index, line)
        for index, group in enumerate(group for group in groups if group.strip())
        for line in plain_paragraphs(group.replace('\n', '\n\n'))
        if line.strip()
    ]


def source_paragraph(text: str, web_index: int, start: int, web_paragraph: str) -> int:
    offset = 0
    target = len(_normalized(web_paragraph[:start]))
    lines = _source_lines(text)
    candidates = [(index, line) for index, (group, line) in enumerate(lines) if group == web_index]
    for index, line in candidates:
        offset += len(_normalized(line)) + 1
        if target < offset:
            return index
    return candidates[-1][0] if candidates else web_index


def selection_context(paragraph: str, start: int, end: int) -> str:
    left, right = 0, len(paragraph)
    for boundary in re.finditer(r"(?<=[.!?])[\"'”’)]*\s+", paragraph):
        if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|[A-Z]|e\.g|i\.e)\.$', paragraph[:boundary.start()]):
            continue
        if boundary.end() <= start:
            left = boundary.end()
        elif boundary.start() >= end:
            right = boundary.start()
            break
    if right - left > 1200:
        left = max(left, start - 500)
        right = min(right, left + 1200)
    return paragraph[left:right].strip()


def paragraph_digest(paragraph: str) -> str:
    return sha256(_normalized(paragraph).encode()).hexdigest()


def find_context_paragraph(
    text: str, sentence: str, source_index: int | None, web_digest: str | None,
) -> int | None:
    quote = _normalized(sentence)
    if not quote:
        return None
    candidates = [
        index for index, paragraph in enumerate(plain_paragraphs(text))
        if quote in _normalized(paragraph)
        and (web_digest is None or paragraph_digest(paragraph) == web_digest)
    ]
    if len(candidates) <= 1:
        return candidates[0] if candidates else None

    lines = _source_lines(text)
    if isinstance(source_index, int) and 0 <= source_index < len(lines):
        index, line = lines[source_index]
        if index in candidates and (web_digest is not None or quote in _normalized(line)):
            return index
    return None
