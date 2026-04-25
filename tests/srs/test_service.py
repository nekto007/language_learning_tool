"""Tests for app/srs/service.py — leech auto-suspend + RELEARNING_STEPS."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.srs.constants import (
    CardState,
    LEECH_THRESHOLD,
    LEECH_SUSPEND_DAYS,
    RATING_DONT_KNOW,
    RATING_KNOW,
    RELEARNING_STEPS,
)
from app.srs.service import UnifiedSRSService
from app.study.models import UserCardDirection, UserWord
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srssvc_{suffix}',
        email=f'srssvc_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_word(db_session) -> CollectionWords:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'word_{suffix}',
        russian_word=f'слово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_review_card(db_session, user: User, *, lapses: int) -> UserCardDirection:
    word = _make_word(db_session)
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'review'
    db_session.add(uw)
    db_session.commit()

    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.REVIEW.value
    card.lapses = lapses
    card.repetitions = 5
    card.interval = 10
    card.ease_factor = 2.0
    card.step_index = 0
    card.next_review = _now_naive()
    db_session.add(card)
    db_session.commit()
    return card


class TestRelearningSteps:
    def test_relearning_steps_now_two_days(self):
        assert RELEARNING_STEPS == [10, 1440]


class TestLeechAutoSuspend:
    def test_calc_dict_includes_bury_days_when_threshold_crossed(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD - 1,
        )
        assert result.get('bury_days') == LEECH_SUSPEND_DAYS

    def test_calc_dict_omits_bury_days_below_threshold(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=2,
        )
        assert 'bury_days' not in result or result.get('bury_days') is None

    def test_calc_dict_does_not_rebury_above_threshold(self):
        # Already past threshold (e.g. user un-buried via CTA and lapsed again):
        # we don't keep adding new bury_days, only on the crossing event.
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD,
        )
        assert 'bury_days' not in result

    def test_grade_card_buries_on_threshold(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        before = datetime.now(timezone.utc)
        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        assert card.lapses == LEECH_THRESHOLD
        assert card.buried_until is not None

        # Compare in UTC. buried_until may be naive or aware depending on DB.
        buried = card.buried_until
        if buried.tzinfo is None:
            buried = buried.replace(tzinfo=timezone.utc)
        delta = buried - before
        assert delta >= timedelta(days=LEECH_SUSPEND_DAYS - 1, hours=23)
        assert delta <= timedelta(days=LEECH_SUSPEND_DAYS + 1)

    def test_grade_card_does_not_bury_below_threshold(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=2)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        db_session.refresh(card)
        assert card.lapses == 3
        assert card.buried_until is None

    def test_due_cards_excludes_buried_leech(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        # _get_due_cards must not include this buried leech
        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=50)
        assert card.id not in [c.id for c in cards]

    def test_buried_leech_returns_after_seven_days(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        # Simulate 8 days passing
        db_session.refresh(card)
        card.buried_until = datetime.now(timezone.utc) - timedelta(days=1)
        # Also make next_review due so it is included
        card.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=50)
        assert card.id in [c.id for c in cards]
