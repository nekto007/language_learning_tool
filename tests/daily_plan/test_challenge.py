"""Tests for the daily challenge system (Task 83).

Covers:
- challenge seeded deterministically for a given date
- same challenge returned for all users on same day
- challenge seeded only once (idempotent)
- listening_deep category attaches a dictation lesson
- completion tracked per user
- complete_challenge is idempotent (second call returns already_completed=True)
- get_today_challenge reflects completion status after completion
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.daily_plan.models import (
    CHALLENGE_CATEGORIES,
    DailyChallenge,
    DailyChallengeCompletion,
)
from app.daily_plan.challenge import (
    CHALLENGE_CATEGORIES as SERVICE_CATEGORIES,
    _seed_today_challenge,
    complete_challenge,
    get_today_challenge,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_user(db_session):
    from app.auth.models import User
    uid = uuid.uuid4().hex[:8]
    user = User(username=f'ch_{uid}', email=f'ch_{uid}@example.com', active=True)
    user.set_password('secret')
    db_session.add(user)
    db_session.commit()
    return user


def _make_dictation_lesson(db_session):
    from app.curriculum.models import CEFRLevel, Lessons, Module
    uid = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=uid, name='Test', description='d', order=99)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=99, title='M', description='d', raw_content={})
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(module_id=module.id, number=1, title='Dictation Lesson', type='dictation', content={})
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ── seeding ───────────────────────────────────────────────────────────────────


class TestSeedChallenge:
    def test_challenge_seeded_for_date(self, db_session):
        from app.utils.db import db
        test_date = date(2026, 6, 1)
        day_idx = test_date.toordinal() % 3
        expected_category = CHALLENGE_CATEGORIES[day_idx]

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.id is not None
        assert challenge.challenge_date == test_date
        assert challenge.category == expected_category
        assert challenge.bonus_xp > 0

    def test_category_is_deterministic(self, db_session):
        from app.utils.db import db
        test_date = date(2026, 6, 2)
        day_idx = test_date.toordinal() % 3
        expected = CHALLENGE_CATEGORIES[day_idx]

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category == expected

    def test_all_categories_present_in_service(self):
        assert set(SERVICE_CATEGORIES) == {'speed_run', 'accuracy_focus', 'listening_deep'}

    def test_listening_deep_attaches_dictation_lesson(self, db_session):
        from app.utils.db import db

        # Find a date that maps to listening_deep (index 2)
        test_date = date(2026, 6, 1)
        while test_date.toordinal() % 3 != 2:
            test_date += timedelta(days=1)

        lesson = _make_dictation_lesson(db_session)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category == 'listening_deep'
        assert challenge.lesson_id == lesson.id

    def test_non_listening_category_has_no_lesson(self, db_session):
        from app.utils.db import db

        # Find a date that maps to speed_run (index 0) or accuracy_focus (index 1)
        test_date = date(2026, 6, 1)
        while test_date.toordinal() % 3 == 2:
            test_date += timedelta(days=1)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category != 'listening_deep'
        assert challenge.lesson_id is None


# ── get_today_challenge ────────────────────────────────────────────────────────


class TestGetTodayChallenge:
    def test_returns_challenge_dict(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        result = get_today_challenge(user.id, db)

        assert result['challenge_date'] == date.today().isoformat()
        assert result['category'] in SERVICE_CATEGORIES
        assert result['bonus_xp'] > 0
        assert result['is_completed'] is False
        assert result['completion'] is None

    def test_same_challenge_for_all_users(self, db_session):
        from app.utils.db import db
        user1 = _make_user(db_session)
        user2 = _make_user(db_session)

        result1 = get_today_challenge(user1.id, db)
        result2 = get_today_challenge(user2.id, db)

        assert result1['id'] == result2['id']
        assert result1['challenge_date'] == result2['challenge_date']
        assert result1['category'] == result2['category']

    def test_challenge_seeded_only_once(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        get_today_challenge(user.id, db)
        get_today_challenge(user.id, db)

        today = date.today()
        count = DailyChallenge.query.filter_by(challenge_date=today).count()
        assert count == 1


# ── complete_challenge ────────────────────────────────────────────────────────


class TestCompleteChallenge:
    def test_completion_tracked(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        result = complete_challenge(user.id, challenge_id, score=95.0, time_spent_seconds=180, db=db)
        db_session.commit()

        assert result['already_completed'] is False
        assert result['bonus_xp'] == challenge_data['bonus_xp']

        stored = DailyChallengeCompletion.query.filter_by(
            challenge_id=challenge_id,
            user_id=user.id,
        ).first()
        assert stored is not None
        assert stored.score == 95.0
        assert stored.time_spent_seconds == 180

    def test_complete_challenge_idempotent(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user.id, challenge_id, score=80.0, time_spent_seconds=200, db=db)
        db_session.commit()
        result2 = complete_challenge(user.id, challenge_id, score=90.0, time_spent_seconds=100, db=db)

        assert result2['already_completed'] is True
        count = DailyChallengeCompletion.query.filter_by(
            challenge_id=challenge_id,
            user_id=user.id,
        ).count()
        assert count == 1

    def test_get_today_challenge_shows_completed(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user.id, challenge_id, score=75.0, time_spent_seconds=250, db=db)
        db_session.commit()

        refreshed = get_today_challenge(user.id, db)
        assert refreshed['is_completed'] is True
        assert refreshed['completion']['score'] == 75.0

    def test_different_users_have_independent_completion(self, db_session):
        from app.utils.db import db
        user1 = _make_user(db_session)
        user2 = _make_user(db_session)
        challenge_data = get_today_challenge(user1.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user1.id, challenge_id, score=88.0, time_spent_seconds=120, db=db)
        db_session.commit()

        user1_data = get_today_challenge(user1.id, db)
        user2_data = get_today_challenge(user2.id, db)

        assert user1_data['is_completed'] is True
        assert user2_data['is_completed'] is False


# ── challenge card data (Task 84) ─────────────────────────────────────────────


class TestChallengeCardData:
    """Verify the data structure returned by get_today_challenge is
    sufficient for rendering the daily-challenge-card in the template."""

    def test_card_data_uncompleted_has_gold_badge_fields(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        data = get_today_challenge(user.id, db)

        # Card should show when is_completed=False
        assert data['is_completed'] is False
        # bonus_xp present and positive — drives "2x XP" badge display
        assert 'bonus_xp' in data
        assert data['bonus_xp'] > 0
        # category present for description lookup
        assert data['category'] in ('speed_run', 'accuracy_focus', 'listening_deep')

    def test_card_data_completed_shows_done_state(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        data = get_today_challenge(user.id, db)
        challenge_id = data['id']

        complete_challenge(user.id, challenge_id, score=92.0, time_spent_seconds=200, db=db)
        db_session.commit()

        refreshed = get_today_challenge(user.id, db)
        # Card should render in greyed/done state
        assert refreshed['is_completed'] is True
        # completion details available for "+ N XP" label
        assert refreshed['completion'] is not None
        assert refreshed['completion']['score'] == 92.0

    def test_bonus_xp_values_per_category(self, db_session):
        from app.utils.db import db
        from app.daily_plan.challenge import _BONUS_XP

        # Each category must have a positive bonus_xp used for "2x XP" display
        for cat in ('speed_run', 'accuracy_focus', 'listening_deep'):
            assert cat in _BONUS_XP
            assert _BONUS_XP[cat] > 0

    def test_listening_deep_has_lesson_id_for_direct_link(self, db_session):
        from app.utils.db import db
        import datetime

        _make_dictation_lesson(db_session)

        # Find a date that maps to listening_deep (index 2)
        test_date = datetime.date(2026, 7, 1)
        while test_date.toordinal() % 3 != 2:
            test_date += datetime.timedelta(days=1)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category == 'listening_deep'
        # lesson_id populated → template renders direct link to lesson
        assert challenge.lesson_id is not None

    def test_non_listening_challenge_has_no_lesson_id(self, db_session):
        from app.utils.db import db
        import datetime

        # Find a date that maps to speed_run or accuracy_focus
        test_date = datetime.date(2026, 7, 1)
        while test_date.toordinal() % 3 == 2:
            test_date += datetime.timedelta(days=1)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        # lesson_id=None → template falls back to first incomplete slot URL
        assert challenge.lesson_id is None
