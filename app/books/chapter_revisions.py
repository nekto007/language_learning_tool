"""Read confirmed chapter revisions without selecting bodies on a cache hit."""

from itertools import batched

from sqlalchemy import and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import Select

from app.books.models import Book, Chapter, chapter_text_revision_cache as cache
from app.books.text_access import chapter_text_revision, chapter_text_with_access, visible_chapter_text
from app.utils.db import db

_BATCH_SIZE = 512
_GENERATION = Chapter.text_generation.label('generation')


class ChapterRevisionRace(RuntimeError):
    """Chapter text changed while missing revisions were being resolved."""


def chapter_toc_query(book_id: int) -> Select:
    return db.select(
        Chapter.id, Chapter.chap_num.label('num'), Chapter.title, Chapter.words, Chapter.audio_url,
    ).where(Chapter.book_id == book_id).order_by(Chapter.chap_num)


def confirmed_chapter_revisions(book: Book, *, admin: bool) -> list[dict]:
    """Project one TOC for the policy held stable by the caller's book lock."""
    _, _, access = chapter_text_with_access(book, '', admin=admin)
    if access['effective_percent'] == 0:
        revision = chapter_text_revision('', access)
        rows = db.session.execute(chapter_toc_query(book.id)).mappings()
        return [dict(row, text_revision=revision) for row in rows]

    for _ in range(2):
        payload = _read_confirmed(book, admin=admin, access=access)
        if payload is not None:
            return payload
    raise ChapterRevisionRace()


def _read_confirmed(book: Book, *, admin: bool, access: dict[str, int | str]) -> list[dict] | None:
    mode = {'effective_percent': access['effective_percent'], 'projection': access['projection']}
    lookup = chapter_toc_query(book.id).add_columns(_GENERATION, cache.c.revision).outerjoin(
        cache, and_(cache.c.chapter_id == Chapter.id, cache.c.generation == _GENERATION,
                    cache.c.effective_percent == mode['effective_percent'], cache.c.projection == mode['projection']),
    )
    metadata = [dict(row) for row in db.session.execute(lookup).mappings()]
    missing = {row['id']: row['generation'] for row in metadata if row['revision'] is None}
    fresh = {}
    if missing:
        fresh = _read_missing(book, admin=admin, access=access, missing=missing)
        if fresh is None:
            return None
        _store_confirmed(fresh, missing, mode)

    for row in metadata:
        row.pop('generation')
        row['text_revision'] = row.pop('revision') or fresh[row['id']]
    return metadata


def _read_missing(
    book: Book, *, admin: bool, access: dict[str, int | str], missing: dict[int, int],
) -> dict[int, str] | None:
    # Key-share prevents deletion between reading a body and inserting its FK.
    # Text-only writers can still run. Match their committed generation against the TOC snapshot.
    bodies = db.select(Chapter.id, _GENERATION, Chapter.text_raw).where(
        Chapter.book_id == book.id,
    ).order_by(Chapter.id).with_for_update(read=True, key_share=True).execution_options(yield_per=16)
    fresh = {}
    for ids in batched(sorted(missing), _BATCH_SIZE, strict=False):
        rows = db.session.execute(bodies.where(Chapter.id.in_(ids)))
        try:
            for chapter_id, generation, text in rows:
                if missing[chapter_id] != generation:
                    return None
                shown, _ = visible_chapter_text(book, text, admin=admin)
                fresh[chapter_id] = chapter_text_revision(shown, access)
        finally:
            rows.close()
    return fresh if fresh.keys() == missing.keys() else None


def _store_confirmed(
    fresh: dict[int, str], generations: dict[int, int], mode: dict[str, int | str],
) -> None:
    # Concurrent fills lock rows in the same order. A late fill cannot replace a newer generation.
    for ids in batched(sorted(fresh), _BATCH_SIZE, strict=False):
        statement = insert(cache).values([
            dict(mode, chapter_id=key, revision=fresh[key], generation=generations[key]) for key in ids
        ])
        db.session.execute(statement.on_conflict_do_update(
            index_elements=[cache.c.chapter_id, cache.c.effective_percent, cache.c.projection],
            set_={'generation': statement.excluded.generation, 'revision': statement.excluded.revision},
            where=cache.c.generation < statement.excluded.generation,
        ))
    db.session.commit()
