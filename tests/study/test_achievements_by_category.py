"""Tests for Task 1: Russian category labels in get_achievements_by_category."""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.study.models import Achievement, UserAchievement
from app.study.services.stats_service import StatsService, _CATEGORY_LABELS_RU
from app.utils.db import db


def _make_user(db_session) -> User:
    uid = uuid.uuid4().hex[:8]
    u = User(username=f"cat_{uid}", email=f"cat_{uid}@test.com")
    u.set_password("password")
    db_session.add(u)
    db_session.flush()
    return u


def _make_achievement(db_session, code: str, category: str, xp: int = 10) -> Achievement:
    ach = Achievement(code=code, name=code, icon="🏅", category=category, xp_reward=xp)
    db_session.add(ach)
    db_session.flush()
    return ach


class TestCategoryLabelsRu:
    def test_all_known_categories_have_russian_labels(self):
        expected_keys = {
            'lessons', 'streak', 'mission', 'quiz', 'flashcards', 'books',
            'writing', 'speaking', 'matching', 'listening', 'levels',
            'challenge', 'study', 'special', 'immersion', 'score', 'general',
        }
        assert expected_keys.issubset(set(_CATEGORY_LABELS_RU.keys()))

    def test_labels_are_russian(self):
        assert _CATEGORY_LABELS_RU['streak'] == 'Серии'
        assert _CATEGORY_LABELS_RU['lessons'] == 'Уроки'
        assert _CATEGORY_LABELS_RU['books'] == 'Книги'

    def test_unknown_category_falls_back_to_raw_code(self, db_session):
        user = _make_user(db_session)
        _make_achievement(db_session, f"ach_{uuid.uuid4().hex[:6]}", "zzunknown")
        result = StatsService.get_achievements_by_category(user.id)
        assert 'zzunknown' in result['category_labels']
        assert result['category_labels']['zzunknown'] == 'zzunknown'


class TestGetAchievementsByCategoryLabels:
    def test_category_labels_key_present(self, db_session):
        user = _make_user(db_session)
        _make_achievement(db_session, f"s_{uuid.uuid4().hex[:6]}", "streak")
        result = StatsService.get_achievements_by_category(user.id)
        assert 'category_labels' in result

    def test_streak_category_label_is_russian(self, db_session):
        user = _make_user(db_session)
        _make_achievement(db_session, f"s_{uuid.uuid4().hex[:6]}", "streak")
        result = StatsService.get_achievements_by_category(user.id)
        labels = result['category_labels']
        assert labels.get('streak') == 'Серии'

    def test_multiple_categories_all_translated(self, db_session):
        user = _make_user(db_session)
        _make_achievement(db_session, f"s_{uuid.uuid4().hex[:6]}", "streak")
        _make_achievement(db_session, f"l_{uuid.uuid4().hex[:6]}", "lessons")
        _make_achievement(db_session, f"b_{uuid.uuid4().hex[:6]}", "books")
        result = StatsService.get_achievements_by_category(user.id)
        labels = result['category_labels']
        assert labels.get('streak') == 'Серии'
        assert labels.get('lessons') == 'Уроки'
        assert labels.get('books') == 'Книги'

    def test_earned_achievement_still_appears_in_category(self, db_session):
        user = _make_user(db_session)
        ach = _make_achievement(db_session, f"s_{uuid.uuid4().hex[:6]}", "streak")
        ua = UserAchievement(user_id=user.id, achievement_id=ach.id)
        db_session.add(ua)
        db_session.flush()
        result = StatsService.get_achievements_by_category(user.id)
        assert 'category_labels' in result
        assert result['category_labels'].get('streak') == 'Серии'


class TestNextGoals:
    def test_next_goals_key_present(self, db_session):
        user = _make_user(db_session)
        _make_achievement(db_session, f"ng_{uuid.uuid4().hex[:6]}", "streak", xp=10)
        result = StatsService.get_achievements_by_category(user.id)
        assert 'next_goals' in result

    def test_earned_achievements_excluded_from_next_goals(self, db_session):
        user = _make_user(db_session)
        earned = _make_achievement(db_session, f"ng_e_{uuid.uuid4().hex[:6]}", "streak", xp=10)
        unearned = _make_achievement(db_session, f"ng_u_{uuid.uuid4().hex[:6]}", "lessons", xp=20)
        ua = UserAchievement(user_id=user.id, achievement_id=earned.id)
        db_session.add(ua)
        db_session.flush()
        result = StatsService.get_achievements_by_category(user.id)
        goal_codes = [g['achievement'].code for g in result['next_goals']]
        assert earned.code not in goal_codes
        assert unearned.code in goal_codes

    def test_next_goals_sorted_by_xp_reward_ascending(self, db_session):
        user = _make_user(db_session)
        ach_high = _make_achievement(db_session, f"ng_h_{uuid.uuid4().hex[:6]}", "lessons", xp=100)
        ach_low = _make_achievement(db_session, f"ng_l_{uuid.uuid4().hex[:6]}", "streak", xp=10)
        ach_mid = _make_achievement(db_session, f"ng_m_{uuid.uuid4().hex[:6]}", "quiz", xp=50)
        result = StatsService.get_achievements_by_category(user.id)
        # Filter to just the ones we created (other tests may have created achievements)
        our_codes = {ach_high.code, ach_low.code, ach_mid.code}
        our_goals = [g for g in result['next_goals'] if g['achievement'].code in our_codes]
        xp_values = [g['achievement'].xp_reward for g in our_goals]
        assert xp_values == sorted(xp_values)

    def test_next_goals_deterministic_within_same_xp(self, db_session):
        user = _make_user(db_session)
        ach_z = _make_achievement(db_session, f"zzz_{uuid.uuid4().hex[:6]}", "streak", xp=10)
        ach_a = _make_achievement(db_session, f"aaa_{uuid.uuid4().hex[:6]}", "streak", xp=10)
        result = StatsService.get_achievements_by_category(user.id)
        our_codes = {ach_z.code, ach_a.code}
        our_goals = [g for g in result['next_goals'] if g['achievement'].code in our_codes]
        codes = [g['achievement'].code for g in our_goals]
        assert codes == sorted(codes)

    def test_all_earned_returns_empty_next_goals(self, db_session):
        user = _make_user(db_session)
        ach = _make_achievement(db_session, f"ng_all_{uuid.uuid4().hex[:6]}", "streak", xp=10)
        ua = UserAchievement(user_id=user.id, achievement_id=ach.id)
        db_session.add(ua)
        db_session.flush()
        result = StatsService.get_achievements_by_category(user.id)
        # next_goals should not contain the earned one; may contain others from the DB
        goal_codes = [g['achievement'].code for g in result['next_goals']]
        assert ach.code not in goal_codes
