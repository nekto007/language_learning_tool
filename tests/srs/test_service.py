"""Tests for app/srs/service.py — leech auto-suspend + RELEARNING_STEPS."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.srs.constants import (
    CardState,
    GRADUATING_INTERVAL,
    LEARNING_STEPS,
    LEECH_THRESHOLD,
    LEECH_SUSPEND_DAYS,
    RATING_DONT_KNOW,
    RATING_KNOW,
    RELEARNING_STEPS,
)
from app.srs.service import UnifiedSRSService
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.study.services import SRSService
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

    def test_calc_dict_reburies_above_threshold(self):
        # Cards already past threshold should re-bury on every lapse: firing
        # only on the crossing event leaves recurring leeches cycling through
        # daily failures once their first bury expires.
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.0,
            lapses=LEECH_THRESHOLD,
        )
        assert result.get('bury_days') == LEECH_SUSPEND_DAYS

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


class TestLearningStepsGraduation:
    def test_three_steps_to_graduate(self):
        assert len(LEARNING_STEPS) == 3
        # Step 0 → 1
        r1 = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW, state=CardState.LEARNING.value,
            step_index=0, repetitions=1, interval=0, ease_factor=2.5,
        )
        assert r1['state'] == CardState.LEARNING.value
        assert r1['step_index'] == 1
        assert r1['requeue_minutes'] == LEARNING_STEPS[1]
        # Step 1 → 2
        r2 = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW, state=CardState.LEARNING.value,
            step_index=1, repetitions=2, interval=0, ease_factor=2.5,
        )
        assert r2['state'] == CardState.LEARNING.value
        assert r2['step_index'] == 2
        assert r2['requeue_minutes'] == LEARNING_STEPS[2]
        # Step 2 → graduate
        r3 = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW, state=CardState.LEARNING.value,
            step_index=2, repetitions=3, interval=0, ease_factor=2.5,
        )
        assert r3['state'] == CardState.REVIEW.value
        assert r3['interval'] == GRADUATING_INTERVAL
        assert r3['requeue_minutes'] is None


def _make_settings(db_session, user: User, *, new_per_day: int = 10) -> StudySettings:
    s = StudySettings(user_id=user.id, new_words_per_day=new_per_day, reviews_per_day=100)
    db_session.add(s)
    db_session.commit()
    return s


class TestAdaptiveLimitReason:
    def test_reason_normal_when_no_history(self, db_session):
        user = _make_user(db_session)
        _make_settings(db_session, user)
        assert SRSService.get_adaptive_limit_reason(user.id) == 'normal'
        new, _ = SRSService.get_adaptive_limits(user.id)
        assert new == 10

    def test_reason_accuracy_low(self, db_session):
        user = _make_user(db_session)
        _make_settings(db_session, user)
        # Build review history with low accuracy
        for _ in range(5):
            word = _make_word(db_session)
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'review'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.REVIEW.value
            card.correct_count = 1
            card.incorrect_count = 4  # 20% accuracy
            card.last_reviewed = datetime.now(timezone.utc).replace(tzinfo=None)
            card.next_review = card.last_reviewed + timedelta(days=1)
            db_session.add(card)
        db_session.commit()
        assert SRSService.get_adaptive_limit_reason(user.id) == 'accuracy_low'
        new, _ = SRSService.get_adaptive_limits(user.id)
        assert new == 2

    def test_reason_backlog_reduction(self, db_session):
        user = _make_user(db_session)
        _make_settings(db_session, user)
        # 51 overdue review cards with high accuracy
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        for _ in range(51):
            word = _make_word(db_session)
            uw = UserWord(user_id=user.id, word_id=word.id)
            uw.status = 'review'
            db_session.add(uw)
            db_session.commit()
            card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            card.state = CardState.REVIEW.value
            card.correct_count = 9
            card.incorrect_count = 1
            card.last_reviewed = past
            card.next_review = past
            db_session.add(card)
        db_session.commit()
        assert SRSService.get_adaptive_limit_reason(user.id) == 'backlog_reduction'
        new, _ = SRSService.get_adaptive_limits(user.id)
        assert new == 2
