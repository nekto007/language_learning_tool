"""Linear daily plan XP integration helpers.

Thin adapter layer between the slot-completion endpoints (curriculum
lesson grading, SRS session complete, book reading progress, error review)
and the shared XP service. Responsibilities:

- Map curriculum ``Lesson.type`` values onto the ``LINEAR_XP`` source keys.
- Gate awards on ``User.use_linear_plan`` so mission-flow users are never
  double-credited with both phase and linear XP.
- Persist one ``StreakEvent(event_type='xp_linear')`` per user+date+source
  so repeated grade submissions are idempotent for the day.
- Trigger the linear perfect-day bonus once all baseline slots complete.

The caller owns the outer transaction: these helpers flush but never
commit, matching the grading / SRS / reading endpoints that wrap their
mutations in a single commit.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any, Optional

from app.achievements.xp_service import (
    LINEAR_XP,
    XPAward,
    award_linear_xp,
    award_perfect_day_xp_idempotent,
)

logger = logging.getLogger(__name__)

# Mapping: curriculum lesson.type → LINEAR_XP source key.
# Legacy aliases ("matching", "text", "flashcards") collapse onto the
# closest canonical source so older content still earns XP.
LESSON_TYPE_TO_SOURCE: dict[str, str] = {
    'card': 'linear_curriculum_card',
    'flashcards': 'linear_curriculum_card',
    'vocabulary': 'linear_curriculum_vocabulary',
    'grammar': 'linear_curriculum_grammar',
    'quiz': 'linear_curriculum_quiz',
    'listening_quiz': 'linear_curriculum_listening_quiz',
    'dialogue_completion_quiz': 'linear_curriculum_dialogue_completion_quiz',
    'ordering_quiz': 'linear_curriculum_ordering_quiz',
    'translation_quiz': 'linear_curriculum_translation_quiz',
    'final_test': 'linear_curriculum_final_test',
    'reading': 'linear_curriculum_reading',
    'text': 'linear_curriculum_reading',
    'listening_immersion': 'linear_curriculum_listening_immersion',
    'listening_immersion_quiz': 'linear_curriculum_listening_immersion',
    'matching': 'linear_curriculum_quiz',
    'dictation': 'linear_curriculum_dictation',
    'audio_fill_blank': 'linear_curriculum_audio_fill_blank',
    'translation': 'linear_curriculum_quiz',
    'sentence_correction': 'linear_curriculum_quiz',
    'writing_prompt': 'linear_curriculum_use',
    'sentence_completion': 'linear_curriculum_quiz',
    'collocation_matching': 'linear_curriculum_quiz',
    'shadow_reading': 'linear_curriculum_use',
    'pronunciation': 'linear_curriculum_use',
    'idiom': 'linear_curriculum_vocabulary',
}

LINEAR_XP_EVENT_TYPE = 'xp_linear'

# Minutes credited per slot source when XP is first awarded for the day.
# Any source starting with 'linear_curriculum_' earns curriculum slot minutes (15).
_SRS_SOURCES = {'linear_srs_global', 'linear_book_srs'}
_READING_SOURCES = {'linear_book_reading'}
_LISTENING_SOURCES = {'linear_listening', 'linear_curriculum_listening_immersion', 'linear_curriculum_dictation', 'linear_curriculum_audio_fill_blank'}
_WRITING_SOURCES = {'linear_writing', 'linear_curriculum_use'}
_ERROR_REVIEW_SOURCES = {'linear_error_review'}
_CURRICULUM_MINUTES = 15
_SOURCE_MINUTES: dict[str, int] = {
    'linear_srs_global': 10,
    'linear_book_srs': 10,
    'linear_book_reading': 15,
    'linear_listening': 10,
    'linear_curriculum_listening_immersion': 10,
    'linear_curriculum_dictation': 10,
    'linear_curriculum_audio_fill_blank': 10,
    'linear_writing': 8,
    'linear_curriculum_use': 8,
    'linear_error_review': 12,
    'linear_grammar_review': 10,
}


def _get_user_timezone(user_id: int, db_session: Any = None) -> str:
    from app.auth.models import User
    from app.utils.db import db
    from config.settings import DEFAULT_TIMEZONE

    db_obj = db_session if db_session is not None else db
    user = db_obj.session.get(User, user_id)
    return getattr(user, 'timezone', None) or DEFAULT_TIMEZONE


def get_linear_event_local_date(
    user_id: int,
    db_session: Any = None,
) -> date_cls:
    """Return the user's local date for linear-plan idempotency keys.

    Delegates to the canonical ``app.utils.time_utils.get_user_local_date``
    so the curriculum, linear, and card-lesson write paths all agree.
    """
    from app.utils.time_utils import get_user_local_date

    return get_user_local_date(user_id, db_session)


def is_linear_user(user_id: int) -> bool:
    """Compat shim: linear and unified users get the same XP wiring.

    Previously gated XP awards on ``use_linear_plan``. After the unified
    refactor every active user receives these XP credits, so this just
    confirms the user exists. Kept under the old name so existing call
    sites (XP helpers, slot completion endpoints) need no rename.
    """
    from app.auth.models import User
    from app.utils.db import db

    user = db.session.get(User, user_id)
    return user is not None


# Alias the canonical helper name for new call sites.
is_unified_user = is_linear_user


def get_source_for_lesson_type(lesson_type: Optional[str]) -> Optional[str]:
    """Return the ``LINEAR_XP`` source key for a curriculum lesson type.

    Returns ``None`` for unknown or missing types — callers should skip
    the XP award rather than raise.
    """
    if not lesson_type:
        return None
    return LESSON_TYPE_TO_SOURCE.get(lesson_type)


def _already_awarded(
    user_id: int, source: str, for_date: date_cls, db_session: Any
) -> bool:
    from app.achievements.models import StreakEvent

    query = db_session.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == for_date,
        StreakEvent.details['source'].astext == source,
    )
    return db_session.session.query(query.exists()).scalar() or False


def award_linear_slot_xp_idempotent(
    user_id: int,
    source: str,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
    score: Optional[float] = None,
    extra_details: Optional[dict] = None,
) -> Optional[XPAward]:
    """Award linear XP once per (user, date, source).

    Returns the ``XPAward`` on first call for that tuple, ``None`` on
    subsequent calls the same day. Caller owns the commit. ``score``
    (0..100) scales the base XP for graded sources. ``extra_details``
    is merged into ``StreakEvent.details`` so callers can record
    auxiliary keys (e.g., ``lesson_id`` for curriculum sources).
    """
    if source not in LINEAR_XP:
        logger.warning('linear_xp: unknown source %r for user=%s', source, user_id)
        return None

    from app.achievements.models import StreakEvent
    from app.utils.db import db

    db_obj = db_session if db_session is not None else db
    when = for_date or get_linear_event_local_date(user_id, db_obj)

    if _already_awarded(user_id, source, when, db_obj):
        return None

    result = award_linear_xp(user_id, source, score=score)
    details: dict = {'source': source, 'xp': result.xp_awarded}
    if extra_details:
        details.update(extra_details)
    db_obj.session.add(StreakEvent(
        user_id=user_id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=when,
        coins_delta=0,
        details=details,
    ))
    from app.daily_plan.models import DailyPlanEvent

    # step_kind is VARCHAR(40); strip the redundant "linear_" prefix so
    # long sources (e.g. linear_curriculum_dialogue_completion_quiz, 43)
    # still fit.
    step_kind = source[len('linear_'):] if source.startswith('linear_') else source
    db_obj.session.add(DailyPlanEvent(
        user_id=user_id,
        event_type='linear_slot_completed',
        plan_date=when,
        step_kind=step_kind,
    ))

    # Accumulate study minutes for the day.
    minutes = _SOURCE_MINUTES.get(source)
    if minutes is None and source.startswith('linear_curriculum_'):
        minutes = _CURRICULUM_MINUTES
    if minutes:
        try:
            from app.curriculum.models import add_study_minutes
            add_study_minutes(user_id, when, minutes, db_obj)
        except Exception:
            logger.warning('add_study_minutes failed for user=%s source=%s', user_id, source, exc_info=True)

    db_obj.session.flush()
    return result


def maybe_award_curriculum_xp(
    user_id: int,
    lesson: Any,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
    score: Optional[float] = None,
) -> Optional[XPAward]:
    """Award linear XP for a completed curriculum lesson.

    Silent no-op when the user is not on the linear plan, the lesson
    type has no registered source, or the award was already recorded
    for today. ``score`` (0..100) scales base XP for graded lesson
    types (quiz, grammar, final test, card accuracy).
    """
    if not is_linear_user(user_id):
        return None

    source = get_source_for_lesson_type(getattr(lesson, 'type', None))
    if source is None:
        return None

    lesson_id = getattr(lesson, 'id', None)
    extra = {'lesson_id': int(lesson_id)} if lesson_id is not None else None

    return award_linear_slot_xp_idempotent(
        user_id, source, for_date, db_session, score=score,
        extra_details=extra,
    )


def maybe_award_srs_global_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for completing a /study SRS session."""
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_srs_global', for_date, db_session,
    )


