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
