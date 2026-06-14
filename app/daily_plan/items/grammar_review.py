"""Grammar review item builder for the unified daily plan.

Surfaces a GrammarTopic for optional review.

For users with grammar exercise history, picks the topic whose exercises
were reviewed longest ago (stalest ``last_reviewed`` across
``UserGrammarExercise`` rows for that topic). For users with no history,
falls back to the first topic at the user's CEFR level, or globally if
no level-specific topics exist.

Returns None only when no GrammarTopic rows exist at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.daily_plan.items import PlanItem

logger = logging.getLogger(__name__)

_GRAMMAR_REVIEW_ETA_MINUTES = 10


def _grammar_reviewed_today(user_id: int, db: Any) -> bool:
    """Return True when the user did any grammar practice today.

    Unions two sources so the slot flips regardless of *how* grammar was
    practised:
    - standalone grammar-lab (``UserGrammarExercise.last_reviewed``)
    - curriculum grammar lessons (``LessonAttempt`` on ``type='grammar'``
      lessons), which write LessonProgress/LessonAttempt, NOT UserGrammarExercise.

    ``UserGrammarExercise.last_reviewed`` is a naive UTC column, so the
    user-local day must be translated to a UTC window before comparison —
    otherwise a non-UTC user practising near local midnight is either
    missed (review fell into yesterday-UTC) or credited on the wrong day.
    """
    from app.grammar_lab.models import UserGrammarExercise
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
    # Compare against the naive UTC column in its native form.
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    query = db.session.query(UserGrammarExercise).filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= start_utc,
        UserGrammarExercise.last_reviewed < end_utc,
    )
    if db.session.query(query.exists()).scalar():
        return True

    # Curriculum grammar lessons write LessonAttempt (naive UTC completed_at),
    # not UserGrammarExercise. Any grammar attempt today counts as practice —
    # correctness-agnostic, matching the standalone signal above.
    from app.curriculum.models import LessonAttempt, Lessons

    curric_query = (
        db.session.query(LessonAttempt.id)
        .join(Lessons, Lessons.id == LessonAttempt.lesson_id)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.completed_at.isnot(None),
            LessonAttempt.completed_at >= start_utc,
            LessonAttempt.completed_at < end_utc,
            Lessons.type == 'grammar',
        )
    )
    return db.session.query(curric_query.exists()).scalar() or False


def build_grammar_review_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    """Return a grammar_review PlanItem or None when no topics exist."""
    topic = _stalest_practiced_topic(user_id, db)
    if topic is None:
        topic = _level_fallback_topic(user_id, db)
    if topic is None:
        return None

    # Grammar review = doing exercises, not reading theory. Point straight
    # at /practice/topic/<id> so "Следующий шаг" from the daily plan lands
    # on the practice queue instead of the topic detail page (Bug #1).
    url = f'/grammar-lab/practice/topic/{topic.id}'
    completed = _grammar_reviewed_today(user_id, db)

    return PlanItem(
        id=f'grammar_review:topic:{topic.id}',
        section=section,  # type: ignore[arg-type]
        kind='grammar_review',
        title=topic.title,
        subtitle=f'{topic.level} · повторение грамматики',
        lesson_type=None,
        eta_minutes=0 if completed else _GRAMMAR_REVIEW_ETA_MINUTES,
        url=url,
        completed=completed,
        completion_signal='grammar_exercises',
        data={
            'topic_id': topic.id,
            'topic_slug': topic.slug,
            'topic_title': topic.title,
            'topic_title_ru': topic.title_ru,
            'topic_level': topic.level,
        },
    )


def _stalest_practiced_topic(user_id: int, db: Any) -> Optional[Any]:
    """Return the topic practised longest ago by this user.

    Unions standalone grammar-lab practice (``UserGrammarExercise.last_reviewed``)
    with curriculum grammar lessons (``LessonAttempt.completed_at`` joined to the
    lesson's ``grammar_topic_id``) so a user who only does course grammar still
    gets their stalest topic surfaced. Both columns are naive UTC; merged in
    Python and the topic with the oldest most-recent practice wins.
    """
    from sqlalchemy import func

    from app.curriculum.models import LessonAttempt, Lessons
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise

    latest_by_topic: dict[int, datetime] = {}

    def _merge(topic_id: Optional[int], ts: Optional[datetime]) -> None:
        if topic_id is None or ts is None:
            return
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        prev = latest_by_topic.get(int(topic_id))
        if prev is None or ts > prev:
            latest_by_topic[int(topic_id)] = ts

    standalone_rows = (
        db.session.query(
            GrammarExercise.topic_id,
            func.max(UserGrammarExercise.last_reviewed),
        )
        .join(UserGrammarExercise, UserGrammarExercise.exercise_id == GrammarExercise.id)
        .join(GrammarTopic, GrammarTopic.id == GrammarExercise.topic_id)
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed.isnot(None),
            GrammarTopic.level.in_(PUBLIC_CEFR_CODES),
        )
        .group_by(GrammarExercise.topic_id)
        .all()
    )
    for topic_id, ts in standalone_rows:
        _merge(topic_id, ts)

    curriculum_rows = (
        db.session.query(
            Lessons.grammar_topic_id,
            func.max(LessonAttempt.completed_at),
        )
        .join(Lessons, Lessons.id == LessonAttempt.lesson_id)
        .join(GrammarTopic, GrammarTopic.id == Lessons.grammar_topic_id)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.completed_at.isnot(None),
            Lessons.type == 'grammar',
            Lessons.grammar_topic_id.isnot(None),
            GrammarTopic.level.in_(PUBLIC_CEFR_CODES),
        )
        .group_by(Lessons.grammar_topic_id)
        .all()
    )
    for topic_id, ts in curriculum_rows:
        _merge(topic_id, ts)

    if not latest_by_topic:
        return None
    stalest_topic_id = min(latest_by_topic, key=lambda tid: latest_by_topic[tid])
    return db.session.get(GrammarTopic, stalest_topic_id)


def _level_fallback_topic(user_id: int, db: Any) -> Optional[Any]:
    """Return the first topic at the user's CEFR level, or any public topic globally."""
    from app.auth.models import User
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.grammar_lab.models import GrammarTopic

    user = db.session.get(User, user_id)
    level_code = getattr(user, 'onboarding_level', None) if user is not None else None

    if level_code and level_code in PUBLIC_CEFR_CODES:
        topic = (
            db.session.query(GrammarTopic)
            .filter(GrammarTopic.level == level_code)
            .order_by(GrammarTopic.order.asc())
            .first()
        )
        if topic is not None:
            return topic

    return (
        db.session.query(GrammarTopic)
        .filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
        .order_by(GrammarTopic.id.asc())
        .first()
    )
