"""Stuck lesson-progress reconciliation (safety net for completion races).

Some ``LessonProgress`` rows stay ``status='in_progress'`` even after the
user finished and effectively passed the lesson. Known causes:

  * ``passing_score`` mismatch between the grader and lesson content
    (e.g. ``process_final_test_submission`` uses ``PASSING_SCORE_DEFAULT``
    to compute ``passed``, but ``update_progress_with_grading`` reads
    ``content['passing_score_percent']``, which may be higher — so the
    client gets ``passed: True`` while the DB row stays unflipped).
  * XP/grading exceptions in lesson handlers that roll back the row's
    status update.

This module scans for such rows and reconciles them. Two signals — either
flips the row:

  1. A ``LessonAttempt`` with ``passed=True`` exists for the same
     ``(user_id, lesson_id)``.
  2. ``progress.score`` already meets the lesson's effective passing
     score (read from ``content['passing_score_percent']``/
     ``['passing_score']`` with type-aware defaults from
     ``app.curriculum.constants``).

The scheduler runs this daily; an ops CLI is provided for manual backfill.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func

from app.curriculum.constants import PASSING_SCORE_DEFAULT, PASSING_SCORE_DICTATION
from app.curriculum.models import LessonAttempt, LessonProgress, Lessons

logger = logging.getLogger(__name__)

def _effective_passing_score(lesson: Lessons) -> int:
    """Return the passing-score threshold the lesson actually grades against.

    Mirrors the precedence used by the lesson routes / progress service:
    explicit ``passing_score_percent`` / ``passing_score`` in content win,
    otherwise fall back to the type-default (dictation → 80, everything
    else → 70). ``audio_fill_blank`` uses 70 in both grader and route
    (see ``grade_audio_fill_blank`` and the ``audio_fill_blank`` handler
    in ``lessons.py``) — only ``dictation`` is the 80-threshold special case.
    """
    content = lesson.content if isinstance(lesson.content, dict) else {}
    explicit = content.get('passing_score_percent')
    if explicit is None:
        explicit = content.get('passing_score')
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass
    if (lesson.type or '') == 'dictation':
        return PASSING_SCORE_DICTATION
    return PASSING_SCORE_DEFAULT


@dataclass
class ReconcileReport:
    scanned: int = 0
    flipped: int = 0
    flipped_by_attempt: int = 0
    flipped_by_score: int = 0
    flipped_by_data_perfect: int = 0
    flipped_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _data_says_perfect_mastery(lesson: Lessons, data: Any) -> bool:
    """Return True when ``progress.data`` carries an unambiguous
    perfect-mastery signal that should bypass historical caps.

    Currently only ``dictation`` is handled: the route used to apply an
    "attempt-limit" cap to score even when the final submission was 100%
    correct (see the mastery-override block in ``_process_dictation_submission``).
    Pre-fix rows can therefore be stuck with ``score=79`` and
    ``failed_by_attempt_limit=True`` despite ``correct_words == total_words``
    — those are real completions and should flip.
    """
    if not isinstance(data, dict):
        return False
    if (lesson.type or '') != 'dictation':
        return False
    try:
        correct = int(data.get('correct_words') or 0)
        total = int(data.get('total_words') or 0)
    except (TypeError, ValueError):
        return False
    return total > 0 and correct >= total


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _latest_passed_attempt(
    db_session: Any, user_id: int, lesson_id: int,
) -> Optional[LessonAttempt]:
    return (
        db_session.query(LessonAttempt)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.lesson_id == lesson_id,
            LessonAttempt.passed.is_(True),
        )
        .order_by(LessonAttempt.completed_at.desc().nullslast(),
                  LessonAttempt.id.desc())
        .first()
    )


def _iter_stuck_progress(db_session: Any) -> Iterable[tuple[LessonProgress, Lessons]]:
    """Yield (progress, lesson) pairs for rows where status='in_progress'
    AND at least one of the reconcile signals could plausibly fire.

    We narrow the SQL scan with two cheap predicates and verify the precise
    condition in Python (so we can read lesson.content for per-lesson
    passing thresholds without a JSON expression).
    """
    has_passed_attempt = (
        db_session.query(LessonAttempt.id)
        .filter(
            LessonAttempt.user_id == LessonProgress.user_id,
            LessonAttempt.lesson_id == LessonProgress.lesson_id,
            LessonAttempt.passed.is_(True),
        )
        .exists()
    )
    score_at_least_default = (
        LessonProgress.score.isnot(None)
        & (LessonProgress.score >= PASSING_SCORE_DEFAULT)
    )
    # Dictation rows can be stuck below PASSING_SCORE_DEFAULT (e.g. 79
    # capped by the old attempt-limit override) while progress.data shows
    # full mastery. Include them so the by_data_perfect signal can fire.
    is_dictation = Lessons.type == 'dictation'
    rows = (
        db_session.query(LessonProgress, Lessons)
        .join(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(
            LessonProgress.status == 'in_progress',
            (has_passed_attempt | score_at_least_default | is_dictation),
        )
        .order_by(LessonProgress.id)
        .yield_per(500)
    )
    return rows


def reconcile_stuck_lesson_progress(
    db_session: Any,
    *,
    dry_run: bool = False,
) -> ReconcileReport:
    """Flip ``LessonProgress.status`` to 'completed' for rows that already
    qualify by either signal.

    On a flip:
      * ``status = 'completed'``
      * ``completed_at = max(latest_passed_attempt.completed_at, last_activity, now)``
        (whichever exists — never overwrites an earlier completion timestamp).
      * ``score = max(progress.score, latest_passed_attempt.score)`` so we
        do not regress a higher historical score.

    Idempotent: a second call after a clean run flips nothing. Commits per
    batch of 100 flips (or once at end for smaller runs) so a long backfill
    cannot lose all progress on a transient failure.

    Returns a ``ReconcileReport`` for telemetry / CLI output.
    """
    report = ReconcileReport()
    pending = 0
    now = _now_utc_naive()

    try:
        for progress, lesson in _iter_stuck_progress(db_session):
            report.scanned += 1
            try:
                threshold = _effective_passing_score(lesson)
                latest_passed = _latest_passed_attempt(
                    db_session, progress.user_id, progress.lesson_id,
                )
                score = progress.score or 0
                attempt_score = latest_passed.score if latest_passed else None

                by_attempt = latest_passed is not None
                by_score = score >= threshold
                by_data_perfect = _data_says_perfect_mastery(lesson, progress.data)

                if not (by_attempt or by_score or by_data_perfect):
                    continue

                new_score = score
                if attempt_score is not None and attempt_score > new_score:
                    new_score = attempt_score

                candidate_times = [now]
                if progress.last_activity is not None:
                    candidate_times.append(progress.last_activity)
                if latest_passed is not None and latest_passed.completed_at is not None:
                    candidate_times.append(latest_passed.completed_at)
                completed_at = max(candidate_times)

                progress.status = 'completed'
                progress.score = new_score
                if progress.completed_at is None:
                    progress.completed_at = completed_at

                report.flipped += 1
                if by_attempt:
                    report.flipped_by_attempt += 1
                    signal = 'attempt'
                elif by_score:
                    report.flipped_by_score += 1
                    signal = 'score'
                else:
                    report.flipped_by_data_perfect += 1
                    signal = 'data_perfect'
                report.flipped_ids.append(progress.id)
                pending += 1

                logger.info(
                    "reconcile: flip lesson_progress id=%s user=%s lesson=%s "
                    "score=%s threshold=%s signal=%s",
                    progress.id, progress.user_id, progress.lesson_id,
                    new_score, threshold, signal,
                )

                if not dry_run and pending >= 100:
                    db_session.commit()
                    pending = 0
            except Exception as exc:  # noqa: BLE001
                msg = (
                    f"reconcile failed for lesson_progress id={progress.id}: {exc}"
                )
                logger.warning(msg, exc_info=True)
                report.errors.append(msg)
                db_session.rollback()

        if dry_run:
            db_session.rollback()
        elif pending:
            db_session.commit()
    except Exception as exc:  # noqa: BLE001
        db_session.rollback()
        msg = f"reconcile aborted: {exc}"
        logger.error(msg, exc_info=True)
        report.errors.append(msg)

    return report
