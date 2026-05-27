"""Listening and pronunciation attempt tracking."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.curriculum.models import ListeningAttempt, PronunciationAttempt


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
        score=float(score) if score is not None else 0.0,
        replay_count=int(replay_count),
    )
    db.session.add(attempt)
    db.session.flush()
    return attempt


def log_pronunciation_attempt(
    user_id: int,
    word: str,
    recognized: str,
    matched: bool,
    db: Any,
) -> 'PronunciationAttempt':
    """Create a PronunciationAttempt row for a pronunciation exercise item.

    Each attempt creates a new row — multiple attempts per word are intentional.
    Caller commits.
    """
    from app.curriculum.models import PronunciationAttempt

    attempt = PronunciationAttempt(
        user_id=user_id,
        word=str(word),
        recognized_text=str(recognized),
        matched=bool(matched),
    )
    db.session.add(attempt)
    db.session.flush()
    return attempt
