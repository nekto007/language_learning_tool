"""Quiz error log service helpers for the linear daily plan.

Writes one ``QuizErrorLog`` row per incorrect quiz answer at grading time,
and surfaces an unresolved pool to the dashboard when the trigger fires.

Trigger for the 4th baseline slot (error review):
    count(unresolved) >= 5
    AND (
        max(resolved_at) IS NULL
        OR max(resolved_at) < now() - 3 days
    )

The trigger favors "old enough + many enough" errors — avoids nagging the
user right after they just finished a review session.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func

from app.daily_plan.linear.models import QuizErrorLog

logger = logging.getLogger(__name__)


REVIEW_TRIGGER_MIN_UNRESOLVED = 5
REVIEW_TRIGGER_COOLDOWN = timedelta(days=3)
DEFAULT_REVIEW_POOL_LIMIT = 10


def _sanitize_payload(question_payload: Any) -> dict:
    """Return a JSONB-safe copy of ``question_payload``.

    Falls back to ``{'raw': str(...)}`` for non-dict inputs so the DB never
    rejects the row — we never want quiz grading to break because of a
    malformed payload.
    """
    if isinstance(question_payload, dict):
        return dict(question_payload)
    return {'raw': str(question_payload) if question_payload is not None else ''}


def log_quiz_error(
    user_id: int,
    lesson_id: int,
    question_payload: Any,
    db: Any,
    *,
    commit: bool = False,
) -> QuizErrorLog:
    """Insert one ``QuizErrorLog`` row.

    ``commit=False`` (default) flushes but does not commit; the caller's
    outer transaction owns the commit. This matches how the quiz
    controllers operate — they commit once after the grading+progress
    update.
    """
    entry = QuizErrorLog(
        user_id=user_id,
        lesson_id=lesson_id,
        question_payload=_sanitize_payload(question_payload),
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return entry


def _unresolved_question_indices(user_id: int, lesson_id: int, db: Any) -> set[int]:
    """Return question indices that already have an unresolved row for this lesson.

    Prevents quiz re-attempts from stacking multiple rows per question,
    which would inflate the 4th-slot trigger count and surface the same
    question multiple times in the review pool.
    """
    rows = (
        db.session.query(QuizErrorLog)
        .filter(
            QuizErrorLog.user_id == user_id,
            QuizErrorLog.lesson_id == lesson_id,
            QuizErrorLog.resolved_at.is_(None),
        )
        .all()
    )
    indices: set[int] = set()
    for row in rows:
        payload = row.question_payload if isinstance(row.question_payload, dict) else None
        if payload is None:
            continue
        raw = payload.get('question_index')
        if isinstance(raw, int):
            indices.add(raw)
        else:
            try:
                indices.add(int(raw))
            except (TypeError, ValueError):
                continue
    return indices


def log_quiz_errors_from_result(
    user_id: int,
    lesson_id: int,
    questions: list[dict],
    result: dict,
    db: Any,
) -> list[QuizErrorLog]:
    """Iterate a ``process_quiz_submission`` result and log each incorrect answer.

    The result ``feedback`` dict keys are stringified question indices
    (``'0'``, ``'1'``, ...) with a ``status`` of ``'correct'`` or
    ``'incorrect'``. We log one row per incorrect entry, embedding the
    original question, user answer, and correct answer into the payload
    so the review slot can rebuild the question later. If the same
    question already has an unresolved row (quiz re-attempt), we skip
    it so the pool doesn't accumulate duplicates.

    Silent no-op when feedback is missing/empty — malformed results from
    older test flows must not crash grading.
    """
    feedback = result.get('feedback') if isinstance(result, dict) else None
    if not isinstance(feedback, dict) or not feedback:
        return []

    already_logged = _unresolved_question_indices(user_id, lesson_id, db)

    logged: list[QuizErrorLog] = []
    for raw_idx, entry in feedback.items():
        if not isinstance(entry, dict):
            continue
        if entry.get('status') != 'incorrect':
            continue

        try:
            q_idx = int(raw_idx)
        except (TypeError, ValueError):
            continue

        if q_idx in already_logged:
            continue

        if q_idx < 0 or q_idx >= len(questions):
            question = {}
        else:
            question = questions[q_idx] or {}

        payload = {
            'question_index': q_idx,
            'question_type': question.get('type'),
            'question_text': question.get('question') or question.get('prompt'),
            'options': question.get('options'),
            'user_answer': entry.get('user_answer'),
            'correct_answer': entry.get('correct_answer'),
        }
        logged.append(log_quiz_error(user_id, lesson_id, payload, db))
        already_logged.add(q_idx)
    return logged


def resolve_quiz_error(
    error_id: int,
    user_id: int,
    db: Any,
    *,
    commit: bool = False,
) -> Optional[QuizErrorLog]:
    """Mark a single error row resolved. No-op if it doesn't exist / belongs to someone else."""
    entry = db.session.get(QuizErrorLog, error_id)
    if entry is None or entry.user_id != user_id:
        return None
    if entry.resolved_at is None:
        entry.resolved_at = datetime.now(timezone.utc)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
    return entry


