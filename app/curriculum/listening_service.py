"""Listening attempt tracking for dictation and audio_fill_blank lessons."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.curriculum.models import ListeningAttempt


def log_listening_attempt(
    user_id: int,
    lesson_id: int,
    score: float,
    replay_count: int,
    db: Any,
) -> 'ListeningAttempt':
    """Create a ListeningAttempt row for a dictation or audio_fill_blank submission.

    Each submission creates a new row — duplicate attempts per lesson are intentional.
    Caller commits.
    """
    from app.curriculum.models import ListeningAttempt

    attempt = ListeningAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        score=float(score),
        replay_count=int(replay_count),
    )
    db.session.add(attempt)
    db.session.flush()
    return attempt
