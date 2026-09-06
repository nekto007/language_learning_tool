"""Tier selection for the static daily-plan v2 snapshot.

Covers the 7-day window thresholds (calm=<3 secured, intensive=>=5
secured + >=3 days with optional activity) and the final_test override
that forces calm regardless of metrics.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.achievements.models import StreakEvent
from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.models import DailyPlanLog
from app.daily_plan.tier import (
    OPTIONAL_HIGH,
    SECURED_HIGH,
    SECURED_LOW,
    WINDOW_DAYS,
    compute_user_tier,
)
from app.utils.db import db as real_db
from tests.conftest import unique_level_code
from tests.support_dates import study_today


@pytest.fixture
def user(db_session):
    suffix = uuid.uuid4().hex[:10]
    u = User(
        username=f'tier_{suffix}',
        email=f'tier_{suffix}@example.com',
        active=True,
    )
    u.set_password('secret123')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def vocabulary_lesson(db_session):
    """Stable next-lesson on the spine (vocabulary, not final_test)."""
    code = unique_level_code()
    level = CEFRLevel(
        code=code,
        name=f'L-{code}',
        order=1,
    )
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='M1', description='', raw_content={})
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id, number=1, title='L1', type='vocabulary', content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _seed_secured_days(user_id: int, today: date, n: int, db_session) -> None:
    """Mark ``n`` past days in the 7-day window as secured."""
    for offset in range(1, n + 1):
        plan_date = today - timedelta(days=offset)
        db_session.add(DailyPlanLog(
            user_id=user_id,
            plan_date=plan_date,
            secured_at=datetime(2026, 1, 1, 12),
        ))
    db_session.commit()


def _seed_optional_days(user_id: int, today: date, n: int, db_session) -> None:
    """Emit StreakEvents with an optional source on ``n`` past days."""
    for offset in range(1, n + 1):
        plan_date = today - timedelta(days=offset)
        db_session.add(StreakEvent(
            user_id=user_id,
            event_type='xp_linear',
            event_date=plan_date,
            details={'source': 'linear_grammar_review', 'xp': 10},
            created_at=datetime(2026, 1, 1, 12),
        ))
    db_session.commit()


class TestTierSelection:
    """Item 14: the tier is the learner's explicit pace; the secured-day ladder is gone."""

    def test_light_pace_gives_calm(self, db_session, user, vocabulary_lesson):
        user.plan_difficulty = 'light'
        db_session.commit()
        assert compute_user_tier(user.id, real_db) == 'calm'

    def test_default_pace_is_normal(self, db_session, user, vocabulary_lesson):
        assert user.plan_difficulty == 'normal'
        assert compute_user_tier(user.id, real_db) == 'normal'

    def test_intensive_pace_gives_intensive(self, db_session, user, vocabulary_lesson):
        user.plan_difficulty = 'intensive'
        db_session.commit()
        assert compute_user_tier(user.id, real_db) == 'intensive'

    def test_secured_and_optional_days_no_longer_move_the_tier(self, db_session, user, vocabulary_lesson):
        today = study_today(user.id)
        _seed_secured_days(user.id, today, SECURED_HIGH + 1, db_session)
        _seed_optional_days(user.id, today, WINDOW_DAYS, db_session)
        user.plan_difficulty = 'light'
        db_session.commit()
        assert compute_user_tier(user.id, real_db) == 'calm'
        user.plan_difficulty = 'normal'
        db_session.commit()
        assert compute_user_tier(user.id, real_db) == 'normal'

    def test_unknown_difficulty_falls_back_to_normal(self, db_session, user, vocabulary_lesson):
        user.plan_difficulty = 'weird'
        db_session.commit()
        assert compute_user_tier(user.id, real_db) == 'normal'

    def test_final_test_forces_calm(self, db_session, user):
        """A final_test next on the spine keeps the day to one curriculum slot."""
        code = unique_level_code()
        level = CEFRLevel(code=code, name=f'L-{code}', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M1', description='', raw_content={})
        db_session.add(module)
        db_session.commit()
        db_session.add(Lessons(module_id=module.id, number=1, title='FT', type='final_test', content={}))
        db_session.commit()
        user.plan_difficulty = 'intensive'
        db_session.commit()
        assert compute_user_tier(user.id, real_db) == 'calm'