def is_srs_slot_completed_today(
    user_id: int, db_session: Any, *, allow_fallback: bool = True
) -> bool:
    """Return True when the linear SRS slot is done for today.

    Primary signal: a ``StreakEvent`` with source ``linear_srs_global``
    exists for the user's local date. Fallback (Раздел 8 of
    docs/srs-fix-plan.md): if no event was recorded but the universal
    pool is exhausted AND the user clearly graded cards today (XP/event
    write must have been lost between grade and complete-session), fire
    a corrective idempotent award and return True. The award uses the
    same key as the normal path — duplicates are silently ignored.

    ``allow_fallback=False`` (deck-quiz слот) отключает fallback: общие
    SRS-счётчики поднимает и парный curriculum card-урок, который не
    должен закрывать квиз (см. компенсацию в streak_service).

    Reconciliation is a side effect of a read path; the corrective call
    only flushes (no commit), so if the caller's transaction rolls back
    the next page load triggers reconciliation again — idempotent.
    """
    from app.achievements.models import StreakEvent

    db_obj = db_session
    today = get_linear_event_local_date(user_id, db_obj)
    has_event = db_obj.session.query(
        db_obj.session.query(StreakEvent).filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.event_date == today,
            StreakEvent.details['source'].astext == 'linear_srs_global',
        ).exists()
    ).scalar() or False
    if has_event:
        return True
    if not allow_fallback:
        # Deck-quiz слот: засчитывается ТОЛЬКО по XP-событию. Fallback ниже
        # срабатывает от общих SRS-счётчиков, которые поднимает парный
        # curriculum card-урок (он же съедает бюджет → pool=0) — слот
        # закрывался бы и награждался без прохождения квиза.
        return False

    # No event — look for fallback signal.
    from app.srs.constants import CardState
    from app.srs.counting import (
        count_due_by_states,
        count_new_cards_today,
        count_pending_new,
        count_reviews_today,
        get_new_card_budget,
    )

    activity = count_reviews_today(user_id, db_obj) + count_new_cards_today(user_id, db_obj)
    if activity <= 0:
        return False

    new_pending = count_pending_new(user_id, db_obj)
    learning_due = count_due_by_states(
        user_id, db_obj,
        states=(CardState.LEARNING.value, CardState.RELEARNING.value),
    )
    review_due = count_due_by_states(
        user_id, db_obj, states=(CardState.REVIEW.value,),
    )
    remaining_new, remaining_reviews = get_new_card_budget(user_id, db_obj)
    pool = (
        min(new_pending, remaining_new)
        + learning_due
        + min(review_due, remaining_reviews)
    )
    if pool > 0:
        return False

    try:
        award_linear_slot_xp_idempotent(
            user_id, 'linear_srs_global', today, db_session=db_obj,
        )
    except Exception:
        logger.exception(
            'is_srs_slot_completed_today: corrective XP failed user=%s', user_id,
        )
    return True


