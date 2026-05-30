"""Tests for check_book_achievements (Task 5).

Covers:
- first_book granted when total_books_completed >= 1
- books_5 / books_10 granted at the right thresholds
- chapter_marathon granted when total_chapters_read >= 50
- non-final chapters don't fire book-count badges
- idempotency: second call grants nothing new
- check_all_achievements includes 'books' key
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.models import UserStatistics
from app.achievements.services import AchievementService
from app.achievements.seed import seed_achievements
from app.auth.models import User
from app.study.models import Achievement, UserAchievement


BOOK_BADGE_CODES = {'first_book', 'books_5', 'books_10', 'chapter_marathon'}


@pytest.fixture
def book_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'bk_{suffix}',
        email=f'bk_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def book_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(BOOK_BADGE_CODES)).all()
    assert len(badges) == len(BOOK_BADGE_CODES), (
        f"Expected {len(BOOK_BADGE_CODES)} badges in DB, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _make_stats(db_session, user_id, books_completed=0, chapters_read=0):
    stats = UserStatistics(
        user_id=user_id,
        total_books_completed=books_completed,
        total_chapters_read=chapters_read,
    )
    db_session.add(stats)
    db_session.flush()
    return stats


class TestCheckBookAchievements:

    def test_zero_books_grants_nothing(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=0, chapters_read=0)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        assert result == []

    def test_first_book_grants_first_book_badge(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=1, chapters_read=5)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_book' in codes
        assert 'books_5' not in codes
        assert 'chapter_marathon' not in codes

    def test_5_books_grants_first_book_and_books_5(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=5, chapters_read=30)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_book' in codes
        assert 'books_5' in codes
        assert 'books_10' not in codes

    def test_10_books_grants_up_to_books_10(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=10, chapters_read=40)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_book' in codes
        assert 'books_5' in codes
        assert 'books_10' in codes

    def test_chapter_marathon_at_50_chapters(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=0, chapters_read=50)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        codes = {a.code for a in result}
        assert 'chapter_marathon' in codes
        assert 'first_book' not in codes

    def test_chapter_marathon_not_granted_below_50(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=0, chapters_read=49)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        codes = {a.code for a in result}
        assert 'chapter_marathon' not in codes

    def test_non_final_chapter_does_not_trigger_book_badge(self, db_session, book_user, book_badges):
        # books_completed=0 means no book completed yet
        stats = _make_stats(db_session, book_user.id, books_completed=0, chapters_read=10)
        result = AchievementService.check_book_achievements(book_user.id, stats)
        codes = {a.code for a in result}
        assert 'first_book' not in codes

    def test_idempotent_second_call_grants_nothing(self, db_session, book_user, book_badges):
        stats = _make_stats(db_session, book_user.id, books_completed=1, chapters_read=10)
        first = AchievementService.check_book_achievements(book_user.id, stats)
        assert len(first) > 0

        second = AchievementService.check_book_achievements(book_user.id, stats)
        assert second == [], "Second call must be idempotent"

    def test_check_all_achievements_includes_books(self, db_session, book_user, book_badges):
        _make_stats(db_session, book_user.id, books_completed=1, chapters_read=10)
        result = AchievementService.check_all_achievements(book_user.id)
        assert 'books' in result, "check_all_achievements must include 'books' key"
        codes = {a.code for a in result['books']}
        assert 'first_book' in codes
