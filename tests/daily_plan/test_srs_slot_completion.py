"""Tests for is_srs_slot_completed_today — Раздел 8 of docs/srs-fix-plan.md.

Primary signal: StreakEvent for linear_srs_global today.
Fallback: empty pool + activity today + no event → corrective idempotent
award fires and the slot is reported as completed.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.achievements.models import StreakEvent
from app.auth.models import User
from app.daily_plan.linear.xp import (
    LINEAR_XP_EVENT_TYPE,
    is_srs_slot_completed_today,
)
from app.srs.constants import CardState
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.utils.db import db as real_db
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srscomp_{suffix}',
        email=f'srscomp_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_settings(db_session, user) -> StudySettings:
    s = StudySettings(user_id=user.id)
    s.new_words_per_day = 5
    s.reviews_per_day = 20
    db_session.add(s)
    db_session.commit()
    return s


def _make_card(
    db_session,
    user: User,
    *,
    state: str = CardState.REVIEW.value,
    next_review: datetime,
    last_reviewed: datetime,
    first_reviewed: datetime,
) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'w_{suffix}', russian_word=f'с_{suffix}', level='A1',
    )
    db_session.add(word)
    db_session.commit()
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'review'
    db_session.add(uw)
    db_session.commit()
    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = state
    card.next_review = next_review
    card.last_reviewed = last_reviewed
    card.first_reviewed = first_reviewed
    db_session.add(card)
    db_session.commit()
    return card


def _seed_xp_event(db_session, user: User) -> None:
    db_session.add(StreakEvent(
        user_id=user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=date.today(),
        coins_delta=0,
        details={'source': 'linear_srs_global'},
    ))
    db_session.commit()


class TestSrsSlotCompletion:
    def test_xp_event_present_returns_true(self, db_session):
        user = _make_user(db_session)
        _make_settings(db_session, user)
        _seed_xp_event(db_session, user)
        assert is_srs_slot_completed_today(user.id, real_db) is True

    def test_no_event_no_activity_returns_false(self, db_session):
        """Brand-new user with no graded cards and no XP event → not done."""
        user = _make_user(db_session)
        _make_settings(db_session, user)
        assert is_srs_slot_completed_today(user.id, real_db) is False

    def test_activity_with_pool_remaining_returns_false(self, db_session):
        """User graded a card today but there are still due cards in the
        pool → slot not yet done (don't fire corrective award)."""
        user = _make_user(db_session)
        _make_settings(db_session, user)
        now = _now_naive()
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Card reviewed today (first_reviewed yesterday → counts as review)
        _make_card(
            db_session, user,
            state=CardState.REVIEW.value,
            first_reviewed=today_midnight - timedelta(days=2),
            last_reviewed=today_midnight,
            next_review=today_midnight + timedelta(days=1),
        )
        # Another card still due today (pool not empty).
        _make_card(
            db_session, user,
            state=CardState.REVIEW.value,
            first_reviewed=today_midnight - timedelta(days=2),
            last_reviewed=today_midnight - timedelta(days=1),
            next_review=today_midnight - timedelta(hours=1),
        )

        result = is_srs_slot_completed_today(user.id, real_db)
        assert result is False
        # No corrective award fired either.
        assert not StreakEvent.query.filter_by(
            user_id=user.id, event_type=LINEAR_XP_EVENT_TYPE,
        ).all()

    def test_fallback_fires_corrective_award_when_pool_empty(self, db_session):
        """Activity present + pool empty + XP event missing → corrective
        award lands and the slot reports completed."""
        user = _make_user(db_session)
        _make_settings(db_session, user)
        now = _now_naive()
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # One card reviewed today, no other cards remain.
        _make_card(
            db_session, user,
            state=CardState.REVIEW.value,
            first_reviewed=today_midnight - timedelta(days=2),
            last_reviewed=today_midnight,
            next_review=today_midnight + timedelta(days=10),  # not due
        )

        result = is_srs_slot_completed_today(user.id, real_db)
        # Flush the corrective award to make it visible to subsequent query.
        real_db.session.flush()

        assert result is True
        # The corrective StreakEvent landed.
        events = StreakEvent.query.filter_by(
            user_id=user.id, event_type=LINEAR_XP_EVENT_TYPE,
        ).all()
        assert len(events) == 1
        assert events[0].details.get('source') == 'linear_srs_global'

    def test_fallback_is_idempotent(self, db_session):
        """Repeated reconciliation calls must not duplicate the award."""
        user = _make_user(db_session)
        _make_settings(db_session, user)
        now = _now_naive()
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        _make_card(
            db_session, user,
            state=CardState.REVIEW.value,
            first_reviewed=today_midnight - timedelta(days=2),
            last_reviewed=today_midnight,
            next_review=today_midnight + timedelta(days=10),
        )

        for _ in range(3):
            is_srs_slot_completed_today(user.id, real_db)
            real_db.session.flush()

        events = StreakEvent.query.filter_by(
            user_id=user.id, event_type=LINEAR_XP_EVENT_TYPE,
        ).all()
        assert len(events) == 1
