"""Tests for check_lesson_achievements (Task 4).

Covers:
- first_lesson granted when total_lessons_completed >= 1
- lessons_5 / lessons_10 granted at the right thresholds
- 11th lesson completion grants nothing new (idempotent)
- user with 0 lessons gets nothing
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.models import UserStatistics
from app.achievements.services import AchievementService
from app.achievements.seed import seed_achievements
from app.auth.models import User
from app.study.models import Achievement, UserAchievement


LESSON_BADGE_CODES = {
    'first_lesson', 'lessons_5', 'lessons_10',
    'lessons_25', 'lessons_50', 'lessons_100',
}


@pytest.fixture
def lesson_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'lsn_{suffix}',
        email=f'lsn_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def lesson_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(LESSON_BADGE_CODES)).all()
    assert len(badges) == len(LESSON_BADGE_CODES), (
        f"Expected {len(LESSON_BADGE_CODES)} badges in DB, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _make_stats(db_session, user_id, lessons_completed):
    stats = UserStatistics(user_id=user_id, total_lessons_completed=lessons_completed)
    db_session.add(stats)
    db_session.flush()
    return stats


class TestCheckLessonAchievements:

    def test_zero_lessons_grants_nothing(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 0)
        result = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        assert result == []

    def test_first_lesson_grants_first_lesson_badge(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 1)
        result = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_lesson' in codes
        assert 'lessons_5' not in codes

    def test_5_lessons_grants_first_lesson_and_lessons_5(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 5)
        result = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_lesson' in codes
        assert 'lessons_5' in codes
        assert 'lessons_10' not in codes

    def test_10_lessons_grants_up_to_lessons_10(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 10)
        result = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_lesson' in codes
        assert 'lessons_5' in codes
        assert 'lessons_10' in codes
        assert 'lessons_25' not in codes

    def test_100_lessons_grants_all_six(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 100)
        result = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        codes = {a.code for a in result}
        for code in LESSON_BADGE_CODES:
            assert code in codes, f"Expected {code} to be granted for 100 lessons"

    def test_11th_lesson_grants_nothing_new(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 10)
        first = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        assert len(first) > 0

        stats.total_lessons_completed = 11
        db_session.flush()

        second = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        assert second == [], "No new achievements should be granted on 11th lesson"

    def test_idempotent_repeated_call(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 5)
        first = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        assert len(first) == 2  # first_lesson + lessons_5

        second = AchievementService.check_lesson_achievements(lesson_user.id, stats)
        assert second == [], "Second call must be idempotent"

    def test_check_all_achievements_includes_lessons(self, db_session, lesson_user, lesson_badges):
        stats = _make_stats(db_session, lesson_user.id, 5)
        result = AchievementService.check_all_achievements(lesson_user.id)
        codes = {a.code for a in result['all']}
        assert 'first_lesson' in codes
        assert 'lessons_5' in codes
        assert 'lessons' in result, "check_all_achievements must include 'lessons' key"