def maybe_award_book_srs_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP once per day for grading a book SRS card.

    Uses a separate source key (``linear_book_srs``) so this daily slot
    does not consume the ``linear_srs_global`` budget from the free-study
    SRS session. Idempotent per (user, date) via StreakEvent. Caller commits.
    """
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_book_srs', for_date, db_session,
    )


def maybe_award_book_reading_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP when the reading slot completes for the day.

    Defends the time gate inside the helper so any future call site
    can't credit XP by simply invoking this — it requires the user to
    have a selected book AND ≥``MIN_READING_SECONDS`` of closed-session
    time today for that book. Idempotent per (user, date, source).
    """
    if not is_linear_user(user_id):
        return None

    from app.books.reading_session import has_min_reading_time_today
    from app.daily_plan.linear.slots.reading_slot import get_user_reading_preference
    from app.utils.db import db

    db_obj = db_session if db_session is not None else db

    preference = get_user_reading_preference(user_id, db_obj)
    if preference is None or preference.book_id is None:
        return None

    if not has_min_reading_time_today(user_id, int(preference.book_id), db_obj):
        return None

    # Record book_id so the reading-slot completion check is book-scoped:
    # switching the preference book mid-day must not carry the old book's
    # done-event over to the new one (_read_today filters on this).
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_book_reading', for_date, db_obj,
        extra_details={'book_id': int(preference.book_id)},
    )


