"""Tests for listening achievement badges (Task 13).

Covers:
- listening_first: granted on first ListeningAttempt
- listening_week: granted when listening streak >= 7 days
- listening_master: granted when avg score >= 90% over last 10 dictations
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import check_listening_achievements
from app.auth.models import User
from app.curriculum.models import ListeningAttempt, Lessons
from app.curriculum.models import Module
from app.study.models import Achievement, UserAchievement


LISTENING_BADGE_CODES = {'listening_first', 'listening_week', 'listening_master'}


@pytest.fixture
def listening_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'lstn_{suffix}',
        email=f'lstn_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def listening_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(LISTENING_BADGE_CODES)).all()
    assert len(badges) == len(LISTENING_BADGE_CODES), (
        f"Expected {len(LISTENING_BADGE_CODES)} badges, got {len(badges)}"
    )
    return {b.code: b for b in badges}


@pytest.fixture
def dictation_lesson(db_session):
    from app.curriculum.models import CEFRLevel
    level = CEFRLevel(code='A1', name='Beginner', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(
        level_id=level.id,
        number=1,
        title='TestModule',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Dictation Lesson',
        type='dictation',
        content={'audio_url': '/a.mp3', 'transcript': 'hello world'},
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


def _add_attempt(db_session, user_id, lesson_id, score, created_at=None):
    now = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    attempt = ListeningAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        score=float(score),
        replay_count=0,
        created_at=now,
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


class TestListeningFirst:
    def test_first_attempt_grants_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        _add_attempt(db_session, listening_user.id, dictation_lesson.id, 85.0)
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_first' in codes

    def test_already_owned_not_regranted(self, db_session, listening_user, listening_badges, dictation_lesson):
        _add_attempt(db_session, listening_user.id, dictation_lesson.id, 85.0)
        check_listening_achievements(listening_user.id, db_session=db_session)
        awarded2 = check_listening_achievements(listening_user.id, db_session=db_session)
        assert 'listening_first' not in {a.code for a in awarded2}

    def test_no_attempts_no_badge(self, db_session, listening_user, listening_badges):
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        assert awarded == []


class TestListeningWeek:
    def test_seven_day_streak_grants_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(7):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 80.0,
                         created_at=now - timedelta(days=offset))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_week' in codes

    def test_three_day_streak_no_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(3):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 80.0,
                         created_at=now - timedelta(days=offset))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_week' not in codes

    def test_gap_in_streak_no_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # 7 attempts but with a gap on day 3
        for offset in (0, 1, 2, 4, 5, 6, 7):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 80.0,
                         created_at=now - timedelta(days=offset))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_week' not in codes


class TestListeningMaster:
    def test_ten_high_score_attempts_grants_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(10):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 95.0,
                         created_at=now - timedelta(hours=i))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_master' in codes

    def test_low_avg_score_no_master_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(10):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 70.0,
                         created_at=now - timedelta(hours=i))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_master' not in codes

    def test_fewer_than_ten_attempts_no_master_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(9):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 99.0,
                         created_at=now - timedelta(hours=i))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_master' not in codes

    def test_avg_exactly_90_grants_badge(self, db_session, listening_user, listening_badges, dictation_lesson):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(10):
            _add_attempt(db_session, listening_user.id, dictation_lesson.id, 90.0,
                         created_at=now - timedelta(hours=i))
        awarded = check_listening_achievements(listening_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'listening_master' in codes
