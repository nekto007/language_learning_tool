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
from typing import Any, Optional

from app.daily_plan.items import PlanItem

logger = logging.getLogger(__name__)

_GRAMMAR_REVIEW_ETA_MINUTES = 10


def build_grammar_review_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    """Return a grammar_review PlanItem or None when no topics exist."""
    from app.grammar_lab.models import GrammarTopic

    topic = _stalest_practiced_topic(user_id, db)
    if topic is None:
        topic = _level_fallback_topic(user_id, db, GrammarTopic)
    if topic is None:
        return None

    url = f'/grammar-lab/topic/{topic.slug}'

    return PlanItem(
        id=f'grammar_review:topic:{topic.id}',
        section=section,  # type: ignore[arg-type]
        kind='grammar_review',
        title=topic.title,
        subtitle=f'{topic.level} · повторение грамматики',
        lesson_type=None,
        eta_minutes=_GRAMMAR_REVIEW_ETA_MINUTES,
        url=url,
        completed=False,
        completion_signal='none',
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

    row = (
        db.session.query(
            GrammarTopic,
            func.max(UserGrammarExercise.last_reviewed).label('latest_review'),
        )
        .join(GrammarExercise, GrammarExercise.topic_id == GrammarTopic.id)
        .join(UserGrammarExercise, UserGrammarExercise.exercise_id == GrammarExercise.id)
        .filter(
            UserGrammarExercise.user_id == user_id,
            GrammarTopic.level.in_(PUBLIC_CEFR_CODES),
        )
        .group_by(GrammarTopic.id)
        .order_by(func.max(UserGrammarExercise.last_reviewed).asc().nullsfirst())
        .first()
    )
    return row[0] if row is not None else None


def _level_fallback_topic(user_id: int, db: Any, GrammarTopic: Any) -> Optional[Any]:
    """Return the first topic at the user's CEFR level, or any public topic globally."""
    from app.auth.models import User
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES

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
