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

    def test_calm_when_few_secured_days(self, db_session, user, vocabulary_lesson):
        # 0 secured days in the past 7 → calm.
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'calm'

    def test_calm_when_below_secured_low_threshold(self, db_session, user, vocabulary_lesson):
        # SECURED_LOW - 1 secured days → still calm.
        today = date.today()
        _seed_secured_days(user.id, today, SECURED_LOW - 1, db_session)
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'calm'

    def test_normal_at_secured_low(self, db_session, user, vocabulary_lesson):
        # SECURED_LOW secured days, no optional → normal.
        today = date.today()
        _seed_secured_days(user.id, today, SECURED_LOW, db_session)
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'normal'

    def test_normal_when_high_secured_but_no_optional(
        self, db_session, user, vocabulary_lesson,
    ):
        # Many secured days but zero optional activity → still normal.
        today = date.today()
        _seed_secured_days(user.id, today, SECURED_HIGH, db_session)
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'normal'

    def test_intensive_when_high_secured_and_optional(
        self, db_session, user, vocabulary_lesson,
    ):
        today = date.today()
        _seed_secured_days(user.id, today, SECURED_HIGH, db_session)
        _seed_optional_days(user.id, today, OPTIONAL_HIGH, db_session)
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'intensive'

    def test_intensive_requires_both_thresholds(
        self, db_session, user, vocabulary_lesson,
    ):
        # SECURED_HIGH secured but OPTIONAL_HIGH-1 optional days → not intensive.
        today = date.today()
        _seed_secured_days(user.id, today, SECURED_HIGH, db_session)
        _seed_optional_days(user.id, today, OPTIONAL_HIGH - 1, db_session)
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'normal'

    def test_final_test_forces_calm(self, db_session, user):
        """final_test as next spine lesson → calm even when metrics scream intensive."""
        code = unique_level_code()
        level = CEFRLevel(
            code=code, name=f'L-{code}', order=1,
        )
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M1', description='', raw_content={})
        db_session.add(module)
        db_session.commit()
        ft = Lessons(
            module_id=module.id, number=1, title='Final', type='final_test', content={},
        )
        db_session.add(ft)
        db_session.commit()

        today = date.today()
        _seed_secured_days(user.id, today, SECURED_HIGH + 2, db_session)
        _seed_optional_days(user.id, today, OPTIONAL_HIGH + 2, db_session)

        tier = compute_user_tier(user.id, real_db)
        assert tier == 'calm'

    def test_today_secured_does_not_count(self, db_session, user, vocabulary_lesson):
        """Tier window is yesterday-and-back; today is excluded.

        The tier shapes today's plan, so today's secured state is not
        yet observable when ``compute_user_tier`` runs (and counting it
        would create a tautology).
        """
        today = date.today()
        # Add today's row as secured — should be ignored.
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=today,
            secured_at=datetime(2026, 1, 1, 12),
        ))
        # And enough yesterday-and-back to JUST hit calm boundary.
        _seed_secured_days(user.id, today, SECURED_LOW - 1, db_session)
        db_session.commit()
        tier = compute_user_tier(user.id, real_db)
        assert tier == 'calm'

    def test_outside_window_does_not_count(self, db_session, user, vocabulary_lesson):
        """Secured days older than WINDOW_DAYS are ignored."""
        today = date.today()
        old = today - timedelta(days=WINDOW_DAYS + 1)
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=old,
            secured_at=datetime(2026, 1, 1, 12),
        ))
        db_session.commit()
        tier = compute_user_tier(user.id, real_db)
        # Still calm: the one old secured day is outside the window.
        assert tier == 'calm'
