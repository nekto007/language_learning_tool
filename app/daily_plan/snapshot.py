"""Daily required-plan snapshot: the fixed plan composition for a day.

This is the only required-plan path. It freezes full item dicts (id, kind,
title, url, eta, data, completion_signal) at user-local midnight or on the
first lazy build after midnight. Required composition is fixed for the day;
only ``completed`` is overlaid live from real activity. Skill slots are
intentionally absent: the day is closed by curriculum, SRS, reading, and
final-test prep items sized by the user's tier (see ``tier.py``).

Roll-over: when ``has_learning_activity`` was False for yesterday, today's
snapshot is a verbatim copy of yesterday's so the user picks up where they
left off.

Writes go through :func:`_get_or_create_log_row` — flush-only, race-safe
against ``uq_daily_plan_log_user_date`` so scheduler and first dashboard GET
share one row.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# v3: bumped to invalidate v2 snapshots that froze a broken grammar-prep
# return_url (/lesson/<id>/final_test, missing the /curriculum prefix → 404).
# Bumping forces a fresh rebuild with the corrected URL on next plan load.
SNAPSHOT_VERSION = 3


def _get_or_create_log_row(user_id: int, plan_date: Any, db: Any):
    """Race-safe get-or-create по uq_daily_plan_log_user_date (flush-only)."""
    from sqlalchemy.exc import IntegrityError

    from app.daily_plan.models import DailyPlanLog

    log = (
        db.session.query(DailyPlanLog)
        .filter_by(user_id=user_id, plan_date=plan_date)
        .first()
    )
    if log is None:
        log = DailyPlanLog(user_id=user_id, plan_date=plan_date)
        db.session.add(log)
        try:
            with db.session.begin_nested():
                db.session.flush()
        except IntegrityError:
            log = (
                db.session.query(DailyPlanLog)
                .filter_by(user_id=user_id, plan_date=plan_date)
                .first()
            )
    return log


def _valid_snapshot(raw: Any) -> Optional[dict[str, Any]]:
    """Return the raw payload if it is a well-formed snapshot, else None."""
    if not isinstance(raw, dict) or raw.get('version') != SNAPSHOT_VERSION:
        return None
    items = raw.get('items')
    if not isinstance(items, list):
        return None
    for it in items:
        if not isinstance(it, dict) or not it.get('id') or not it.get('kind'):
            return None
    return raw


def resolve_snapshot_for_today(
    user_id: int,
    today_local: Any,
    db: Any,
) -> dict[str, Any]:
    """Return the snapshot for ``today_local``, building/rolling as needed.

    Order of operations:
      1. If today's row already has a snapshot, return it.
      2. Else if yesterday's row has a snapshot AND
         ``has_learning_activity(yesterday)`` is False, copy yesterday's
         items into today's row verbatim. The user gets the same plan
         to finish.
      3. Else build a fresh snapshot via ``plan_builder``.

    Persistence is flush-only via :func:`_get_or_create_log_row`; the
    caller commits. Returns an empty snapshot
    (``{'version': SNAPSHOT_VERSION, 'date': ..., 'items': []}``) when no curriculum
    content is available — graduated / fresh-with-no-content users.
    """
    from datetime import timedelta

    log = _get_or_create_log_row(user_id, today_local, db)
    if log is None:
        return _empty_snapshot(today_local)

    existing = _valid_snapshot(log.plan_json)
    if existing is not None:
        return existing

    yesterday = today_local - timedelta(days=1)
    rolled = _try_rollover_from_yesterday(user_id, yesterday, today_local, db)
    if rolled is not None:
        log.plan_json = rolled
        db.session.flush()
        return rolled

    fresh = _build_fresh_snapshot(user_id, today_local, db)
    log.plan_json = fresh
    db.session.flush()
    return fresh


def _empty_snapshot(today_local: Any) -> dict[str, Any]:
    return {
        'version': SNAPSHOT_VERSION,
        'date': today_local.isoformat(),
        'tier': None,
        'rolled_over_from': None,
        'items': [],
    }


def _build_fresh_snapshot(
    user_id: int,
    today_local: Any,
    db: Any,
) -> dict[str, Any]:
    """Compose a brand-new snapshot for today via ``plan_builder``."""
    from app.daily_plan.plan_builder import build_required_snapshot
    from app.daily_plan.tier import compute_user_tier

    tier = compute_user_tier(user_id, db)
    items = build_required_snapshot(user_id, tier, db)
    logger.info(
        "daily_plan_snapshot user=%s date=%s tier=%s items=%d fresh",
        user_id, today_local, tier, len(items),
    )
    return {
        'version': SNAPSHOT_VERSION,
        'date': today_local.isoformat(),
        'tier': tier,
        'rolled_over_from': None,
        'items': items,
    }


def _try_rollover_from_yesterday(
    user_id: int,
    yesterday: Any,
    today_local: Any,
    db: Any,
) -> Optional[dict[str, Any]]:
    """Return a rolled-over snapshot, or None when roll-over does not apply.

    Roll-over fires only when ALL hold:
      - yesterday has a snapshot row with non-empty items
      - the user had zero learning activity in yesterday's user-local
        day window (``has_learning_activity`` over the 24h naive-UTC
        bounds derived from yesterday's user-local midnight)
    """
    from datetime import timedelta

    from app.daily_plan.models import DailyPlanLog

    y_row = (
        db.session.query(DailyPlanLog)
        .filter(DailyPlanLog.user_id == user_id, DailyPlanLog.plan_date == yesterday)
        .first()
    )
    if y_row is None:
        return None
    y_snap = _valid_snapshot(y_row.plan_json)
    if y_snap is None or not y_snap.get('items'):
        return None

    from app.utils.activity_tracker import has_learning_activity
    y_start = _local_date_start_naive_utc(user_id, yesterday, db)
    y_end = y_start + timedelta(days=1)

    if has_learning_activity(user_id, y_start, y_end, db.session):
        return None

    logger.info(
        "daily_plan_snapshot user=%s date=%s rolled_over_from=%s items=%d",
        user_id, today_local, yesterday, len(y_snap['items']),
    )
    return {
        'version': SNAPSHOT_VERSION,
        'date': today_local.isoformat(),
        'tier': y_snap.get('tier'),
        'rolled_over_from': yesterday.isoformat(),
        'items': list(y_snap['items']),
    }


def _local_date_start_naive_utc(user_id: int, local_date: Any, db: Any):
    """Return UTC-naive midnight for an explicit user-local date."""
    from datetime import datetime, time, timezone

    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore

    from app.utils.time_utils import get_user_timezone_name

    try:
        tz = ZoneInfo(get_user_timezone_name(user_id, db))
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    local_midnight = datetime.combine(local_date, time.min, tzinfo=tz)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def overlay_completion(
    user_id: int,
    snapshot: dict[str, Any],
    db: Any,
) -> list[dict[str, Any]]:
    """Return the snapshot items with live ``completed`` flags applied.

    Each returned dict is a copy of the snapshot item with:
      - ``completed`` set from the per-kind detector
      - ``section='required'`` (snapshots are required-only)
      - ``eta_minutes`` zeroed when completed
      - ``url`` set to None when completed (UI hides the CTA)

    Other fields (id, kind, title, subtitle, lesson_type, data,
    completion_signal) are passed through unchanged.
    """
    items_out: list[dict[str, Any]] = []
    for item in snapshot.get('items') or []:
        merged = dict(item)
        merged['section'] = 'required'
        completed = _is_item_completed(user_id, merged, db)
        merged['completed'] = completed
        if completed:
            merged['eta_minutes'] = 0
            merged['url'] = None
        items_out.append(merged)
    return items_out


def _is_item_completed(user_id: int, item: dict[str, Any], db: Any) -> bool:
    """Per-kind completion detector for snapshot overlay.

    Each branch keys on the snapshot ``id`` first (precise) and falls
    back to ``kind`` when the id doesn't carry the needed sub-key.
    """
    item_id = item.get('id') or ''
    kind = item.get('kind') or ''
    data = item.get('data') or {}

    if item_id == 'srs:global':
        from app.daily_plan.linear.xp import is_srs_slot_completed_today
        return bool(is_srs_slot_completed_today(user_id, db))

    if item_id == 'srs:deck_quiz':
        from app.daily_plan.linear.xp import is_srs_slot_completed_today
        # Strict: deck-quiz closes only on its own XP event so the
        # paired card-curriculum lesson doesn't satisfy it via fallback.
        return bool(is_srs_slot_completed_today(user_id, db, allow_fallback=False))

    if kind == 'reading':
        from app.daily_plan.items.reading import _read_today
        book_id = data.get('book_id')
        try:
            book_id_int = int(book_id) if book_id is not None else None
        except (TypeError, ValueError):
            book_id_int = None
        return bool(_read_today(user_id, book_id_int, db))

    if kind == 'curriculum':
        lesson_id = data.get('lesson_id')
        try:
            lesson_id_int = int(lesson_id) if lesson_id is not None else None
        except (TypeError, ValueError):
            lesson_id_int = None
        if lesson_id_int is None:
            return False
        return _curriculum_lesson_done_today(user_id, lesson_id_int, db)

    if kind == 'grammar_review':
        topic_id = data.get('topic_id')
        module_id = data.get('module_id')
        try:
            topic_id_int = int(topic_id) if topic_id is not None else None
        except (TypeError, ValueError):
            topic_id_int = None
        try:
            module_id_int = int(module_id) if module_id is not None else None
        except (TypeError, ValueError):
            module_id_int = None
        if topic_id_int is None:
            return False
        return _grammar_topic_practiced_today(
            user_id, topic_id_int, module_id_int, db,
        )

    return False


def _curriculum_lesson_done_today(
    user_id: int,
    lesson_id: int,
    db: Any,
) -> bool:
    """True when THIS specific curriculum lesson was completed today.

    Differs from the general ``_curriculum_done_today`` (which checks
    «any curriculum lesson today»). For static snapshots we need a
    per-lesson signal: an audio lesson at slot 1 does not close a
    grammar lesson at slot 2 just because both fired a curriculum-XP
    event somewhere today.

    Primary: ``StreakEvent.details.lesson_id`` matches today + this
    lesson_id. Fallback: ``LessonProgress`` row for this lesson with
    ``last_activity`` in the user-local day AND a passing score for
    score-based types.
    """
    from app.achievements.models import StreakEvent
    from app.curriculum.models import LessonProgress, Lessons
    from app.daily_plan.items.curriculum import (
        _CURRICULUM_XP_SOURCES,
        _lesson_meets_passing,
    )
    from app.daily_plan.linear.xp import (
        LINEAR_XP_EVENT_TYPE,
        get_linear_event_local_date,
    )
    from app.utils.time_utils import get_user_local_day_bounds

    today = get_linear_event_local_date(user_id, db)
    xp_exists = db.session.query(
        db.session.query(StreakEvent)
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.event_date == today,
            StreakEvent.details['source'].astext.in_(list(_CURRICULUM_XP_SOURCES)),
            StreakEvent.details['lesson_id'].astext == str(lesson_id),
        )
        .exists()
    ).scalar() or False
    if xp_exists:
        return True

    today_start, today_end = get_user_local_day_bounds(user_id, db)
    row = (
        db.session.query(LessonProgress.score, Lessons)
        .join(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id == lesson_id,
            LessonProgress.status == 'completed',
            LessonProgress.last_activity.isnot(None),
            LessonProgress.last_activity >= today_start,
            LessonProgress.last_activity < today_end,
        )
        .first()
    )
    if row is None:
        return False
    score, lesson = row
    return _lesson_meets_passing(lesson, score)


def _grammar_topic_practiced_today(
    user_id: int,
    topic_id: int,
    module_id: Optional[int],
    db: Any,
) -> bool:
    """True when the user practised THIS grammar topic today.

    Two signals:
      1. ``UserGrammarExercise.last_reviewed`` in today for any
         exercise of this topic (standalone grammar-lab practice).
      2. ``LessonAttempt.completed_at`` in today for a curriculum
         grammar lesson tied to this topic — and, when ``module_id``
         is known, restricted to that module so practising the same
         topic via a *different* module's grammar lesson does not
         close the pre-FT step for this module.
    """
    from datetime import datetime, timedelta, timezone

    from app.curriculum.models import LessonAttempt, Lessons
    from app.grammar_lab.models import GrammarExercise, UserGrammarExercise
    from app.utils.time_utils import get_user_local_date, get_user_timezone_name

    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore

    today = get_user_local_date(user_id, db)
    tz_name = get_user_timezone_name(user_id, db)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    start_local = datetime(today.year, today.month, today.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    standalone_q = (
        db.session.query(UserGrammarExercise.id)
        .join(GrammarExercise, GrammarExercise.id == UserGrammarExercise.exercise_id)
        .filter(
            UserGrammarExercise.user_id == user_id,
            GrammarExercise.topic_id == topic_id,
            UserGrammarExercise.last_reviewed.isnot(None),
            UserGrammarExercise.last_reviewed >= start_utc,
            UserGrammarExercise.last_reviewed < end_utc,
        )
    )
    if db.session.query(standalone_q.exists()).scalar():
        return True

    curric_q = (
        db.session.query(LessonAttempt.id)
        .join(Lessons, Lessons.id == LessonAttempt.lesson_id)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.completed_at.isnot(None),
            LessonAttempt.completed_at >= start_utc,
            LessonAttempt.completed_at < end_utc,
            Lessons.type == 'grammar',
            Lessons.grammar_topic_id == topic_id,
        )
    )
    if module_id is not None:
        curric_q = curric_q.filter(Lessons.module_id == module_id)
    return bool(db.session.query(curric_q.exists()).scalar() or False)
