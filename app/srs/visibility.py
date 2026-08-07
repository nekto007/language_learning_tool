"""Single source of truth for "may this card be served to the user?".

Two flags decide whether a card may appear in front of the learner:

* ``UserWord.srs_excluded`` — the learner asked never to study this word again
  ("Не учить это слово"). Permanent until explicitly reversed.
* ``UserCardDirection.buried_until`` — the card is resting: either the
  multi-day automatic rest for a word that will not stick (see
  ``app/srs/scheduling.py``) or the short intra-session bury.

Both rules used to be hand-inlined in every query that serves or counts cards,
and roughly half of those queries knew only one of them — so an excluded word
still turned up in the games and a resting card was still counted in the
navbar badge. Everything now composes the expressions below instead.

The two halves stay separate on purpose. Surfaces that exist *to show* resting
cards (the difficult-words list, the resting-word counter) take
:func:`srs_scope_filter` alone, so ``srs_excluded`` still lives in one place
even there.

Time basis: ``buried_until`` is naive UTC, like every other SRS datetime
column (see ``app/srs/counting.py``). ``now`` is normalised before comparison.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.study.models import UserCardDirection, UserWord


def naive_utc_now(now_utc: Optional[datetime] = None) -> datetime:
    """Normalise ``now`` to the naive-UTC basis the SRS columns use."""
    if now_utc is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now_utc.tzinfo is not None:
        return now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    return now_utc


def _as_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def srs_scope_filter(user_id: int) -> ColumnElement:
    """The word belongs to ``user_id`` and was not excluded from SRS.

    The query must join (or select from) ``UserWord``.
    """
    return and_(
        UserWord.user_id == user_id,
        UserWord.srs_excluded.is_(False),
    )


def not_buried_filter(now_utc: Optional[datetime] = None) -> ColumnElement:
    """The card is not resting right now."""
    now = naive_utc_now(now_utc)
    return or_(
        UserCardDirection.buried_until.is_(None),
        UserCardDirection.buried_until <= now,
    )


def srs_servable_filter(user_id: int, now_utc: Optional[datetime] = None) -> ColumnElement:
    """Canonical rule: this card may be shown to the user right now.

    Use for every query that serves cards or counts the workload the user is
    expected to clear.
    """
    return and_(srs_scope_filter(user_id), not_buried_filter(now_utc))


def is_word_in_srs(user_word: Any) -> bool:
    """Python twin of :func:`srs_scope_filter` for an already-loaded row."""
    if user_word is None:
        return False
    return not bool(getattr(user_word, 'srs_excluded', False))


def is_card_resting(direction: Any, now_utc: Optional[datetime] = None) -> bool:
    """Python twin of the negated :func:`not_buried_filter`."""
    buried_until = _as_naive(getattr(direction, 'buried_until', None))
    if buried_until is None:
        return False
    return buried_until > naive_utc_now(now_utc)


def is_card_servable(direction: Any, now_utc: Optional[datetime] = None) -> bool:
    """Python twin of :func:`srs_servable_filter` for an already-loaded row.

    Reads the owning ``UserWord`` through the relationship, so callers that
    only hold a direction still get the exclusion rule applied.
    """
    if direction is None:
        return False
    if is_card_resting(direction, now_utc):
        return False
    return is_word_in_srs(getattr(direction, 'user_word', None))
