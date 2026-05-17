"""Tests for speaking achievement badges (Task 59).

Covers:
- speaking_first: granted on first PronunciationAttempt
- speaking_streak_3: granted after 3 consecutive days with pronunciation attempts
- speaking_clear: granted when 10 matched pronunciations total
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import check_speaking_achievements
from app.achievements.streak_service import get_speaking_streak
from app.auth.models import User
from app.curriculum.models import PronunciationAttempt
from app.study.models import Achievement


SPEAKING_BADGE_CODES = {'speaking_first', 'speaking_streak_3', 'speaking_clear'}


@pytest.fixture
def speaking_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'spk_{suffix}',
        email=f'spk_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def speaking_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(SPEAKING_BADGE_CODES)).all()
    assert len(badges) == len(SPEAKING_BADGE_CODES), (
        f"Expected {len(SPEAKING_BADGE_CODES)} badges, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _add_attempt(db_session, user_id: int, word: str = 'hello',
                 matched: bool = True, created_at=None) -> PronunciationAttempt:
    now = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    attempt = PronunciationAttempt(
        user_id=user_id,
        word=word,
        recognized_text=word if matched else 'wrong',
        matched=matched,
        created_at=now,
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


class TestSpeakingFirst:
    def test_first_attempt_grants_badge(self, db_session, speaking_user, speaking_badges):
        _add_attempt(db_session, speaking_user.id)
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_first' in codes

    def test_already_owned_not_regranted(self, db_session, speaking_user, speaking_badges):
        _add_attempt(db_session, speaking_user.id)
        check_speaking_achievements(speaking_user.id, db_session=db_session)
        awarded2 = check_speaking_achievements(speaking_user.id, db_session=db_session)
        assert 'speaking_first' not in {a.code for a in awarded2}

    def test_no_attempts_no_badge(self, db_session, speaking_user, speaking_badges):
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        assert awarded == []


class TestSpeakingStreak3:
    def test_three_consecutive_days_grants_badge(self, db_session, speaking_user, speaking_badges):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(3):
            _add_attempt(db_session, speaking_user.id,
                         created_at=now - timedelta(days=offset))
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_streak_3' in codes

    def test_two_days_no_badge(self, db_session, speaking_user, speaking_badges):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(2):
            _add_attempt(db_session, speaking_user.id,
                         created_at=now - timedelta(days=offset))
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_streak_3' not in codes

    def test_gap_breaks_streak(self, db_session, speaking_user, speaking_badges):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # days 0, 1, 3 — gap on day 2
        for offset in (0, 1, 3):
            _add_attempt(db_session, speaking_user.id,
                         created_at=now - timedelta(days=offset))
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_streak_3' not in codes


class TestSpeakingClear:
    def test_10_matched_grants_badge(self, db_session, speaking_user, speaking_badges):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(10):
            _add_attempt(db_session, speaking_user.id, word=f'word{i}', matched=True)
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_clear' in codes

    def test_9_matched_no_badge(self, db_session, speaking_user, speaking_badges):
        for i in range(9):
            _add_attempt(db_session, speaking_user.id, word=f'word{i}', matched=True)
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_clear' not in codes

    def test_unmatched_not_counted(self, db_session, speaking_user, speaking_badges):
        # 5 matched + 10 unmatched = still only 5 matched
        for i in range(5):
            _add_attempt(db_session, speaking_user.id, word=f'good{i}', matched=True)
        for i in range(10):
            _add_attempt(db_session, speaking_user.id, word=f'bad{i}', matched=False)
        awarded = check_speaking_achievements(speaking_user.id, db_session=db_session)
        codes = {a.code for a in awarded}
        assert 'speaking_clear' not in codes


class TestGetSpeakingStreak:
    def test_no_attempts_streak_zero(self, db_session, speaking_user):
        assert get_speaking_streak(speaking_user.id, db_session=db_session) == 0

    def test_three_consecutive_days(self, db_session, speaking_user):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(3):
            _add_attempt(db_session, speaking_user.id,
                         created_at=now - timedelta(days=offset))
        assert get_speaking_streak(speaking_user.id, db_session=db_session) == 3

    def test_gap_resets_streak(self, db_session, speaking_user):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Only day 0 and day 2 — yesterday (day 1) is missing
        for offset in (0, 2):
            _add_attempt(db_session, speaking_user.id,
                         created_at=now - timedelta(days=offset))
        assert get_speaking_streak(speaking_user.id, db_session=db_session) == 1
