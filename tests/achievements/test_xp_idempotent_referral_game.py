"""Tests for idempotent referral and game XP (Task 2)."""
from datetime import date

import uuid
import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.achievements.xp_service import (
    GAME_XP_EVENT_TYPE,
    REFERRAL_XP_EVENT_TYPE,
    award_game_xp_idempotent,
    award_referral_xp_idempotent,
)
from app.auth.models import User
from app.utils.db import db


def _mk_user(db_session):
    unique = uuid.uuid4().hex[:8]
    u = User(username=f'xpidem_{unique}', email=f'xpidem_{unique}@example.com', active=True)
    u.set_password('TestPass123!')
    db_session.add(u)
    db_session.commit()
    return u


class TestAwardReferralXpIdempotent:
    def test_first_call_awards_and_logs_event(self, app, db_session):
        referrer = _mk_user(db_session)
        referee = _mk_user(db_session)

        result = award_referral_xp_idempotent(referrer.id, referee.id, 100)
        assert result is not None
        assert result.xp_awarded >= 100

        events = StreakEvent.query.filter_by(
            user_id=referrer.id, event_type=REFERRAL_XP_EVENT_TYPE,
        ).all()
        assert len(events) == 1
        assert events[0].details['referee_id'] == referee.id

    def test_second_call_same_referee_is_noop(self, app, db_session):
        referrer = _mk_user(db_session)
        referee = _mk_user(db_session)

        first = award_referral_xp_idempotent(referrer.id, referee.id, 100)
        assert first is not None
        total1 = UserStatistics.query.filter_by(user_id=referrer.id).first().total_xp

        second = award_referral_xp_idempotent(referrer.id, referee.id, 100)
        assert second is None
        total2 = UserStatistics.query.filter_by(user_id=referrer.id).first().total_xp
        assert total1 == total2

    def test_different_referee_awards_separately(self, app, db_session):
        referrer = _mk_user(db_session)
        r1 = _mk_user(db_session)
        r2 = _mk_user(db_session)

        a = award_referral_xp_idempotent(referrer.id, r1.id, 100)
        b = award_referral_xp_idempotent(referrer.id, r2.id, 100)
        assert a is not None and b is not None
        events = StreakEvent.query.filter_by(
            user_id=referrer.id, event_type=REFERRAL_XP_EVENT_TYPE,
        ).count()
        assert events == 2

    def test_zero_xp_is_noop(self, app, db_session):
        referrer = _mk_user(db_session)
        referee = _mk_user(db_session)
        assert award_referral_xp_idempotent(referrer.id, referee.id, 0) is None


class TestAwardGameXpIdempotent:
    def test_first_call_awards_and_logs(self, app, db_session):
        user = _mk_user(db_session)
        result = award_game_xp_idempotent(
            user.id, session_id=111, game_type='matching', xp=25, for_date=date(2026, 4, 25),
        )
        assert result is not None
        events = StreakEvent.query.filter_by(
            user_id=user.id, event_type=GAME_XP_EVENT_TYPE,
        ).all()
        assert len(events) == 1
        assert events[0].details['session_id'] == 111
        assert events[0].details['game_type'] == 'matching'

    def test_repeat_same_session_is_noop(self, app, db_session):
        user = _mk_user(db_session)
        first = award_game_xp_idempotent(
            user.id, 222, 'matching', 25, date(2026, 4, 25),
        )
        assert first is not None
        total1 = UserStatistics.query.filter_by(user_id=user.id).first().total_xp

        second = award_game_xp_idempotent(
            user.id, 222, 'matching', 25, date(2026, 4, 25),
        )
        assert second is None
        total2 = UserStatistics.query.filter_by(user_id=user.id).first().total_xp
        assert total1 == total2

    def test_new_session_awards_new_xp(self, app, db_session):
        user = _mk_user(db_session)
        a = award_game_xp_idempotent(user.id, 301, 'matching', 25, date(2026, 4, 25))
        b = award_game_xp_idempotent(user.id, 302, 'matching', 25, date(2026, 4, 25))
        assert a is not None and b is not None
        events = StreakEvent.query.filter_by(
            user_id=user.id, event_type=GAME_XP_EVENT_TYPE,
        ).count()
        assert events == 2

    def test_different_game_type_same_session_awards_separately(self, app, db_session):
        user = _mk_user(db_session)
        a = award_game_xp_idempotent(user.id, 400, 'matching', 25, date(2026, 4, 25))
        b = award_game_xp_idempotent(user.id, 400, 'quiz', 25, date(2026, 4, 25))
        assert a is not None and b is not None

    def test_none_session_does_not_write_event(self, app, db_session):
        user = _mk_user(db_session)
        result = award_game_xp_idempotent(
            user.id, session_id=None, game_type='matching', xp=25, for_date=date(2026, 4, 25),
        )
        assert result is not None
        assert StreakEvent.query.filter_by(
            user_id=user.id, event_type=GAME_XP_EVENT_TYPE,
        ).count() == 0

    def test_zero_xp_is_noop(self, app, db_session):
        user = _mk_user(db_session)
        assert award_game_xp_idempotent(
            user.id, 500, 'matching', 0, date(2026, 4, 25),
        ) is None
