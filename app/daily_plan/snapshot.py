"""Daily required-plan snapshot: the fixed plan composition for a day.

This is the only required-plan path. It freezes full item dicts (id, kind,
title, url, eta, data, completion_signal) on the first build of the user's
study day — which starts at ``LEARNING_DAY_START_HOUR`` (02:00) local, not at
calendar midnight. Required composition is fixed for the day;
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
# v4 (2026-09-06, lesson audit items 12-13): the SRS tile's composition,
# subtitle and pause hint are frozen in the snapshot; v3 rows built before
# the deploy kept showing the old review budget («4 на повтор», «фокус на
# повторении») for a whole study day. The roll-over from yesterday goes
# through the same version check, so a bump rebuilds everyone once.
SNAPSHOT_VERSION = 4

# SRS ``data`` keys that describe today's *progress* rather than the day's
# frozen composition — re-read on every overlay (DP-041). ``goal_total`` is
# deliberately absent: the denominator stays put for the whole day.
_SRS_LIVE_COUNTERS = ('reviews_today', 'new_today', 'overdue_reviews')


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
        try:
            # `add` INSIDE the savepoint — begin_nested() flushes the session to
            # take its snapshot BEFORE emitting SAVEPOINT, so an insert staged
            # beforehand runs in the outer transaction and its IntegrityError
            # poisons the session instead of being rolled back here.
            with db.session.begin_nested():
                db.session.add(log)
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
      - the user had zero learning activity in yesterday's study-day
        window (``has_learning_activity`` over the 24h naive-UTC bounds
        anchored at 02:00 local — see :func:`_local_date_start_naive_utc`)
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
    # The window END is the NEXT study day's start, not `start + 24h`: study days
    # run 23 or 25 hours across a DST transition, and a fixed delta would let an
    # hour of today's activity suppress (or an hour of yesterday's escape) the
    # roll-over decision.
    y_start = _local_date_start_naive_utc(user_id, yesterday, db)
    y_end = _local_date_start_naive_utc(user_id, yesterday + timedelta(days=1), db)

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
    """Return UTC-naive study-day start (02:00 local) for an explicit date.

    ``local_date`` is already a *study-day* date (it comes from
    ``get_user_local_date``), so anchoring the window at calendar midnight
    shifted it two hours early: activity between 00:00 and 02:00 fell into
    the next window, and the roll-over check both missed a real study session
    and counted the previous day's one (DP-002 / DP-009). Delegates to
    :func:`app.utils.time_utils.study_day_start_utc` — the same anchor the
    streak, telegram and SRS windows use.
    """
    from app.utils.time_utils import get_user_timezone_name, study_day_start_utc

    tz_name = get_user_timezone_name(user_id, db)
    return study_day_start_utc(tz_name, local_date).replace(tzinfo=None)


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
      - the day's live SRS counters refreshed inside ``data``
      - the current reading target/progress refreshed inside ``data``

    Other fields (id, kind, title, subtitle, lesson_type, completion_signal)
    and the rest of ``data`` are passed through unchanged.

    A finished reading book is dropped outright. Every other drop goes through
    the single reachability predicate :func:`_item_unreachable`, and only for a
    *still-incomplete* item: the builder's gates cover only the day the
    snapshot is composed, the required list is then frozen, and the world under
    it keeps moving — a licence expires, an admin deletes the lesson, the user
    empties the decks the frozen deck-quiz was built over. Without the repair
    such an item blocks ``day_secured`` until the study day rolls over at
    02:00. An item already completed before it became unreachable is kept: it
    blocks nothing, and dropping it would revoke earned credit.
    """
    items_out: list[dict[str, Any]] = []
    for item in snapshot.get('items') or []:
        merged = dict(item)
        merged['section'] = 'required'
        if _is_finished_reading_book(user_id, merged, db):
            continue
        completed = _is_item_completed(user_id, merged, db)
        # Reachability is checked AFTER completion: the point of the drop is to
        # unblock a slot that can no longer be finished, and a slot already
        # finished this morning is not blocking anything. Dropping it anyway
        # would erase credit the user really earned and shrink the
        # steps_done/steps_total pair that feeds get_required_steps.
        if not completed and _item_unreachable(user_id, merged, db):
            continue
        merged['completed'] = completed
        _refresh_srs_counters(user_id, merged, db)
        _refresh_reading_target(user_id, merged, db)
        if completed:
            merged['eta_minutes'] = 0
            merged['url'] = None
        items_out.append(merged)
    return items_out


