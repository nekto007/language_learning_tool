"""Tests for check_perfect_quiz_achievements and check_perfect_session_achievements (Task 10).

Covers:
- perfect_quiz granted when quiz score == 100
- perfect_quiz not granted when score < 100
- perfect_quiz idempotency
- backfill via historical GameScore rows
- perfect_session granted when all correct in a study session
- perfect_session not granted when there are errors
- perfect_session idempotency
- backfill via historical StudySession rows
- check_all_achievements includes 'perfect_quiz' and 'perfect_session' keys
- perfect_quiz via /api/complete-quiz endpoint
- perfect_session via /api/complete-session endpoint
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.achievements.services import AchievementService
from app.achievements.seed import seed_achievements
from app.auth.models import User
from app.study.models import Achievement, GameScore, StudySession, UserAchievement
from app.utils.db import db


@pytest.fixture
def p_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'pu_{suffix}',
        email=f'pu_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def perfect_badges(db_session):
    seed_achievements()
    db_session.flush()
    codes = {'perfect_quiz', 'perfect_session'}
    badges = Achievement.query.filter(Achievement.code.in_(codes)).all()
    assert len(badges) == len(codes), (
        f"Expected {len(codes)} badges in DB, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _add_quiz_gamescore(db_session, user_id, correct=10, total=10, score=100.0):
    gs = GameScore(
        user_id=user_id,
        game_type='quiz',
        score=score,
        time_taken=60,
        correct_answers=correct,
        total_questions=total,
        date_achieved=datetime.now(timezone.utc),
    )
    db_session.add(gs)
    db_session.flush()
    return gs


def _add_study_session(db_session, user_id, correct=10, incorrect=0):
    session = StudySession(
        user_id=user_id,
        session_type='flashcards',
        start_time=datetime.now(timezone.utc),
        words_studied=correct + incorrect,
        correct_answers=correct,
        incorrect_answers=incorrect,
    )
    db_session.add(session)
    db_session.flush()
    return session


class TestCheckPerfectQuizAchievements:

    def test_score_100_grants_perfect_quiz(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_perfect_quiz_achievements(p_user.id, score=100.0)
        codes = {a.code for a in result}
        assert 'perfect_quiz' in codes

    def test_score_below_100_does_not_grant(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_perfect_quiz_achievements(p_user.id, score=99.0)
        assert result == []

    def test_no_score_no_history_grants_nothing(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_perfect_quiz_achievements(p_user.id)
        assert result == []

    def test_idempotent_second_call_grants_nothing(self, db_session, p_user, perfect_badges):
        first = AchievementService.check_perfect_quiz_achievements(p_user.id, score=100.0)
        assert len(first) == 1

        second = AchievementService.check_perfect_quiz_achievements(p_user.id, score=100.0)
        assert second == [], "Second call must be idempotent"

    def test_backfill_from_historical_gamescore(self, db_session, p_user, perfect_badges):
        _add_quiz_gamescore(db_session, p_user.id, correct=10, total=10, score=100.0)
        result = AchievementService.check_perfect_quiz_achievements(p_user.id)
        codes = {a.code for a in result}
        assert 'perfect_quiz' in codes

    def test_backfill_imperfect_history_grants_nothing(self, db_session, p_user, perfect_badges):
        _add_quiz_gamescore(db_session, p_user.id, correct=8, total=10, score=80.0)
        result = AchievementService.check_perfect_quiz_achievements(p_user.id)
        assert result == []


class TestCheckPerfectSessionAchievements:

    def test_all_correct_grants_perfect_session(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_perfect_session_achievements(
            p_user.id, correct_answers=10, total_answered=10
        )
        codes = {a.code for a in result}
        assert 'perfect_session' in codes

    def test_some_wrong_does_not_grant(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_perfect_session_achievements(
            p_user.id, correct_answers=8, total_answered=10
        )
        assert result == []

    def test_zero_total_does_not_grant(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_perfect_session_achievements(
            p_user.id, correct_answers=0, total_answered=0
        )
        assert result == []

    def test_idempotent_second_call_grants_nothing(self, db_session, p_user, perfect_badges):
        first = AchievementService.check_perfect_session_achievements(
            p_user.id, correct_answers=5, total_answered=5
        )
        assert len(first) == 1

        second = AchievementService.check_perfect_session_achievements(
            p_user.id, correct_answers=5, total_answered=5
        )
        assert second == [], "Second call must be idempotent"

    def test_backfill_from_historical_session(self, db_session, p_user, perfect_badges):
        _add_study_session(db_session, p_user.id, correct=5, incorrect=0)
        result = AchievementService.check_perfect_session_achievements(p_user.id)
        codes = {a.code for a in result}
        assert 'perfect_session' in codes

    def test_backfill_session_with_errors_grants_nothing(self, db_session, p_user, perfect_badges):
        _add_study_session(db_session, p_user.id, correct=5, incorrect=2)
        result = AchievementService.check_perfect_session_achievements(p_user.id)
        assert result == []


class TestCheckAllAchievementsIncludesPerfect:

    def test_check_all_includes_perfect_quiz_key(self, db_session, p_user, perfect_badges):
        result = AchievementService.check_all_achievements(p_user.id)
        assert 'perfect_quiz' in result
        assert 'perfect_session' in result

    def test_check_all_grants_perfect_quiz_from_history(self, db_session, p_user, perfect_badges):
        _add_quiz_gamescore(db_session, p_user.id, correct=10, total=10, score=100.0)
        result = AchievementService.check_all_achievements(p_user.id)
        codes = {a.code for a in result['perfect_quiz']}
        assert 'perfect_quiz' in codes

    def test_check_all_grants_perfect_session_from_history(self, db_session, p_user, perfect_badges):
        _add_study_session(db_session, p_user.id, correct=5, incorrect=0)
        result = AchievementService.check_all_achievements(p_user.id)
        codes = {a.code for a in result['perfect_session']}
        assert 'perfect_session' in codes


class TestPerfectQuizViaEndpoint:

    def test_perfect_quiz_via_complete_quiz_endpoint(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        seed_achievements()
        db_session.flush()
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps({
                'total_questions': 10,
                'correct_answers': 10,
                'time_taken': 60,
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        ua = (
            UserAchievement.query
            .join(Achievement)
            .filter(
                UserAchievement.user_id == test_user.id,
                Achievement.code == 'perfect_quiz',
            )
            .first()
        )
        assert ua is not None, "perfect_quiz should be granted after 100% quiz via endpoint"

    def test_imperfect_quiz_does_not_grant_perfect_quiz(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        seed_achievements()
        db_session.flush()
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps({
                'total_questions': 10,
                'correct_answers': 8,
                'time_taken': 60,
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200

        ua = (
            UserAchievement.query
            .join(Achievement)
            .filter(
                UserAchievement.user_id == test_user.id,
                Achievement.code == 'perfect_quiz',
            )
            .first()
        )
        assert ua is None, "perfect_quiz must not be granted for imperfect quiz"
