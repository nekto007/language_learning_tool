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
from datetime import datetime, timedelta
from typing import Any, Optional

from app.daily_plan.items import PlanItem

logger = logging.getLogger(__name__)

_GRAMMAR_REVIEW_ETA_MINUTES = 10


def _grammar_reviewed_today(user_id: int, db: Any) -> bool:
    """Return True when the user completed any grammar exercise today."""
    from app.daily_plan.linear.xp import get_linear_event_local_date
    from app.grammar_lab.models import UserGrammarExercise

    today = get_linear_event_local_date(user_id, db)
    today_start = datetime.combine(today, datetime.min.time())
    today_end = today_start + timedelta(days=1)
    query = db.session.query(UserGrammarExercise).filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
        UserGrammarExercise.last_reviewed < today_end,
    )
    return db.session.query(query.exists()).scalar() or False


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

    url = f'/grammar-lab/topic/{topic.slug}'
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
    """Return the topic whose exercises were reviewed longest ago by this user."""
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
    from sqlalchemy import func

    # Group by a scalar column only to avoid PostgreSQL full-GROUP-BY requirement.
    row = (
        db.session.query(
            GrammarExercise.topic_id,
            func.max(UserGrammarExercise.last_reviewed).label('latest_review'),
        )
        .join(UserGrammarExercise, UserGrammarExercise.exercise_id == GrammarExercise.id)
        .join(GrammarTopic, GrammarTopic.id == GrammarExercise.topic_id)
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed.isnot(None),
            GrammarTopic.level.in_(PUBLIC_CEFR_CODES),
        )
        .group_by(GrammarExercise.topic_id)
        .order_by(func.max(UserGrammarExercise.last_reviewed).asc().nullsfirst())
        .first()
    )
    if row is None:
        return None
    return db.session.get(GrammarTopic, row.topic_id)


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
