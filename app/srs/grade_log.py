"""Append-only log of SRS grades and the retention metric built on it.

Lesson audit item 11 (2026-09-06). Two grading surfaces exist
(``UnifiedSRSService.grade_card`` and ``UserCardDirection.update_after_review``);
both call :func:`record_grade_event` after the SM-2 update so every grade is
kept with the card state *before* the answer. :func:`recent_mature_accuracy`
reads it back for the adaptive tier: percent recalled on the last N grades of
cards that were in REVIEW state when asked — a real retention test, unlike the
lifetime ``correct_count`` / ``incorrect_count`` it replaces (those kept a
returning learner in ``collapse`` on years-old misses) and unlike relearning
re-asks ten minutes after a miss (mostly successes, which would inflate it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.srs.constants import RATING_DOUBT, CardState
from app.utils.db import db

# Below this many mature grades the metric is not trusted and the caller falls
# back to the legacy lifetime counters, so a fresh deployment does not flip
# every struggling learner to «normal» overnight.
MIN_MATURE_GRADES_FOR_ACCURACY = 10


@dataclass(frozen=True)
class CardSnapshot:
    """Card scheduling fields captured *before* the SM-2 update mutates them."""

    state: str
    step_index: int
    interval: int
    ease_factor: float | None
    lapses: int
    first_reviewed_is_none: bool

    @classmethod
    def of(cls, card: Any) -> CardSnapshot:
        return cls(
            state=card.state or CardState.NEW.value,
            step_index=int(card.step_index or 0),
            interval=int(card.interval or 0),
            ease_factor=card.ease_factor,
            lapses=int(card.lapses or 0),
            first_reviewed_is_none=card.first_reviewed is None,
        )


def _owned_session_id(session_id: Any, user_id: int) -> int | None:
    """The client sends ``session_id`` as-is; only a session of this user is linked."""
    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        return None
    from app.study.models import StudySession

    exists = db.session.query(StudySession.id).filter_by(id=sid, user_id=user_id).first()
    return sid if exists else None


def record_grade_event(
    card: Any,
    *,
    rating: int,
    before: CardSnapshot,
    user_id: int | None,
    context: str | None = None,
    session_id: Any = None,
    db_session: Any = db,
):
    """Append one grade row for ``card`` (already holding its post-grade state).

    Flush-only; the caller commits with the grade. Returns the event, or None
    when the owner is unknown (nothing sensible to attribute the grade to).
    """
    if user_id is None:
        return None
    from app.study.models import CardGradeEvent

    if card.id is None:
        db_session.session.flush()
    user_word = getattr(card, 'user_word', None)
    event = CardGradeEvent(
        user_id=user_id,
        direction_id=card.id,
        word_id=getattr(user_word, 'word_id', None),
        rating=int(rating),
        state_before=before.state,
        step_before=before.step_index,
        interval_before=before.interval,
        ease_before=before.ease_factor,
        lapses_before=before.lapses,
        state_after=card.state or CardState.NEW.value,
        interval_after=int(card.interval or 0),
        ease_after=card.ease_factor,
        is_first_review=before.first_reviewed_is_none,
        context=(context or None) and str(context)[:32],
        session_id=_owned_session_id(session_id, user_id) if session_id is not None else None,
        graded_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db_session.session.add(event)
    return event


def recent_mature_accuracy(
    user_id: int,
    window: int,
    *,
    min_events: int = MIN_MATURE_GRADES_FOR_ACCURACY,
    db_session: Any = db,
) -> float | None:
    """Percent recalled on the last ``window`` grades of REVIEW-state cards.

    Returns None when fewer than ``min_events`` such grades exist — the caller
    decides what to trust instead. Relearning re-asks and learning steps are
    excluded on purpose: only a card that had graduated measures retention.
    """
    from app.study.models import CardGradeEvent

    rows = (
        db_session.session.query(CardGradeEvent.rating)
        .filter(
            CardGradeEvent.user_id == user_id,
            CardGradeEvent.state_before == CardState.REVIEW.value,
        )
        .order_by(CardGradeEvent.graded_at.desc(), CardGradeEvent.id.desc())
        .limit(max(1, int(window)))
        .all()
    )
    if len(rows) < min_events:
        return None
    correct = sum(1 for (rating,) in rows if (rating or 0) >= RATING_DOUBT)
    return correct / len(rows) * 100.0
