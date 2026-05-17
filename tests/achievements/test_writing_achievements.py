"""Tests for writing achievement badges (Task 23).

Covers:
- writing_first: granted on first UserWritingAttempt
- writing_streak_3: granted after 3 consecutive days with writing attempts
- writing_fluent: granted when any attempt has word_count >= 100
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import check_writing_achievements
from app.achievements.streak_service import get_writing_streak
from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module, UserWritingAttempt
from app.study.models import Achievement, UserAchievement


WRITING_BADGE_CODES = {'writing_first', 'writing_streak_3', 'writing_fluent'}


@pytest.fixture
def writing_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'wrt_{suffix}',
        email=f'wrt_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def writing_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(WRITING_BADGE_CODES)).all()
    assert len(badges) == len(WRITING_BADGE_CODES), (
        f"Expected {len(WRITING_BADGE_CODES)} badges, got {len(badges)}"
    )
    return {b.code: b for b in badges}


@pytest.fixture
def writing_lesson(db_session):
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Beginner', order=1)
        db_session.add(level)
        db_session.flush()
    module = Module(
        level_id=level.id,
        number=1,
        title='WR Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Writing Lesson',
        type='writing_prompt',
        content={'prompt': 'Write something.', 'min_words': 10},
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


def _add_attempt(db_session, user_id: int, lesson_id: int, text: str = 'hello world',
                 created_at=None) -> UserWritingAttempt:
    now = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    attempt = UserWritingAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        response_text=text,
        word_count=len(text.split()),
        checklist_completed=True,
        created_at=now,
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


class TestWritingFirst:
    def test_first_attempt_grants_badge(self, db_session, writing_user, writing_badges, writing_lesson):
        _add_attempt(db_session, writing_user.id, writing_lesson.id)
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_first' in codes

    def test_already_owned_not_regranted(self, db_session, writing_user, writing_badges, writing_lesson):
        _add_attempt(db_session, writing_user.id, writing_lesson.id)
        check_writing_achievements(writing_user.id, db_session=db_session)
        awarded2 = check_writing_achievements(writing_user.id, db_session=db_session)
        assert 'writing_first' not in {a.code for a in awarded2}

    def test_no_attempts_no_badge(self, db_session, writing_user, writing_badges):
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        assert awarded == []


class TestWritingStreak3:
    def test_three_consecutive_days_grants_badge(self, db_session, writing_user, writing_badges, writing_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(3):
            _add_attempt(db_session, writing_user.id, writing_lesson.id,
                         created_at=now - timedelta(days=offset))
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_streak_3' in codes

    def test_two_days_no_badge(self, db_session, writing_user, writing_badges, writing_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(2):
            _add_attempt(db_session, writing_user.id, writing_lesson.id,
                         created_at=now - timedelta(days=offset))
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_streak_3' not in codes

    def test_gap_breaks_streak(self, db_session, writing_user, writing_badges, writing_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # days 0, 1, 3 — gap on day 2
        for offset in (0, 1, 3):
            _add_attempt(db_session, writing_user.id, writing_lesson.id,
                         created_at=now - timedelta(days=offset))
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_streak_3' not in codes


class TestWritingFluent:
    def test_100_words_grants_badge(self, db_session, writing_user, writing_badges, writing_lesson):
        long_text = ' '.join(['word'] * 100)
        _add_attempt(db_session, writing_user.id, writing_lesson.id, text=long_text)
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_fluent' in codes

    def test_99_words_no_badge(self, db_session, writing_user, writing_badges, writing_lesson):
        short_text = ' '.join(['word'] * 99)
        _add_attempt(db_session, writing_user.id, writing_lesson.id, text=short_text)
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_fluent' not in codes

    def test_exactly_100_words_grants_badge(self, db_session, writing_user, writing_badges, writing_lesson):
        text = ' '.join(['word'] * 100)
        _add_attempt(db_session, writing_user.id, writing_lesson.id, text=text)
        awarded = check_writing_achievements(writing_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'writing_fluent' in codes


class TestGetWritingStreak:
    def test_no_attempts_streak_zero(self, db_session, writing_user):
        assert get_writing_streak(writing_user.id, db_session=db_session) == 0

    def test_three_consecutive_days(self, db_session, writing_user, writing_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(3):
            _add_attempt(db_session, writing_user.id, writing_lesson.id,
                         created_at=now - timedelta(days=offset))
        assert get_writing_streak(writing_user.id, db_session=db_session) == 3

    def test_gap_resets_streak(self, db_session, writing_user, writing_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Only day 0 and day 2 — streak from today is 1 (yesterday is missing)
        for offset in (0, 2):
            _add_attempt(db_session, writing_user.id, writing_lesson.id,
                         created_at=now - timedelta(days=offset))
        assert get_writing_streak(writing_user.id, db_session=db_session) == 1