def maybe_award_error_review_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for completing an error-review session."""
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_error_review', for_date, db_session,
    )


def maybe_award_grammar_review_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for doing standalone grammar-lab practice.

    Idempotent per (user, date) via StreakEvent source='linear_grammar_review'
    — once per day regardless of how many exercises are answered. Mirrors the
    grammar_review slot's ``completed`` signal (``_grammar_reviewed_today``,
    which counts any exercise reviewed today), so practising grammar from the
    daily plan credits global ``total_xp`` and grows levels. Curriculum-driven
    grammar lessons keep awarding via ``maybe_award_curriculum_xp`` on a
    separate code path (process_grammar_submission), so there is no double
    award here.
    """
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_grammar_review', for_date, db_session,
    )


def maybe_award_listening_xp(
    user_id: int,
    lesson_id: Optional[int] = None,
    score: Optional[float] = None,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for completing a listening extension slot.

    Idempotent per (user, date) via StreakEvent source='linear_listening'.
    Complements the lesson-level ``maybe_award_curriculum_xp`` award —
    this slot-level award is once per day regardless of which listening
    lesson the user completed. Returns None for non-linear users or if
    already awarded today. Caller owns the commit.
    """
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_listening', for_date, db_session, score=score,
    )


def maybe_award_writing_xp(
    user_id: int,
    lesson_id: Optional[int] = None,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for completing a writing extension slot.

    Idempotent per (user, date) via StreakEvent source='linear_writing'.
    Complements the lesson-level ``maybe_award_curriculum_xp`` award —
    this slot-level award fires once per day regardless of which writing
    lesson the user completed. Returns None for non-linear users or if
    already awarded today. Caller owns the commit.
    """
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_writing', for_date, db_session,
    )


def maybe_record_linear_plan_completion(
    user_id: int,
    plan: dict,
    plan_completion: dict,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Any:
    """Record plan-completion + rank-up for a linear user when day is secured.

    Returns the ``RankUp`` produced by ``record_plan_completion`` (or ``None``
    when no threshold was crossed / the call was a duplicate). Idempotent:
    ``record_plan_completion`` dedups via ``StreakEvent('plan_completed')``
    per (user, date), so repeated invocations on the same day are a no-op.
    Caller owns the commit — this helper only flushes.
    """
    if not is_linear_user(user_id):
        return None

    baseline_slots = plan.get('baseline_slots') or []
    if not baseline_slots:
        return None
    all_done = all(
        plan_completion.get(slot.get('kind', ''), False)
        for slot in baseline_slots
    )
    if not all_done:
        return None

    from app.achievements.ranks import record_plan_completion
    from app.utils.db import db

    db_obj = db_session if db_session is not None else db
    when = for_date or get_linear_event_local_date(user_id, db_obj)

    rank_up = record_plan_completion(user_id, for_date=when)
    db_obj.session.flush()
    if rank_up is not None:
        try:
            from app.notifications.services import notify_rank_up
            notify_rank_up(user_id, rank_up.new_name)
        except Exception:
            logger.warning(
                "Failed to send rank-up notification for linear user %s",
                user_id, exc_info=True,
            )
    return rank_up


def maybe_award_linear_perfect_day(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award the perfect-day bonus when the UNIFIED plan's required is done.

    Бонус считается по тому же плану, который видит пользователь
    (``get_daily_plan_unified``), и тем же предикатом, что ``day_secured``
    (``compute_day_secured_from_activity``). Раньше здесь собирался legacy
    linear-план (``get_linear_plan``): наборы слотов расходились с unified
    (reading безусловно, 5 слотов без капа против 4 required), и бонус для
    части конфигураций был недостижим — либо, наоборот, выдавался без
    закрытия видимого плана.
    """
    if not is_linear_user(user_id):
        return None

    from app.achievements.streak_service import compute_plan_steps
    from app.daily_plan.service import (
        compute_day_secured_from_activity,
        get_daily_plan_unified,
    )
    from app.telegram.queries import get_daily_summary

    when = for_date or get_linear_event_local_date(user_id, db_session)
    tz = _get_user_timezone(user_id, db_session)

    try:
        plan = get_daily_plan_unified(user_id, tz=tz)
        summary = get_daily_summary(user_id, tz=tz)
    except Exception:  # noqa: BLE001 — never break caller on plan assembly
        logger.warning(
            'linear_xp: perfect-day check failed to assemble plan for user=%s',
            user_id, exc_info=True,
        )
        return None

    plan_meta = plan.get('_plan_meta') or {}
    if plan_meta.get('effective_mode') == 'paused':
        return None
    if not (plan.get('required') or []) and not plan_meta.get('graduated'):
        return None

    plan_completion, _, _, _ = compute_plan_steps(plan, summary)
    if not compute_day_secured_from_activity(plan, plan_completion):
        return None

    return award_perfect_day_xp_idempotent(user_id, when, is_linear=True)
