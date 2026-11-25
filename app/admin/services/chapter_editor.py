"""Review and apply a chapter correction without replacing its identity."""
# ruff: noqa: RUF001 -- validation messages are shown in Russian.

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256

from bs4 import BeautifulSoup
from sqlalchemy import func, select

from app.books.models import Book, Bookmark, Chapter, UserChapterProgress
from app.books.reading_session import UserReadingSession
from app.nlp.processor import process_text
from app.nlp.setup import initialize_nltk
from app.utils.db import db
from app.utils.db_utils import chunk_ids
from app.utils.template_utils import format_chapter_text
from app.words.models import CollectionWords, word_book_link

_BLOCK = ('p', 'div', 'section', 'article', 'blockquote', 'li', 'ul', 'ol', 'pre', 'tr',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6')
_MARKUP = frozenset({'b', 'i', 'em', 'strong', 'u', 's', 'br', 'code', 'sub', 'sup', *_BLOCK})


@dataclass(frozen=True)
class ChapterPreview:
    changes: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    word_count: int
    text_changed: bool
    index: 'BookIndex | None' = None
    structure_changed: bool = False


@dataclass(frozen=True)
class BookIndex:
    words: int
    unique_words: int
    frequencies: dict[int, int]


def text_for_edit(text: str) -> str:
    """Older imports persisted literal newline escapes."""
    return text.replace('\\n', '\n').replace('\r\n', '\n').replace('\r', '\n')


def chapter_revision(title: str, text: str) -> str:
    return sha256((title + '\0' + text).encode()).hexdigest()


def _paragraphs(text: str, *, native: bool = False) -> tuple[str, ...]:
    if native:
        # Native readers also break on single newlines and block markup.
        markup = BeautifulSoup(text_for_edit(text), 'html.parser')
        for tag in markup.find_all(['br', *_BLOCK]):
            if tag.name == 'br':
                tag.replace_with('\n')
            else:
                tag.insert_before('\n')
                tag.insert_after('\n')
        return tuple(line for raw in markup.get_text().splitlines() if (line := ' '.join(raw.split())))
    markup = BeautifulSoup(str(format_chapter_text(text)), 'html.parser')
    return tuple(' '.join(paragraph.get_text().split()) for paragraph in markup.find_all('p'))


def _words(paragraphs: tuple[str, ...]) -> list[str]:
    return re.findall(r"\b[\w']+\b", ' '.join(paragraphs).replace('’', "'").casefold())


def _positions(paragraphs: tuple[str, ...], excerpt: str) -> tuple[int, ...]:
    return tuple(index for index, paragraph in enumerate(paragraphs) if excerpt in paragraph.casefold())


def _changes(before: tuple[str, ...], after: tuple[str, ...]) -> tuple:
    return tuple((before[i:j], after[k:m]) for action, i, j, k, m in
                 SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if action != 'equal')


def _indexed_changes(book: Book, before: tuple[str, ...], after: tuple[str, ...]) -> BookIndex | None:
    if before == after:
        return None
    if db.session.scalar(select(word_book_link.c.id).where(word_book_link.c.book_id == book.id).limit(1)) is None:
        return None
    vocabulary, brown, stop_words = initialize_nltk()
    if not vocabulary:
        raise ValueError('Локальный анализатор словаря книги недоступен. Текст с индексом пока сохранить нельзя.')
    old_text, new_text = ' '.join(before).casefold(), ' '.join(after).casefold()
    try:
        old_counts = Counter(process_text(old_text, vocabulary, stop_words, brown))
        counts = Counter(process_text(new_text, vocabulary, stop_words, brown))
    except LookupError as exc:
        raise ValueError('Локальный анализатор словаря книги недоступен. Текст с индексом пока сохранить нельзя.') from exc
    words_delta = sum(counts.values()) - sum(old_counts.values())
    lemmas = old_counts.keys() | counts.keys()
    # Phrasal links use literal occurrences, just as the original book index.
    heads = set(_words((*before, *after)))
    for name in db.session.scalars(select(CollectionWords.english_word).where(CollectionWords.item_type == 'phrasal_verb')):
        if not name or name.casefold().split()[0] not in heads:
            continue
        phrase = re.compile(r'\b' + re.escape(name.casefold()) + r'\b')
        old_counts[name] += sum(1 for _ in phrase.finditer(old_text))
        counts[name] += sum(1 for _ in phrase.finditer(new_text))
    affected = [word for word in old_counts.keys() | counts.keys() if old_counts[word] != counts[word]]
    frequencies = {}
    unique_delta = 0
    known = set()
    for batch in chunk_ids(affected):
        entries = select(CollectionWords.id, CollectionWords.english_word, word_book_link.c.frequency).outerjoin(
            word_book_link, (word_book_link.c.word_id == CollectionWords.id) & (word_book_link.c.book_id == book.id)
        ).where(CollectionWords.english_word.in_(batch))
        for word_id, name, existing in db.session.execute(entries):
            known.add(name)
            frequency = (existing or 0) + counts[name] - old_counts[name]
            if existing is None and frequency <= 0:
                continue
            if frequency < counts[name]:
                raise ValueError('Сохранённая частота слова расходится с текстом главы. Сначала сверяйте словарь книги.')
            frequencies[word_id] = frequency
            if name in lemmas:
                unique_delta += int(frequency > 0) - int(bool(existing))
    missing = sorted(name for name in set(affected) - known if counts[name] > old_counts[name])
    if missing:
        raise ValueError(f'Для индекса книги в словаре отсутствует: {", ".join(missing[:3])}. '
                         'Сначала добавьте слово с переводом или уточните правку.')
    return BookIndex(max(0, (book.words_total or 0) + words_delta),
                     max(0, (book.unique_words or 0) + unique_delta), frequencies)


def review_chapter(book: Book, chapter: Chapter, title: str, text: str) -> ChapterPreview:
    current_text = text_for_edit(chapter.text_raw)
    changed = text != current_text
    if not title.strip() or len(title) > 255 or '\0' in title or '\n' in title or '\r' in title:
        raise ValueError('Введите название главы одной строкой, до 255 символов.')
    if not changed:
        return ChapterPreview((), chapter.words, False)
    if not text.strip() or '\0' in text or len(text.encode()) > 2_000_000:
        raise ValueError('Введите текст главы. Максимальный размер — 2 МБ.')
    if any(tag.name not in _MARKUP or tag.attrs for tag in BeautifulSoup(text, 'html.parser').find_all()):
        raise ValueError('Используйте обычный текст или простое выделение. HTML с атрибутами не поддерживается.')

    before, after = _paragraphs(current_text), _paragraphs(text)
    if not after or not any(after):
        raise ValueError('В главе должен остаться видимый текст.')
    old_words, words = _words(before), _words(after)
    if chapter.audio_url and old_words != words:
        raise ValueError('Правка меняет произносимые слова главы с аудио. Сначала требуется сверить дорожку.')
    if book.is_short_reading:
        raise ValueError('Текст короткого чтения связан с вопросами и словарём. Обновите его через исходный пакет.')

    changes = _changes(before, after)
    native_before, native_after = _paragraphs(current_text, native=True), _paragraphs(text, native=True)
    contexts = db.session.scalars(select(Bookmark.context).where(Bookmark.book_id == book.id)).all()
    for context in contexts:
        excerpt = ' '.join((context or '').casefold().split())
        if excerpt and any(
            (positions := _positions(old, excerpt)) and positions != _positions(new, excerpt)
            for old, new in ((before, after), (native_before, native_after))
        ):
            raise ValueError('Сохранённый контекст закладки исчезает или меняет абзац. Оставьте этот отрывок на месте.')
    # Legacy progress records do not carry a paragraph or device geometry.
    # Keep their ordinal anchors stable when accepting an in-place correction.
    structural = any(len(old) != len(new) for old, new in (*changes, *_changes(native_before, native_after)))
    if structural and (contexts or
                       UserChapterProgress.query.filter_by(chapter_id=chapter.id).first() or
                       UserReadingSession.query.filter_by(chapter_id=chapter.id).first()):
        raise ValueError('Правка добавляет, убирает или переставляет абзацы при сохранённой позиции чтения.')
    return ChapterPreview(changes, len(words), True, _indexed_changes(book, before, after), structural)


def apply_chapter(book: Book, chapter: Chapter, title: str, text: str, preview: ChapterPreview) -> None:
    chapter.title = title
    if not preview.text_changed:
        return
    old_words = set(_words(_paragraphs(chapter.text_raw)))
    new_words = set(_words(_paragraphs(text)))
    chapter.text_raw = text
    if preview.word_count != chapter.words:
        chapter.words = preview.word_count
        if preview.index is None:
            book.words_total = db.session.scalar(select(func.sum(Chapter.words)).where(Chapter.book_id == book.id))

    if preview.index:
        book.words_total = preview.index.words
        book.unique_words = preview.index.unique_words
        for word_id, frequency in preview.index.frequencies.items():
            link = word_book_link.delete().where(word_book_link.c.book_id == book.id, word_book_link.c.word_id == word_id)
            if frequency:
                updated = db.session.execute(word_book_link.update().where(
                    word_book_link.c.book_id == book.id, word_book_link.c.word_id == word_id
                ).values(frequency=frequency))
                if not updated.rowcount:
                    db.session.execute(word_book_link.insert().values(
                        book_id=book.id, word_id=word_id, frequency=frequency,
                    ))
            else:
                db.session.execute(link)
    elif old_words != new_words:
        indexed = db.session.scalar(select(word_book_link.c.word_id).where(word_book_link.c.book_id == book.id).limit(1))
        if indexed is None:
            words = set()
            for raw in db.session.scalars(select(Chapter.text_raw).where(Chapter.book_id == book.id)):
                words.update(_words(_paragraphs(raw)))
            book.unique_words = len(words)
    if chapter.ts_idx is not None and db.session.get_bind().dialect.name == 'postgresql':
        chapter.ts_idx = func.to_tsvector(' '.join(_paragraphs(text)))