def _item_unreachable(user_id: int, item: dict[str, Any], db: Any) -> bool:
    """One predicate for «this frozen required item can no longer be finished».

    Every kind that has a live precondition at build time needs the same check
    again at overlay time, because the snapshot froze the answer at 02:00:

    * ``reading`` — book access (DP-033),
    * ``curriculum`` — the lesson row still exists (DP-005),
    * ``srs:deck_quiz`` — the decks still hold quizzable words (DP-044).

    Deliberately one dispatcher and one call-site in ``overlay_completion``:
    a second pass over ``items`` would drift from the completion pass that
    decides whether the drop is allowed at all.
    """
    kind = item.get('kind') or ''
    if kind == 'reading':
        return _reading_book_unreachable(user_id, item, db)
    if kind == 'curriculum':
        return _curriculum_lesson_unreachable(user_id, item, db)
    if (item.get('id') or '') == 'srs:deck_quiz':
        return _deck_quiz_unreachable(user_id, db)
    return False


def _curriculum_lesson_unreachable(
    user_id: int,
    item: dict[str, Any],
    db: Any,
) -> bool:
    """True when the frozen curriculum slot points at a lesson that is gone.

    An admin deleting a lesson (or a module, cascading into its lessons) mid-day
    leaves the snapshot pointing at ``/curriculum/lesson/<id>/…`` → 404, while
    ``_curriculum_lesson_done_today`` can never turn True for a row that no
    longer exists and ``skip-lesson`` rejects the id as ``invalid_lesson``.
    The day then cannot be closed by any amount of work (DP-005).

    An item whose ``lesson_id`` does not resolve to an int is unreachable for
    the same reason — its completion detector short-circuits to False forever.
    A transient lookup failure keeps the item: required must not shrink on a
    hiccup.
    """
    data = item.get('data') or {}
    lesson_id = data.get('lesson_id')
    try:
        lesson_id_int = int(lesson_id) if lesson_id is not None else None
    except (TypeError, ValueError):
        lesson_id_int = None
    if lesson_id_int is None:
        logger.warning(
            "snapshot curriculum slot dropped user=%s item=%s reason=no_lesson_id",
            user_id, item.get('id'),
        )
        return True
    try:
        from app.curriculum.models import Lessons

        if db.session.get(Lessons, lesson_id_int) is not None:
            return False
    except Exception:
        logger.warning(
            "snapshot curriculum lesson check failed user=%s lesson=%s",
            user_id, lesson_id_int, exc_info=True,
        )
        return False
    logger.warning(
        "snapshot curriculum slot dropped user=%s lesson=%s reason=lesson_deleted",
        user_id, lesson_id_int,
    )
    return True


def _deck_quiz_unreachable(user_id: int, db: Any) -> bool:
    """True when the frozen deck-quiz slot has no words left to quiz over.

    ``_srs_item_dict`` checks ``_count_user_deck_quiz_words > 0`` once, when the
    snapshot is composed. Deleting a deck (or its last word) later the same day
    leaves a required slot whose quiz generator returns zero questions, so its
    own completion signal can never fire (DP-044). Re-reading the same counter
    here is the repair; the day then closes on the remaining required items.
    """
    try:
        from app.daily_plan.linear.slots.srs_slot import _count_user_deck_quiz_words

        if _count_user_deck_quiz_words(user_id, db) > 0:
            return False
    except Exception:
        logger.warning(
            "snapshot deck-quiz word count failed user=%s", user_id, exc_info=True,
        )
        return False
    logger.warning(
        "snapshot deck-quiz slot dropped user=%s reason=no_deck_words", user_id,
    )
    return True


