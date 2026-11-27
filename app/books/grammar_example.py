"""Resolve the one configured Grammar Lab example in the visible book text."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import JSONDecodeError, loads
from typing import TYPE_CHECKING, Any

from flask import current_app, url_for

from app.books.models import Book
from app.books.reader_vocabulary import find_context_paragraph, reader_source

if TYPE_CHECKING:
    from app.grammar_lab.models import GrammarTopic


@dataclass(frozen=True)
class GrammarBookExample:
    topic: GrammarTopic
    book: Book
    chapter: int
    paragraph: int
    revision: str

    def reader_link(self, back: str) -> str:
        return url_for(
            'books.read_book_chapters', book_id=self.book.id, chapter=self.chapter,
            reader_paragraph=self.paragraph, reader_revision=self.revision,
            grammar_example=self.topic.slug, **{'from': back},
        )


def grammar_book_example(
    user: Any, *, topic_slug: str | None = None, book: Book | None = None, chapter: int | None = None,
) -> GrammarBookExample | None:
    setting = current_app.config.get('GRAMMAR_BOOK_EXAMPLE')
    if not isinstance(setting, str) or not setting or not user.is_authenticated:
        return None
    try:
        pair = loads(setting)
    except JSONDecodeError:
        return None
    if not isinstance(pair, dict):
        return None
    topic_key, book_key, number, quote = (pair.get(key) for key in ('topic', 'book', 'chapter', 'quote'))
    if (not all(isinstance(value, str) and value.strip() for value in (topic_key, book_key, quote))
            or len(quote) > 500 or type(number) is not int or number < 1):
        return None
    if ((topic_slug is not None and topic_slug != topic_key)
            or (book is not None and (book.slug != book_key or chapter != number))):
        return None
    book = book if book is not None else Book.query.filter_by(slug=book_key).first()
    if book is None or book.is_short_reading or (source := reader_source(book.id, number, user)) is None:
        return None
    _, text = source
    paragraph = find_context_paragraph(text, quote, None, None)
    if paragraph is None:
        return None
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.grammar_lab.models import GrammarTopic

    topic = GrammarTopic.query.filter_by(slug=topic_key).first()
    if topic is None or topic.level not in PUBLIC_CEFR_CODES:
        return None
    return GrammarBookExample(topic, book, number, paragraph, sha256(text.encode()).hexdigest())
