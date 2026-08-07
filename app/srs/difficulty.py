"""Recovery state for cards that repeatedly fail to stick.

This module deliberately owns only the per-direction recovery markers.  The
normal SM-2 state machine remains responsible for intervals and learning
steps, which lets recovery stay inside the existing flashcard session.
"""
from __future__ import annotations

from typing import Any

from app.srs.constants import (
    DIFFICULTY_MAX_SCORE,
    DIFFICULTY_MISS_PENALTY_REVIEW,
    DIFFICULTY_MISS_PENALTY_STEP,
    DIFFICULTY_RECOVERY_THRESHOLD,
    RATING_DONT_KNOW,
    RATING_KNOW,
    RECOVERY_SUCCESSFUL_RECALLS,
    CardState,
)


def miss_penalty(previous_state: str) -> int:
    """Weight of a single miss on ``difficulty_score``.

    Shared with the SM-2 engine, which projects the post-grade score to decide
    whether the card has earned an automatic rest.
    """
    if (previous_state or CardState.NEW.value) == CardState.REVIEW.value:
        return DIFFICULTY_MISS_PENALTY_REVIEW
    return DIFFICULTY_MISS_PENALTY_STEP


def update_recovery_state(
    card: Any,
    *,
    rating: int,
    previous_state: str,
) -> None:
    """Update recovery markers after one graded recall.

    A miss in a learning step is a weaker signal than a lapse from REVIEW,
    but it must still be visible to the system. Two ``Know`` grades while a
    card is in recovery release it back to normal SRS; its difficulty score
    falls but is not erased, so a further miss is treated cautiously.
    """
    previous_state = previous_state or CardState.NEW.value
    score = card.difficulty_score or 0

    if rating == RATING_DONT_KNOW:
        score += miss_penalty(previous_state)
        card.difficulty_score = min(DIFFICULTY_MAX_SCORE, score)
        card.recovery_successes = 0
        if card.difficulty_score >= DIFFICULTY_RECOVERY_THRESHOLD:
            card.recovery_required = True

        # A rested card stays out of every queue for the whole rest period; the
        # recovery invite lands when the rest ends. Inviting it back the next
        # day (the old behaviour) made a multi-day rest invisible — the card
        # returned every single session and only the ordinary queue skipped it.
        if card.buried_until is not None:
            card.recovery_due_at = card.buried_until
        return

    if not card.recovery_required:
        if previous_state == CardState.REVIEW.value and score > 0:
            card.difficulty_score = score - 1
        return

    if rating == RATING_KNOW:
        card.recovery_successes = (card.recovery_successes or 0) + 1
        if card.recovery_successes >= RECOVERY_SUCCESSFUL_RECALLS:
            card.recovery_required = False
            card.recovery_successes = 0
            card.difficulty_score = max(0, score - DIFFICULTY_RECOVERY_THRESHOLD)
            card.recovery_due_at = None
            # Release only this direction. Its state and next_review still
            # come from the normal relearning schedule.
            card.buried_until = None
            card.consecutive_leech_burials = 0
    else:
        # "Doubt" is not a reliable active recall for a recovery card.
        card.recovery_successes = 0