def _refresh_srs_counters(user_id: int, item: dict[str, Any], db: Any) -> None:
    """Re-read today's SRS progress into a frozen item's ``data`` (DP-041).

    Only the numerator moves. ``goal_total`` is frozen on purpose (see
    ``_srs_goal_total`` in ``plan_builder``) so «12 из 30» does not become
    «12 из 18» as the due pile shrinks — but the snapshot froze the counted
    side too, so the dashboard read ``reviews_today = 0`` all day and hid the
    progress caption entirely, no matter how many cards were actually
    reviewed. The debt badge (``overdue_reviews``) is the same frozen number
    and moves with them.

    Composition is untouched: no key is added, only the ones the builder
    already wrote are re-read. The deck-quiz variant carries none of them and
    is skipped — its data describes decks, not card reviews.

    ``data`` is replaced with a copy: ``overlay_completion`` shallow-copies the
    item, so mutating the nested dict in place would edit the snapshot held in
    ``DailyPlanLog.plan_json``.
    """
    if (item.get('kind') or '') != 'srs':
        return
    data = item.get('data') or {}
    live_keys = [k for k in _SRS_LIVE_COUNTERS if k in data]
    if not live_keys:
        return
    try:
        from app.srs.counting import count_new_cards_today, count_reviews_today
        from app.study.services import SRSService

        fresh = {
            'reviews_today': int(count_reviews_today(user_id, db) or 0),
            'new_today': int(count_new_cards_today(user_id, db) or 0),
            'overdue_reviews': int(SRSService.get_overdue_review_count(user_id) or 0),
        }
    except Exception:
        logger.warning(
            "snapshot srs counter refresh failed user=%s", user_id, exc_info=True,
        )
        return
    refreshed = dict(data)
    for key in live_keys:
        refreshed[key] = fresh[key]
    item['data'] = refreshed


def _refresh_reading_target(user_id: int, item: dict[str, Any], db: Any) -> None:
    """Refresh today's alternating reading target on a frozen item (DP-049).

    Rolled-over snapshots retain yesterday's 5/10 minute subtitle and gate,
    while completion is evaluated against today's target.  Refresh every
    target-dependent field together so API consumers never see a mixture of
    today's completion state and yesterday's progress metadata.

    As with the SRS refresh, replace the nested ``data`` dict instead of
    mutating the snapshot-owned object in place.
    """
    if (item.get('kind') or '') != 'reading':
        return

    data = item.get('data') or {}
    book_id = data.get('book_id')
    try:
        book_id_int = int(book_id) if book_id is not None else None
    except (TypeError, ValueError):
        book_id_int = None
    if book_id_int is None:
        return

    try:
        from app.books.reading_session import (
            get_book_reading_seconds_today,
            get_daily_reading_target_seconds,
        )
        from app.utils.time_utils import get_user_local_date

        target_seconds = int(
            get_daily_reading_target_seconds(get_user_local_date(user_id, db))
        )
        time_spent_seconds = int(
            get_book_reading_seconds_today(user_id, book_id_int, db) or 0
        )
    except Exception:
        logger.warning(
            "snapshot reading target refresh failed user=%s book=%s",
            user_id, book_id_int, exc_info=True,
        )
        return

    target_minutes = target_seconds // 60
    subtitle_parts: list[str] = []
    chapter_num = data.get('current_chapter_num')
    chapter_title = data.get('current_chapter_title')
    if chapter_num is not None:
        subtitle_parts.append(f'Глава {chapter_num}')
    if chapter_title:
        subtitle_parts.append(str(chapter_title))
    subtitle_parts.append(f'Норма дня — {target_minutes} мин')

    refreshed = dict(data)
    refreshed.update({
        'time_spent_seconds': time_spent_seconds,
        'gate_seconds': target_seconds,
        'gate_reached': time_spent_seconds >= target_seconds,
    })
    item['data'] = refreshed
    item['subtitle'] = ' · '.join(subtitle_parts)
    item['eta_minutes'] = target_minutes


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
        from app.daily_plan.linear.xp import is_deck_quiz_completed_today
        # Own signal only (DP-042): the shared `linear_srs_global` key is
        # written by a plain /study session and by the corrective fallback
        # inside is_srs_slot_completed_today, neither of which is a quiz.
        return bool(is_deck_quiz_completed_today(user_id, db))

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