def resolve_quiz_errors(
    error_ids: Iterable[int],
    user_id: int,
    db: Any,
    *,
    commit: bool = False,
) -> list[QuizErrorLog]:
    """Bulk-resolve helper: only rows owned by ``user_id`` are updated."""
    resolved: list[QuizErrorLog] = []
    for error_id in error_ids:
        entry = resolve_quiz_error(error_id, user_id, db, commit=False)
        if entry is not None and entry.resolved_at is not None:
            resolved.append(entry)
    if commit and resolved:
        db.session.commit()
    return resolved


def count_unresolved(user_id: int, db: Any) -> int:
    """Return the count of unresolved quiz errors for this user."""
    return int(
        db.session.query(func.count(QuizErrorLog.id))
        .filter(
            QuizErrorLog.user_id == user_id,
            QuizErrorLog.resolved_at.is_(None),
        )
        .scalar()
        or 0
    )


def get_last_resolved_at(user_id: int, db: Any) -> Optional[datetime]:
    """Return the most recent ``resolved_at`` timestamp, or None."""
    return (
        db.session.query(func.max(QuizErrorLog.resolved_at))
        .filter(QuizErrorLog.user_id == user_id)
        .scalar()
    )


def get_review_pool(
    user_id: int,
    db: Any,
    limit: int = DEFAULT_REVIEW_POOL_LIMIT,
) -> list[QuizErrorLog]:
    """Return oldest unresolved errors, capped at ``limit``.

    Ordered by ``created_at`` ascending so the review session surfaces
    the stalest mistakes first.
    """
    if limit <= 0:
        return []
    return (
        db.session.query(QuizErrorLog)
        .filter(
            QuizErrorLog.user_id == user_id,
            QuizErrorLog.resolved_at.is_(None),
        )
        .order_by(QuizErrorLog.created_at.asc(), QuizErrorLog.id.asc())
        .limit(limit)
        .all()
    )


def should_show_error_review(
    user_id: int,
    db: Any,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Trigger logic for the conditional 4th baseline slot.

    True iff there are at least ``REVIEW_TRIGGER_MIN_UNRESOLVED`` unresolved
    errors AND the cooldown since the last resolve has elapsed (or the
    user has never resolved one).
    """
    unresolved = count_unresolved(user_id, db)
    if unresolved < REVIEW_TRIGGER_MIN_UNRESOLVED:
        return False

    last_resolved = get_last_resolved_at(user_id, db)
    if last_resolved is None:
        return True

    reference = now if now is not None else datetime.now(timezone.utc)
    # Normalise naive timestamps from SQLite so the comparison works.
    if last_resolved.tzinfo is None:
        last_resolved = last_resolved.replace(tzinfo=timezone.utc)
    return (reference - last_resolved) >= REVIEW_TRIGGER_COOLDOWN
