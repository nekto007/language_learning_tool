"""Vocab-pull: extract unlearned words from a read chapter slice and queue them
as SRS cards scheduled for tomorrow.

Called from ``reading_session_end`` on the ``daily_target_met`` transition
(False → True).  Best-effort: caller wraps in try/except so errors never block
the response.
"""
from __future__ import annotations

import re
from typing import Any

from app.srs.constants import DEFAULT_EASE_FACTOR
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

_WORD_RE = re.compile(r'\b[a-z]{3,}\b')



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

    # NOTE (audit E-053): offset_pct is a RENDERED-scroll fraction, mapped here
    # directly onto raw-text character positions. These don't align exactly
    # (markup, images, font metrics), so the slice is an APPROXIMATION of the
    # read region — acceptable for vocab sampling, not an exact boundary. If
    # precise alignment is ever needed, store character progress separately.
    text = chapter.text_raw
    start_char = int(start_offset * len(text))
    end_char = int(end_offset * len(text))
    if end_char <= start_char:
        return []
    text_slice = text[start_char:end_char]

    raw_tokens = _WORD_RE.findall(text_slice.lower())
    unique_tokens = list(dict.fromkeys(
        t for t in raw_tokens if t not in STOP_WORDS
    ))[:500]  # cap before IN() to avoid large query plans
    if not unique_tokens:
        return []

    # english_word is stored lowercase; direct match uses the B-tree index
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
        key=lambda w: (not w.frequency_rank, w.frequency_rank or 999999)
    )
    return unlearned[:count]


def pull_chapter_vocab_once(
    user_id: int,
    chapter_id: int,
    start_offset: float,
    end_offset: float,
    db_session: Any = db,
) -> int:
    """Idempotent daily vocab pull from a read slice. Flush only — caller commits.

    Writes the per-(user, local-date) ``vocab_pull`` StreakEvent marker ONLY
    after scanning a **non-degenerate** slice. A degenerate slice (``end <=
    start`` — e.g. a freshly-opened chapter scrolled to ~0 while today's reading
    target was met on a *different* chapter) must NOT consume the day's single
    pull, otherwise the actually-read chapter's words are lost until tomorrow.
    A non-degenerate slice that yields 0 cards means "all words already known"
    and correctly marks the day done.

    Returns the number of SRS cards queued (0 when already pulled today, the
    slice is degenerate, or all candidate words are already known).
    """
    from app.achievements.models import StreakEvent
    from app.utils.time_utils import get_user_local_date

    today_local = get_user_local_date(user_id, db_session)
    already = (
        db_session.session.query(StreakEvent)
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == 'vocab_pull',
            StreakEvent.event_date == today_local,
        )
        .first()
    )
    if already is not None:
        return 0
    if end_offset <= start_offset:
        # Degenerate slice — leave the day open for a later /end with real reading.
        return 0

    words = extract_chapter_vocab(chapter_id, start_offset, end_offset, user_id, db_session)
    queued = queue_vocab_as_srs(words, user_id, db_session)
    db_session.session.add(StreakEvent(
        user_id=user_id,
        event_type='vocab_pull',
        event_date=today_local,
        details={'chapter_id': chapter_id, 'queued_count': queued},
    ))
    db_session.session.flush()
    return queued


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

    from app.utils.time_utils import get_user_local_day_bounds
    tomorrow = get_user_local_day_bounds(user_id, db_session)[1]
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
                ease_factor=DEFAULT_EASE_FACTOR,
                interval=0,
                repetitions=0,
                next_review=tomorrow,
            )
            db_session.session.add(card)
            created += 1

    db_session.session.flush()
    return created