def _is_finished_reading_book(user_id: int, item: dict[str, Any], db: Any) -> bool:
    """Return True for stale snapshot reading items whose book is complete."""
    if item.get('kind') != 'reading':
        return False
    data = item.get('data') or {}
    book_id = data.get('book_id')
    try:
        book_id_int = int(book_id) if book_id is not None else None
    except (TypeError, ValueError):
        book_id_int = None
    if book_id_int is None:
        return False
    try:
        from app.books.progress import get_book_completion_state
        return bool(get_book_completion_state(user_id, book_id_int, db)['is_completed'])
    except Exception:
        logger.warning(
            "snapshot reading completion check failed user=%s book=%s",
            user_id, book_id_int, exc_info=True,
        )
        return False


def _reading_book_unreachable(user_id: int, item: dict[str, Any], db: Any) -> bool:
    """True when a frozen reading slot points at a book the user can't open.

    Access is not static: a licence expires, an admin pulls the ``books``
    module, a book is unpublished. The snapshot is frozen for the day, so the
    slot keeps pointing at a 403/404 and ``day_secured`` stays unreachable.

    Dropping the item is the only honest repair — marking it ``completed``
    would be a fake credit and would also fake a perfect day. A book row that
    has disappeared counts as unreachable for the same reason. Errors keep the
    item: a transient failure must not silently shrink the required list.
    """
    if item.get('kind') != 'reading':
        return False
    data = item.get('data') or {}
    book_id = data.get('book_id')
    try:
        book_id_int = int(book_id) if book_id is not None else None
    except (TypeError, ValueError):
        book_id_int = None
    if book_id_int is None:
        return False
    try:
        from app.books.models import Book
        from app.daily_plan.items.reading import book_access_ok_for_reading

        book = db.session.get(Book, book_id_int)
        if book_access_ok_for_reading(user_id, book, db):
            return False
    except Exception:
        logger.warning(
            "snapshot reading access check failed user=%s book=%s",
            user_id, book_id_int, exc_info=True,
        )
        return False
    logger.warning(
        "snapshot reading slot dropped user=%s book=%s reason=access_revoked",
        user_id, book_id_int,
    )
    return True


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

    "Today" is the *study* day (02:00 local → 02:00 local), taken from
    ``get_user_local_day_bounds`` — the same window ``_grammar_reviewed_today``
    (``app/daily_plan/items/grammar_review.py``) and ``_curriculum_lesson_done_today``
    above use. A hand-rolled calendar-midnight window was two hours early
    relative to the study-day date it was derived from (DP-009): the second
    signal below filters on ``LessonAttempt.completed_at``, a real wall-clock
    moment, so a curriculum grammar lesson finished at 01:00 local fell outside
    its own study day (required slot stays open, ``day_secured`` unreachable)
    and inside the *next* one (a day with no work closes the slot).
    """
    from app.curriculum.models import LessonAttempt, Lessons
    from app.grammar_lab.models import GrammarExercise, UserGrammarExercise
    from app.utils.time_utils import get_user_local_day_bounds

    start_utc, end_utc = get_user_local_day_bounds(user_id, db)

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
