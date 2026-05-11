"""Tests for challenge achievement badges (Task 96).

Covers:
- challenge_first: granted on first DailyChallengeCompletion
- challenge_streak_7: granted after 7 consecutive days of challenge completion
- challenger: granted after 30 total challenge completions
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import check_challenge_achievements
from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion
from app.study.models import Achievement


CHALLENGE_BADGE_CODES = {'challenge_first', 'challenge_streak_7', 'challenger'}


@pytest.fixture
def challenge_user(db_session):
    from app.auth.models import User
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'ch_{suffix}',
        email=f'ch_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def challenge_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(CHALLENGE_BADGE_CODES)).all()
    assert len(badges) == len(CHALLENGE_BADGE_CODES), (
        f"Expected {len(CHALLENGE_BADGE_CODES)} badges, got {len(badges)}: "
        f"{[b.code for b in badges]}"
    )
    return {b.code: b for b in badges}


def _seed_challenge(d: date, db_session) -> DailyChallenge:
    existing = DailyChallenge.query.filter_by(challenge_date=d).first()
    if existing:
        return existing
    ch = DailyChallenge(
        challenge_date=d,
        lesson_id=None,
        bonus_xp=50,
        category='speed_run',
    )
    db_session.add(ch)
    db_session.flush()
    return ch


def _add_completion(user_id: int, d: date, db_session) -> DailyChallengeCompletion:
    ch = _seed_challenge(d, db_session)
    existing = DailyChallengeCompletion.query.filter_by(
        challenge_id=ch.id, user_id=user_id,
    ).first()
    if existing:
        return existing
    comp = DailyChallengeCompletion(
        challenge_id=ch.id,
        user_id=user_id,
        score=90.0,
        time_spent_seconds=120,
    )
    db_session.add(comp)
    db_session.flush()
    return comp


class TestChallengeFirst:
    def test_first_completion_grants_badge(self, db_session, challenge_user, challenge_badges):
        _add_completion(challenge_user.id, date.today(), db_session)
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'challenge_first' in codes

    def test_already_owned_not_regranted(self, db_session, challenge_user, challenge_badges):
        _add_completion(challenge_user.id, date.today(), db_session)
        check_challenge_achievements(challenge_user.id, db_session=db_session)
        awarded2 = check_challenge_achievements(challenge_user.id, db_session=db_session)
        assert 'challenge_first' not in {a.code for a in awarded2}

    def test_no_completions_no_badge(self, db_session, challenge_user, challenge_badges):
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        assert awarded == []


class TestChallengeStreak7:
    def test_seven_consecutive_days_grants_badge(self, db_session, challenge_user, challenge_badges):
        today = date.today()
        for offset in range(7):
            _add_completion(challenge_user.id, today - timedelta(days=offset), db_session)
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'challenge_streak_7' in codes

    def test_six_days_no_badge(self, db_session, challenge_user, challenge_badges):
        today = date.today()
        for offset in range(6):
            _add_completion(challenge_user.id, today - timedelta(days=offset), db_session)
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'challenge_streak_7' not in codes

    def test_gap_breaks_streak(self, db_session, challenge_user, challenge_badges):
        today = date.today()
        # days 0, 1, 3, 4, 5, 6, 7 — gap on day 2
        for offset in (0, 1, 3, 4, 5, 6, 7):
            _add_completion(challenge_user.id, today - timedelta(days=offset), db_session)
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'challenge_streak_7' not in codes


class TestChallenger:
    def test_30_completions_grants_badge(self, db_session, challenge_user, challenge_badges):
        # Use dates spread over 30 days (past 30 unique days)
        base = date(2025, 1, 1)
        for i in range(30):
            _add_completion(challenge_user.id, base + timedelta(days=i), db_session)
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'challenger' in codes

    def test_29_completions_no_badge(self, db_session, challenge_user, challenge_badges):
        base = date(2025, 2, 1)
        for i in range(29):
            _add_completion(challenge_user.id, base + timedelta(days=i), db_session)
        awarded = check_challenge_achievements(challenge_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'challenger' not in codes

    def test_idempotent_at_30(self, db_session, challenge_user, challenge_badges):
        base = date(2025, 3, 1)
        for i in range(30):
            _add_completion(challenge_user.id, base + timedelta(days=i), db_session)
        check_challenge_achievements(challenge_user.id, db_session=db_session)
        awarded2 = check_challenge_achievements(challenge_user.id, db_session=db_session)
        assert 'challenger' not in {a.code for a in awarded2}


class TestCheckChallengeAchievementsIntegration:
    def test_complete_challenge_triggers_check(self, db_session, challenge_user, challenge_badges):
        """complete_challenge() calls check_challenge_achievements() and grants challenge_first."""
        from app.utils.db import db as _db
        from app.daily_plan.challenge import complete_challenge, get_today_challenge

        data = get_today_challenge(challenge_user.id, _db)
        challenge_id = data['id']

        complete_challenge(challenge_user.id, challenge_id, score=95.0, time_spent_seconds=180, db=_db)
        db_session.commit()

        from app.study.models import UserAchievement
        badge = Achievement.query.filter_by(code='challenge_first').first()
        owned = UserAchievement.query.filter_by(
            user_id=challenge_user.id, achievement_id=badge.id,
        ).first()
        assert owned is not None
