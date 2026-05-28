"""Vocab-pull: extract unlearned words from a read chapter slice and queue them
as SRS cards scheduled for tomorrow.

Called from ``reading_session_end`` on the ``daily_target_met`` transition
(False → True).  Best-effort: caller wraps in try/except so errors never block
the response.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.utils.db import db

STOP_WORDS: frozenset[str] = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'used', 'ought',
    'to', 'of', 'in', 'on', 'at', 'by', 'for', 'with', 'from', 'into',
    'through', 'about', 'after', 'before', 'and', 'or', 'but', 'not', 'if',
    'so', 'as', 'when', 'that', 'this', 'these', 'those', 'it', 'its',
    'he', 'she', 'they', 'we', 'you', 'i', 'my', 'your', 'his', 'her',
    'their', 'our', 'me', 'him', 'us', 'them', 'up', 'out', 'over', 'down',
    'than', 'then', 'what', 'which', 'who', 'whom', 'where', 'how', 'all',
    'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such',
    'no', 'nor', 'too', 'very', 'just', 'also', 'only', 'own', 'same',
})

_WORD_RE = re.compile(r'\b[a-zA-Z]{3,}\b')


def _tomorrow_naive_utc(user_id: int, db_session: Any) -> datetime:
    """Return tomorrow midnight in the user's local timezone as naive UTC."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore

    from app.daily_plan.linear.xp import _get_user_timezone
    from app.utils.time_utils import get_user_local_date

    today: date = get_user_local_date(user_id, db_session)
    tz_name = _get_user_timezone(user_id, db_session)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc

    tomorrow_local = datetime(today.year, today.month, today.day, tzinfo=tz) + timedelta(days=1)
    return tomorrow_local.astimezone(timezone.utc).replace(tzinfo=None)


def extract_chapter_vocab(
    chapter_id: int,
    start_offset: float,
    end_offset: float,
    user_id: int,
    db_session: Any = db,
    count: int = 3,
) -> list:
    """Return up to ``count`` unlearned CollectionWords from the read slice.

    The slice is defined by ``[start_offset, end_offset)`` as fractions of
    ``chapter.text_raw``.  Words are matched case-insensitively against
    ``CollectionWords.english_word``, stop-words are excluded, and already-known
    words (any existing ``UserWord`` row) are filtered out.  The remainder is
    sorted by ``frequency_rank ASC`` (lower rank = more frequent; NULL last)
    and trimmed to ``count``.
    """
    from app.books.models import Chapter
    from app.study.models import UserWord
    from app.words.models import CollectionWords

    chapter = db_session.session.get(Chapter, chapter_id)
    if chapter is None or not chapter.text_raw:
        return []

    text = chapter.text_raw
    start_char = int(start_offset * len(text))
    end_char = int(end_offset * len(text))
    if end_char <= start_char:
        end_char = len(text)
    text_slice = text[start_char:end_char]

    raw_tokens = _WORD_RE.findall(text_slice.lower())
    unique_tokens = list(dict.fromkeys(
        t for t in raw_tokens if t not in STOP_WORDS
    ))
    if not unique_tokens:
        return []

    found = (
        db_session.session.query(CollectionWords)
        .filter(CollectionWords.english_word.in_(unique_tokens))
        .all()
    )
    if not found:
        return []

    found_ids = [w.id for w in found]
    known_ids = {
        uw.word_id
        for uw in db_session.session.query(UserWord)
        .filter(UserWord.user_id == user_id, UserWord.word_id.in_(found_ids))
        .all()
    }

    unlearned = [w for w in found if w.id not in known_ids]
    unlearned.sort(
        key=lambda w: (w.frequency_rank is None, w.frequency_rank or 0)
    )
    return unlearned[:count]


def queue_vocab_as_srs(words: list, user_id: int, db_session: Any = db) -> int:
    """Create SRS cards for ``words`` scheduled for tomorrow.

    For each word: ensure a ``UserWord`` row exists, then for each direction
    (``eng-rus``, ``rus-eng``) create a ``UserCardDirection`` if absent with
    ``source='book_reading'`` and ``next_review`` set to tomorrow midnight
    (naive UTC).  Flush only — caller commits.

    Returns the number of new ``UserCardDirection`` rows created.
    """
    from app.study.models import UserCardDirection, UserWord

    if not words:
        return 0

    tomorrow = _tomorrow_naive_utc(user_id, db_session)
    created = 0

    for word in words:
        user_word = UserWord.get_or_create(user_id, word.id)

        for direction in ('eng-rus', 'rus-eng'):
            existing = (
                db_session.session.query(UserCardDirection)
                .filter_by(user_word_id=user_word.id, direction=direction)
                .first()
            )
            if existing is not None:
                continue

            card = UserCardDirection(
                user_word_id=user_word.id,
                direction=direction,
                source='book_reading',
                ease_factor=2.5,
                interval=0,
                repetitions=0,
                next_review=tomorrow,
            )
            db_session.session.add(card)
            created += 1

    db_session.session.flush()
    return created
