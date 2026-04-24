"""Tests for the canonical idempotent grant_achievement helper."""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.achievements.services import grant_achievement
from app.auth.models import User
from app.study.models import Achievement, UserAchievement


@pytest.fixture
def user(db_session):
    suffix = uuid.uuid4().hex[:8]
    u = User(
        username=f'grant_{suffix}',
        email=f'grant_{suffix}@test.com',
        active=True,
    )
    u.set_password('test123')
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
def achievement(db_session):
    suffix = uuid.uuid4().hex[:8]
    ach = Achievement(
        code=f'test_ach_{suffix}',
        name='Test',
        icon='🏅',
        category='test',
        xp_reward=0,
    )
    db_session.add(ach)
    db_session.flush()
    return ach


class TestGrantAchievement:
    def test_first_grant_returns_is_new_true(self, db_session, user, achievement):
        ua, is_new = grant_achievement(user.id, achievement.id)
        assert is_new is True
        assert ua.user_id == user.id
        assert ua.achievement_id == achievement.id

    def test_second_grant_returns_existing(self, db_session, user, achievement):
        ua1, is_new1 = grant_achievement(user.id, achievement.id)
        db_session.flush()
        ua2, is_new2 = grant_achievement(user.id, achievement.id)
        assert is_new1 is True
        assert is_new2 is False
        assert ua2.id == ua1.id

        count = UserAchievement.query.filter_by(
            user_id=user.id, achievement_id=achievement.id,
        ).count()
        assert count == 1

    def test_race_condition_integrity_error_handled(
        self, db_session, user, achievement,
    ):
        """Simulate a concurrent writer inserting between dupe-check and insert.

        We patch the first filter_by call to report "not existing" even though
        another session already wrote the row (done in-session here by adding
        directly). The nested-savepoint insert hits the UniqueConstraint, and
        grant_achievement must swallow the IntegrityError and return the
        existing row.
        """
        # Pre-create the row as if another transaction committed it first
        pre_existing = UserAchievement(
            user_id=user.id, achievement_id=achievement.id,
        )
        db_session.add(pre_existing)
        db_session.flush()

        original_filter_by = UserAchievement.query.filter_by
        call_count = {'n': 0}

        def fake_filter_by(**kwargs):
            q = original_filter_by(**kwargs)
            # Force the FIRST dupe-check to report empty, so grant_achievement
            # proceeds to insert and trips the unique constraint.
            call_count['n'] += 1
            if call_count['n'] == 1:
                class _Empty:
                    def first(self_inner):
                        return None
                return _Empty()
            return q

        with patch.object(UserAchievement, 'query') as mock_query:
            mock_query.filter_by = fake_filter_by
            ua, is_new = grant_achievement(user.id, achievement.id)

        assert is_new is False
        assert ua.id == pre_existing.id

        count = UserAchievement.query.filter_by(
            user_id=user.id, achievement_id=achievement.id,
        ).count()
        assert count == 1
