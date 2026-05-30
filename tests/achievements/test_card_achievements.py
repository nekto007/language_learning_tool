"""Tests for check_card_achievements (Task 6).

Covers:
- cards_100 / cards_500 / cards_1000 granted at the right thresholds
- zero reviews grants nothing
- idempotency: second call grants nothing new
- check_all_achievements includes 'cards' key
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.models import UserStatistics
from app.achievements.services import AchievementService
from app.achievements.seed import seed_achievements
from app.auth.models import User
from app.study.models import Achievement, UserAchievement


CARD_BADGE_CODES = {'cards_100', 'cards_500', 'cards_1000'}


@pytest.fixture
def card_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'cu_{suffix}',
        email=f'cu_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def card_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(CARD_BADGE_CODES)).all()
    assert len(badges) == len(CARD_BADGE_CODES), (
        f"Expected {len(CARD_BADGE_CODES)} badges in DB, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _make_stats(db_session, user_id, cards_reviewed=0):
    stats = UserStatistics(
        user_id=user_id,
        total_cards_reviewed=cards_reviewed,
    )
    db_session.add(stats)
    db_session.flush()
    return stats


class TestCheckCardAchievements:

    def test_zero_reviews_grants_nothing(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=0)
        result = AchievementService.check_card_achievements(card_user.id, stats)
        assert result == []

    def test_99_reviews_grants_nothing(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=99)
        result = AchievementService.check_card_achievements(card_user.id, stats)
        assert result == []

    def test_100_reviews_grants_cards_100(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=100)
        result = AchievementService.check_card_achievements(card_user.id, stats)
        codes = {a.code for a in result}
        assert 'cards_100' in codes
        assert 'cards_500' not in codes
        assert 'cards_1000' not in codes

    def test_500_reviews_grants_cards_100_and_500(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=500)
        result = AchievementService.check_card_achievements(card_user.id, stats)
        codes = {a.code for a in result}
        assert 'cards_100' in codes
        assert 'cards_500' in codes
        assert 'cards_1000' not in codes

    def test_1000_reviews_grants_all_three(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=1000)
        result = AchievementService.check_card_achievements(card_user.id, stats)
        codes = {a.code for a in result}
        assert 'cards_100' in codes
        assert 'cards_500' in codes
        assert 'cards_1000' in codes

    def test_idempotent_second_call_grants_nothing(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=100)
        first = AchievementService.check_card_achievements(card_user.id, stats)
        assert len(first) > 0

        second = AchievementService.check_card_achievements(card_user.id, stats)
        assert second == [], "Second call must be idempotent"

    def test_check_all_achievements_includes_cards(self, db_session, card_user, card_badges):
        _make_stats(db_session, card_user.id, cards_reviewed=100)
        result = AchievementService.check_all_achievements(card_user.id)
        assert 'cards' in result, "check_all_achievements must include 'cards' key"
        codes = {a.code for a in result['cards']}
        assert 'cards_100' in codes

    def test_501_reviews_does_not_re_grant_500(self, db_session, card_user, card_badges):
        stats = _make_stats(db_session, card_user.id, cards_reviewed=500)
        first = AchievementService.check_card_achievements(card_user.id, stats)
        assert any(a.code == 'cards_500' for a in first)

        stats.total_cards_reviewed = 501
        db_session.flush()
        second = AchievementService.check_card_achievements(card_user.id, stats)
        assert second == [], "No new badge at 501 reviews after 500 already granted"
