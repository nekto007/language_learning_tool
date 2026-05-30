"""Tests for check_matching_achievements (Task 9).

Covers:
- matching_first granted after first game
- matching_perfect granted when score_percentage == 100
- matching_speed granted when duration_sec < 60
- no achievements for no games
- idempotency: second call grants nothing new
- check_all_achievements includes 'matching' key
- backfill via historical GameScore rows
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.achievements.services import AchievementService
from app.achievements.seed import seed_achievements
from app.auth.models import User
from app.study.models import Achievement, GameScore, UserAchievement
from app.utils.db import db


MATCHING_BADGE_CODES = {'matching_first', 'matching_perfect', 'matching_speed'}


@pytest.fixture
def m_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'mu_{suffix}',
        email=f'mu_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def matching_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(MATCHING_BADGE_CODES)).all()
    assert len(badges) == len(MATCHING_BADGE_CODES), (
        f"Expected {len(MATCHING_BADGE_CODES)} badges in DB, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _add_game(db_session, user_id, pairs_matched=5, total_pairs=5, time_taken=30):
    gs = GameScore(
        user_id=user_id,
        game_type='matching',
        difficulty='easy',
        score=100,
        time_taken=time_taken,
        pairs_matched=pairs_matched,
        total_pairs=total_pairs,
        moves=10,
        date_achieved=datetime.now(timezone.utc),
    )
    db_session.add(gs)
    db_session.flush()
    return gs


class TestCheckMatchingAchievements:

    def test_no_games_grants_nothing(self, db_session, m_user, matching_badges):
        result = AchievementService.check_matching_achievements(m_user.id)
        assert result == []

    def test_first_game_grants_matching_first(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=3, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(m_user.id)
        codes = {a.code for a in result}
        assert 'matching_first' in codes

    def test_perfect_score_param_grants_matching_perfect(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(
            m_user.id, score_percentage=100.0
        )
        codes = {a.code for a in result}
        assert 'matching_perfect' in codes

    def test_imperfect_score_param_does_not_grant_matching_perfect(
        self, db_session, m_user, matching_badges
    ):
        _add_game(db_session, m_user.id, pairs_matched=3, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(
            m_user.id, score_percentage=60.0
        )
        codes = {a.code for a in result}
        assert 'matching_perfect' not in codes

    def test_speed_param_grants_matching_speed(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(
            m_user.id, duration_sec=45
        )
        codes = {a.code for a in result}
        assert 'matching_speed' in codes

    def test_slow_duration_does_not_grant_speed(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(
            m_user.id, duration_sec=90
        )
        codes = {a.code for a in result}
        assert 'matching_speed' not in codes

    def test_all_three_granted_in_one_call(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(
            m_user.id, score_percentage=100.0, duration_sec=45
        )
        codes = {a.code for a in result}
        assert codes == MATCHING_BADGE_CODES

    def test_idempotent_second_call_grants_nothing(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=90)
        first = AchievementService.check_matching_achievements(
            m_user.id, score_percentage=100.0, duration_sec=45
        )
        assert len(first) == 3

        second = AchievementService.check_matching_achievements(
            m_user.id, score_percentage=100.0, duration_sec=45
        )
        assert second == [], "Second call must be idempotent"

    def test_backfill_perfect_from_historical_gamescore(self, db_session, m_user, matching_badges):
        # A past game with all pairs matched qualifies for matching_perfect without param
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=90)
        result = AchievementService.check_matching_achievements(m_user.id)
        codes = {a.code for a in result}
        assert 'matching_perfect' in codes

    def test_backfill_speed_from_historical_gamescore(self, db_session, m_user, matching_badges):
        # A past game with time_taken < 60 qualifies for matching_speed without param
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=45)
        result = AchievementService.check_matching_achievements(m_user.id)
        codes = {a.code for a in result}
        assert 'matching_speed' in codes

    def test_check_all_achievements_includes_matching(self, db_session, m_user, matching_badges):
        _add_game(db_session, m_user.id, pairs_matched=5, total_pairs=5, time_taken=45)
        result = AchievementService.check_all_achievements(m_user.id)
        assert 'matching' in result, "check_all_achievements must include 'matching' key"
        codes = {a.code for a in result['matching']}
        assert 'matching_first' in codes


class TestMatchingAchievementsViaEndpoint:

    def _post_matching(self, client, **kwargs):
        payload = {
            'pairs_matched': kwargs.get('pairs_matched', 5),
            'total_pairs': kwargs.get('total_pairs', 5),
            'moves': kwargs.get('moves', 10),
            'time_taken': kwargs.get('time_taken', 30),
            'difficulty': kwargs.get('difficulty', 'easy'),
        }
        payload.update({k: v for k, v in kwargs.items() if k not in payload})
        return client.post(
            '/study/api/complete-matching-game',
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_first_game_via_endpoint_grants_matching_first(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        seed_achievements()
        db_session.flush()
        resp = self._post_matching(
            authenticated_client, pairs_matched=3, total_pairs=5, time_taken=90
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        ua = UserAchievement.query.join(Achievement).filter(
            UserAchievement.user_id == test_user.id,
            Achievement.code == 'matching_first',
        ).first()
        assert ua is not None, "matching_first should be granted after first game via endpoint"

    def test_perfect_game_via_endpoint_grants_matching_perfect(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        seed_achievements()
        db_session.flush()
        resp = self._post_matching(
            authenticated_client, pairs_matched=5, total_pairs=5, time_taken=90
        )
        assert resp.status_code == 200

        ua = UserAchievement.query.join(Achievement).filter(
            UserAchievement.user_id == test_user.id,
            Achievement.code == 'matching_perfect',
        ).first()
        assert ua is not None, "matching_perfect should be granted for 100% accuracy via endpoint"

    def test_speed_game_via_endpoint_grants_matching_speed(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        seed_achievements()
        db_session.flush()
        resp = self._post_matching(
            authenticated_client, pairs_matched=5, total_pairs=5, time_taken=45
        )
        assert resp.status_code == 200

        ua = UserAchievement.query.join(Achievement).filter(
            UserAchievement.user_id == test_user.id,
            Achievement.code == 'matching_speed',
        ).first()
        assert ua is not None, "matching_speed should be granted for <60s game via endpoint"
