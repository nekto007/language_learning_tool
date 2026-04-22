"""Tests for the linear SRS slot and card-lesson budget integration.

Covers:
- ``get_srs_budget_remaining`` reflects StudySettings.new_words_per_day
  minus cards with ``first_reviewed = today``.
- ``build_srs_slot`` states: active when due>0, collapsed-reviewed when
  due=0 and any activity today, collapsed-empty otherwise.
- ``_build_cards_for_words(..., activate_srs=False)`` does not create
  ``UserWord`` / ``UserCardDirection`` rows for untouched words — so
  curriculum vocabulary can be shown without activating SM-2.
- Card/flashcard curriculum lessons switch the second slot to a deck quiz
  instead of mixing SRS reviews into the first task.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.routes.card_lessons import _build_cards_for_words
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.srs_slot import (
    build_srs_slot,
    count_srs_cards_studied_today,
    count_srs_due_cards,
    count_srs_reviews_today,
    get_linear_plan_due_mix_cards,
    get_srs_budget_remaining,
)
from app.srs.constants import CardState
from app.study.models import QuizDeck, QuizDeckWord, StudySettings, UserCardDirection, UserWord
from app.utils.db import db as real_db
from app.words.models import CollectionWords


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srsslot_{suffix}',
        email=f'srsslot_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_word(db_session, prefix: str = 'word') -> CollectionWords:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'{prefix}_{suffix}',
        russian_word=f'слово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_user_word(db_session, user: User, word: CollectionWords) -> UserWord:
    uw = UserWord(user_id=user.id, word_id=word.id)
    db_session.add(uw)
    db_session.commit()
    return uw


def _make_direction(
    db_session,
    user_word: UserWord,
    *,
    direction: str = 'eng-rus',
    state: str = CardState.REVIEW.value,
    next_review: datetime | None = None,
    last_reviewed: datetime | None = None,
    first_reviewed: datetime | None = None,
    repetitions: int = 0,
) -> UserCardDirection:
    row = UserCardDirection(user_word_id=user_word.id, direction=direction)
    row.state = state
    row.repetitions = repetitions
    row.next_review = next_review or datetime.now(timezone.utc)
    row.last_reviewed = last_reviewed
    row.first_reviewed = first_reviewed
    db_session.add(row)
    db_session.commit()
    return row


def _set_new_words_per_day(db_session, user: User, limit: int) -> None:
    settings = StudySettings.get_settings(user.id)
    settings.new_words_per_day = limit
    db_session.commit()


def _set_reviews_per_day(db_session, user: User, limit: int) -> None:
    settings = StudySettings.get_settings(user.id)
    settings.reviews_per_day = limit
    db_session.commit()


def _make_quiz_deck_with_words(db_session, user: User, count: int) -> QuizDeck:
    deck = QuizDeck(title=f'Deck {uuid.uuid4().hex[:6]}', user_id=user.id)
    db_session.add(deck)
    db_session.commit()

    for index in range(count):
        word = _make_word(db_session, prefix=f'deck_{index}')
        db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word.id, order_index=index))
    db_session.commit()
    return deck


class TestSrsBudgetRemaining:
    def test_default_budget_from_settings(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 7)

        assert get_srs_budget_remaining(user.id, real_db) == 7

    def test_budget_decrements_by_cards_first_reviewed_today(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 5)

        today = datetime.now(timezone.utc)
        for _ in range(3):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                first_reviewed=today,
                last_reviewed=today,
                state=CardState.LEARNING.value,
                next_review=today + timedelta(days=1),
                repetitions=1,
            )

        assert get_srs_budget_remaining(user.id, real_db) == 2

    def test_budget_ignores_first_reviewed_yesterday(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 5)

        yesterday = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            first_reviewed=yesterday,
            last_reviewed=yesterday,
            state=CardState.REVIEW.value,
            next_review=yesterday + timedelta(days=2),
            repetitions=2,
        )

        assert get_srs_budget_remaining(user.id, real_db) == 5

    def test_budget_clamped_at_zero(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 2)

        today = datetime.now(timezone.utc)
        for _ in range(4):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                first_reviewed=today,
                last_reviewed=today,
                state=CardState.LEARNING.value,
                next_review=today + timedelta(days=1),
                repetitions=1,
            )

        assert get_srs_budget_remaining(user.id, real_db) == 0


class TestSrsSlotStates:
    def test_active_slot_when_due_cards_present(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 5)
        now = datetime.now(timezone.utc)
        for _ in range(3):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now - timedelta(hours=1),
                last_reviewed=now - timedelta(days=2),
                first_reviewed=now - timedelta(days=5),
                repetitions=3,
            )

        slot = build_srs_slot(user.id, real_db)

        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'srs'
        assert slot.completed is False
        assert slot.url == '/study/cards?source=linear_plan&from=linear_plan&slot=srs'
        assert slot.data['due_count'] == 3
        assert slot.data['backlog_due_count'] == 3
        assert 'Повторить 3' in slot.title

    def test_active_slot_is_capped_by_reviews_per_day(self, db_session):
        user = _make_user(db_session)
        _set_reviews_per_day(db_session, user, 100)
        now = datetime.now(timezone.utc)
        for _ in range(212):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now - timedelta(hours=1),
                last_reviewed=now - timedelta(days=2),
                first_reviewed=now - timedelta(days=5),
                repetitions=3,
            )

        slot = build_srs_slot(user.id, real_db)

        assert slot.completed is False
        assert slot.title == 'Повторить 100 карточек'
        assert slot.data['due_count'] == 100
        assert slot.data['backlog_due_count'] == 212
        assert slot.data['reviews_limit'] == 100
        assert slot.data['reviews_remaining'] == 100

    def test_slot_completed_when_review_limit_exhausted(self, db_session):
        user = _make_user(db_session)
        _set_reviews_per_day(db_session, user, 2)
        now = datetime.now(timezone.utc)

        for _ in range(2):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now + timedelta(days=2),
                last_reviewed=now,
                first_reviewed=now - timedelta(days=5),
                repetitions=3,
            )

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
            last_reviewed=now - timedelta(days=2),
            first_reviewed=now - timedelta(days=5),
            repetitions=3,
        )

        slot = build_srs_slot(user.id, real_db)

        assert slot.completed is True
        assert slot.url is None
        assert slot.title == 'Лимит повторений на сегодня достигнут'
        assert slot.data['due_count'] == 0
        assert slot.data['backlog_due_count'] == 1
        assert slot.data['reviews_remaining'] == 0

    def test_collapsed_when_no_due_but_studied_today(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 5)

        now = datetime.now(timezone.utc)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now + timedelta(days=3),
            last_reviewed=now,
            first_reviewed=now,
            repetitions=2,
        )

        slot = build_srs_slot(user.id, real_db)

        assert slot.completed is True
        assert slot.url is None
        assert slot.data['due_count'] == 0
        assert slot.data['studied_today'] >= 1
        assert slot.title == 'Карточки повторим завтра'

    def test_collapsed_empty_when_nothing_due_and_no_activity(self, db_session):
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 5)

        slot = build_srs_slot(user.id, real_db)

        assert slot.completed is True
        assert slot.url is None
        assert slot.data['due_count'] == 0
        assert slot.data['studied_today'] == 0
        assert slot.title == 'Сегодня повторять нечего'

    def test_slot_collapses_after_card_lesson_clears_queue(self, db_session):
        """due≥1 active; after the user reviews them (due→0 + studied_today>0),
        the slot collapses to ``completed`` without requiring a click."""
        user = _make_user(db_session)
        _set_new_words_per_day(db_session, user, 5)
        now = datetime.now(timezone.utc)

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        card = _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
            last_reviewed=now - timedelta(days=2),
            first_reviewed=now - timedelta(days=5),
            repetitions=3,
        )

        active = build_srs_slot(user.id, real_db)
        assert active.completed is False
        assert active.data['due_count'] == 1

        # Simulate the card being reviewed and rescheduled.
        card.last_reviewed = now
        card.next_review = now + timedelta(days=3)
        db_session.commit()

        collapsed = build_srs_slot(user.id, real_db)
        assert collapsed.completed is True
        assert collapsed.data['due_count'] == 0
        assert collapsed.title == 'Карточки повторим завтра'

    def test_to_dict_shape(self, db_session):
        user = _make_user(db_session)
        slot_dict = build_srs_slot(user.id, real_db).to_dict()
        assert set(slot_dict) == {
            'kind', 'title', 'lesson_type', 'eta_minutes', 'url', 'completed', 'data',
        }
        assert slot_dict['kind'] == 'srs'
        assert slot_dict['data']['due_count'] == 0


class TestSrsSlotDeckQuizVariant:
    def test_card_curriculum_lesson_uses_deck_quiz_slot(self, db_session):
        user = _make_user(db_session)
        _make_quiz_deck_with_words(db_session, user, 35)

        lesson = type('LessonStub', (), {'type': 'card'})()
        slot = build_srs_slot(user.id, real_db, curriculum_lesson=lesson)

        assert slot.kind == 'srs'
        assert slot.lesson_type == 'quiz'
        assert slot.completed is False
        assert slot.title == 'Квиз по словам из колод'
        assert slot.url == (
            '/study/quiz/linear-plan?source=linear_plan_deck_quiz&limit=30'
            '&from=linear_plan&slot=srs'
        )
        assert slot.data['mode'] == 'deck_quiz'
        assert slot.data['word_limit'] == 30

    def test_card_curriculum_quiz_slot_ignores_due_srs_cards(self, db_session):
        user = _make_user(db_session)
        _make_quiz_deck_with_words(db_session, user, 25)
        now = datetime.now(timezone.utc)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
            last_reviewed=now - timedelta(days=2),
            first_reviewed=now - timedelta(days=5),
            repetitions=2,
        )

        lesson = type('LessonStub', (), {'type': 'flashcards'})()
        slot = build_srs_slot(user.id, real_db, curriculum_lesson=lesson)

        assert slot.lesson_type == 'quiz'
        assert slot.data['word_limit'] == 25
        assert 'linear_plan_deck_quiz' in slot.url
        assert slot.data.get('due_count') is None

    def test_card_curriculum_quiz_slot_completed_after_linear_xp_event(self, db_session):
        from app.achievements.models import StreakEvent
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

        user = _make_user(db_session)
        _make_quiz_deck_with_words(db_session, user, 20)
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            coins_delta=0,
            details={'source': 'linear_srs_global', 'xp': 8},
        ))
        db_session.commit()

        lesson = type('LessonStub', (), {'type': 'card'})()
        slot = build_srs_slot(user.id, real_db, curriculum_lesson=lesson)

        assert slot.completed is True
        assert slot.url is None
        assert slot.title == 'Квиз по словам из колод готов'


class TestSrsCountHelpers:
    def test_count_due_excludes_new_state(self, db_session):
        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.NEW.value,
            next_review=now - timedelta(hours=1),
        )

        assert count_srs_due_cards(user.id, real_db) == 0

    def test_count_due_excludes_buried(self, db_session):
        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        card = _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
            repetitions=2,
        )
        card.buried_until = now + timedelta(hours=4)
        db_session.commit()

        assert count_srs_due_cards(user.id, real_db) == 0

    def test_count_due_excludes_mastered_user_words(self, db_session):
        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        uw.status = 'mastered'
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
            repetitions=2,
        )
        db_session.commit()

        assert count_srs_due_cards(user.id, real_db) == 0

    def test_count_studied_today(self, db_session):
        user = _make_user(db_session)
        now = datetime.now(timezone.utc)

        word_today = _make_word(db_session)
        uw1 = _make_user_word(db_session, user, word_today)
        _make_direction(
            db_session, uw1,
            state=CardState.REVIEW.value,
            last_reviewed=now,
            first_reviewed=now - timedelta(days=4),
            next_review=now + timedelta(days=1),
            repetitions=2,
        )

        word_yesterday = _make_word(db_session)
        uw2 = _make_user_word(db_session, user, word_yesterday)
        _make_direction(
            db_session, uw2,
            state=CardState.REVIEW.value,
            last_reviewed=now - timedelta(days=1, hours=1),
            first_reviewed=now - timedelta(days=5),
            next_review=now + timedelta(days=2),
            repetitions=2,
        )

        assert count_srs_cards_studied_today(user.id, real_db) == 1

    def test_count_reviews_today_excludes_first_reviews(self, db_session):
        user = _make_user(db_session)
        now = datetime.now(timezone.utc)

        first_review_word = _make_word(db_session)
        first_review_uw = _make_user_word(db_session, user, first_review_word)
        _make_direction(
            db_session, first_review_uw,
            state=CardState.LEARNING.value,
            last_reviewed=now,
            first_reviewed=now,
            next_review=now + timedelta(days=1),
            repetitions=1,
        )

        review_word = _make_word(db_session)
        review_uw = _make_user_word(db_session, user, review_word)
        _make_direction(
            db_session, review_uw,
            state=CardState.REVIEW.value,
            last_reviewed=now,
            first_reviewed=now - timedelta(days=3),
            next_review=now + timedelta(days=1),
            repetitions=3,
        )

        assert count_srs_cards_studied_today(user.id, real_db) == 2
        assert count_srs_reviews_today(user.id, real_db) == 1


class TestCurriculumCardActivationGate:
    def test_activate_srs_true_creates_directions(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)

        assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).count() == 0

        cards = _build_cards_for_words([word], user.id, activate_srs=True)

        assert len(cards) == 1
        assert cards[0]['direction_id'] is not None
        assert cards[0]['word_id'] == word.id
        assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).count() == 1
        directions = UserCardDirection.query.join(UserWord).filter(
            UserWord.user_id == user.id, UserWord.word_id == word.id,
        ).count()
        assert directions == 1

    def test_activate_srs_false_skips_direction_creation(self, db_session):
        """budget=0 path: curriculum words are shown display-only; no new
        UserWord / UserCardDirection rows are created."""
        user = _make_user(db_session)
        word = _make_word(db_session)

        cards = _build_cards_for_words([word], user.id, activate_srs=False)

        assert len(cards) == 1
        assert cards[0]['direction_id'] is None
        assert cards[0]['is_new'] is True
        assert cards[0]['word_id'] == word.id
        assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).count() == 0

    def test_activate_srs_false_preserves_existing_directions(self, db_session):
        """When the user already has a direction for a word, activate_srs=False
        still emits the existing card (not a display-only duplicate) and does
        not create new rows."""
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        direction = _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=datetime.now(timezone.utc) - timedelta(hours=1),
            last_reviewed=datetime.now(timezone.utc) - timedelta(days=2),
            first_reviewed=datetime.now(timezone.utc) - timedelta(days=5),
            repetitions=2,
        )

        cards = _build_cards_for_words([word], user.id, activate_srs=False)

        assert len(cards) == 1
        assert cards[0]['direction_id'] == direction.id
        assert UserCardDirection.query.join(UserWord).filter(
            UserWord.user_id == user.id,
        ).count() == 1


class TestLinearPlanIncludesSrsSlot:
    def test_get_linear_plan_exposes_srs_slot(self, db_session):
        from app.curriculum.models import CEFRLevel, Lessons, Module
        from app.daily_plan.linear.plan import get_linear_plan

        suffix = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=suffix, name=f'Level {suffix}', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M1', raw_content={})
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(module_id=module.id, number=1, title='L1', type='vocabulary', content={})
        db_session.add(lesson)
        db_session.commit()

        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        srs_slots = [s for s in payload['baseline_slots'] if s['kind'] == 'srs']
        assert len(srs_slots) == 1
        assert srs_slots[0]['completed'] is True  # no due cards for fresh user
