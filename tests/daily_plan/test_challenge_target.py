"""DP-048 — карточка челленджа ведёт только на урок, который может выполнить критерий.

Критерии ``check_challenge_criteria`` засчитывают лишь серверно-оцениваемые
типы (``CHALLENGE_GRADED_LESSON_TYPES``); ``listening_deep`` требует
``ListeningAttempt``. До правки builder брал следующий урок спайна любого
типа: пользователь проходил ровно предложенный урок и бонуса не получал.
"""
from __future__ import annotations

import pytest

from app.daily_plan.challenge import CHALLENGE_GRADED_LESSON_TYPES
from app.daily_plan.items.challenge import build_challenge_item
from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion
from app.utils.db import db as real_db
from tests.daily_plan.test_unified_plan import (
    _complete_lesson,
    _make_level,
    _make_lesson,
    _make_module,
    _make_user,
)
from tests.support_dates import study_today


def _seed_challenge(db_session, category: str, bonus_xp: int = 60) -> DailyChallenge:
    challenge = DailyChallenge(
        challenge_date=study_today(),
        lesson_id=None,
        bonus_xp=bonus_xp,
        category=category,
    )
    db_session.add(challenge)
    db_session.commit()
    return challenge


def _spine(db_session, first_type: str, second_type: str = 'vocabulary'):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    first = _make_lesson(db_session, module, number=1, type_=first_type)
    second = _make_lesson(db_session, module, number=2, type_=second_type)
    user = _make_user(db_session, onboarding_level=level.code)
    return user, first, second


class TestGradedTargetPreferred:

    def test_accuracy_points_at_next_lesson_when_it_is_graded(self, db_session):
        assert 'quiz' in CHALLENGE_GRADED_LESSON_TYPES
        user, quiz, _ = _spine(db_session, 'quiz')
        _seed_challenge(db_session, 'accuracy_focus')

        item = build_challenge_item(user.id, real_db)

        assert item is not None
        assert item.url.startswith(f'/learn/{quiz.id}/')
        assert 'retry=true' not in item.url
        assert 'from=linear_plan' in item.url and 'slot=challenge' in item.url
        assert item.data['retry'] is False
        assert item.data['lesson_id'] == quiz.id

    def test_speed_run_points_at_next_lesson_when_it_is_graded(self, db_session):
        user, dictation, _ = _spine(db_session, 'dictation')
        _seed_challenge(db_session, 'speed_run', bonus_xp=50)

        item = build_challenge_item(user.id, real_db)

        assert item is not None
        assert item.data['lesson_id'] == dictation.id
        assert 'retry=true' not in item.url


class TestUngradedNextLesson:

    def test_accuracy_falls_back_to_a_passed_graded_lesson_as_retake(self, db_session):
        """Следующий урок — грамматика (не оценивается); есть сданный квиз → пересдача."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        quiz = _make_lesson(db_session, module, number=1, type_='quiz')
        _make_lesson(db_session, module, number=2, type_='grammar')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, quiz)
        _seed_challenge(db_session, 'accuracy_focus')

        item = build_challenge_item(user.id, real_db)

        assert item is not None
        assert item.data['lesson_id'] == quiz.id
        assert item.data['retry'] is True
        # Без retry=true сданный урок открывается на экране результата.
        assert item.url.startswith(f'/learn/{quiz.id}/?retry=true')
        assert 'from=linear_plan' in item.url
        assert 'пересдай' in (item.subtitle or '')

    def test_accuracy_without_any_graded_lesson_builds_no_card(self, db_session):
        user, _, _ = _spine(db_session, 'grammar', 'vocabulary')
        _seed_challenge(db_session, 'accuracy_focus')

        assert build_challenge_item(user.id, real_db) is None

    def test_speed_run_has_no_retake_path(self, db_session):
        """Пересдача никогда не уложится в 5 минут: started_at копируется из первого открытия."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        quiz = _make_lesson(db_session, module, number=1, type_='quiz')
        _make_lesson(db_session, module, number=2, type_='grammar')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, quiz)
        _seed_challenge(db_session, 'speed_run', bonus_xp=50)

        assert build_challenge_item(user.id, real_db) is None

    def test_listening_deep_never_falls_back_to_a_non_listening_lesson(self, db_session):
        user, _, _ = _spine(db_session, 'vocabulary', 'grammar')
        _seed_challenge(db_session, 'listening_deep', bonus_xp=40)

        assert build_challenge_item(user.id, real_db) is None

    def test_listening_deep_points_at_the_reachable_listening_lesson(self, db_session):
        user, dictation, _ = _spine(db_session, 'dictation', 'vocabulary')
        _seed_challenge(db_session, 'listening_deep', bonus_xp=40)

        item = build_challenge_item(user.id, real_db)

        assert item is not None
        assert item.data['lesson_id'] == dictation.id


class TestCompletedChallengeStaysVisible:

    def test_completed_card_survives_without_a_target(self, db_session):
        """Выполненный челлендж — история дня; отсутствие цели его не прячет."""
        user, _, _ = _spine(db_session, 'grammar', 'vocabulary')
        challenge = _seed_challenge(db_session, 'accuracy_focus')
        db_session.add(DailyChallengeCompletion(
            challenge_id=challenge.id, user_id=user.id, score=95.0,
        ))
        db_session.commit()

        item = build_challenge_item(user.id, real_db)

        assert item is not None
        assert item.completed is True
        assert item.url is None
