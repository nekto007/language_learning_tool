"""Lesson audit item 11: the SRS grade log and the retention metric built on it.

Both grading surfaces append a ``CardGradeEvent`` with the card state *before*
the answer; the adaptive tier reads recent mature accuracy from the log and
falls back to the lifetime counters only while the log is too short.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.srs.constants import CardState
from app.srs.grade_log import MIN_MATURE_GRADES_FOR_ACCURACY, recent_mature_accuracy
from app.srs.service import UnifiedSRSService
from app.study.models import CardGradeEvent, StudySession, UserCardDirection, UserWord
from app.study.services.srs_service import SRSService
from app.words.models import CollectionWords
from app.auth.models import User


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _word(db_session) -> CollectionWords:
    word = CollectionWords(english_word=f'gl_{uuid.uuid4().hex[:10]}', russian_word='перевод')
    db_session.add(word)
    db_session.commit()
    return word


def _card(db_session, user, *, state: str, interval: int = 10, lapses: int = 0,
          correct: int = 0, incorrect: int = 0) -> UserCardDirection:
    uw = UserWord(user_id=user.id, word_id=_word(db_session).id)
    db_session.add(uw)
    db_session.commit()
    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = state
    card.interval = interval
    card.lapses = lapses
    card.repetitions = 3 if state == CardState.REVIEW.value else 0
    card.ease_factor = 2.3
    card.step_index = 0
    card.next_review = _now()
    card.correct_count = correct
    card.incorrect_count = incorrect
    if state != CardState.NEW.value:
        card.first_reviewed = _now() - timedelta(days=30)
        card.last_reviewed = _now() - timedelta(days=10)
    db_session.add(card)
    db_session.commit()
    return card


def _events(db_session, user_id: int) -> list[CardGradeEvent]:
    return db_session.query(CardGradeEvent).filter_by(user_id=user_id).order_by(CardGradeEvent.id).all()


def _log(db_session, user_id: int, direction_id: int, *, state_before: str, rating: int, ago_minutes: int) -> None:
    db_session.add(CardGradeEvent(
        user_id=user_id, direction_id=direction_id, rating=rating,
        state_before=state_before, state_after=CardState.REVIEW.value,
        graded_at=_now() - timedelta(minutes=ago_minutes),
    ))


class TestBothSurfacesLog:
    def test_update_after_review_logs_pre_answer_state(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.REVIEW.value, interval=10, lapses=1)
        card.update_after_review(1)  # «не знаю» on a mature card
        db_session.commit()
        (event,) = _events(db_session, test_user.id)
        assert event.direction_id == card.id
        assert event.rating == 1 and event.is_correct is False
        assert event.state_before == CardState.REVIEW.value
        assert event.state_after == CardState.RELEARNING.value
        assert event.interval_before == 10 and event.lapses_before == 1
        assert event.is_first_review is False
        assert event.context is None and event.session_id is None
        assert event.word_id == card.user_word.word_id

    def test_grade_card_logs_event_with_context(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.REVIEW.value, interval=6)
        result = UnifiedSRSService().grade_card(card.id, 3, test_user.id)
        assert result['success'] is True
        db_session.commit()
        (event,) = _events(db_session, test_user.id)
        assert event.context == 'srs_api'
        assert event.state_before == CardState.REVIEW.value and event.state_after == CardState.REVIEW.value
        assert event.rating == 3 and event.is_correct is True
        assert event.interval_after > event.interval_before

    def test_first_review_of_a_new_card(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.NEW.value, interval=0)
        card.update_after_review(3, context='lesson')
        db_session.commit()
        (event,) = _events(db_session, test_user.id)
        assert event.state_before == CardState.NEW.value
        assert event.state_after != CardState.NEW.value  # the engine decides where a first «know» lands
        assert event.is_first_review is True and event.context == 'lesson'

    def test_doubt_counts_as_recalled_like_the_lifetime_counters(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.REVIEW.value)
        card.update_after_review(2)
        db_session.commit()
        (event,) = _events(db_session, test_user.id)
        assert event.rating == 2 and event.is_correct is True
        assert card.correct_count == 1 and card.incorrect_count == 0

    def test_session_is_linked_only_when_owned(self, app, db_session, test_user):
        other = User(username=f'other_{uuid.uuid4().hex[:8]}', email=f'{uuid.uuid4().hex[:8]}@example.com')
        other.set_password('Str0ng-Passw0rd!')
        db_session.add(other)
        db_session.commit()
        mine = StudySession(user_id=test_user.id, session_type='cards')
        theirs = StudySession(user_id=other.id, session_type='cards')
        db_session.add_all([mine, theirs])
        db_session.commit()
        card = _card(db_session, test_user, state=CardState.REVIEW.value)
        card.update_after_review(3, context='study', session_id=str(mine.id))
        card.update_after_review(3, context='study', session_id=theirs.id)
        card.update_after_review(3, context='study', session_id='abc')
        db_session.commit()
        linked = [e.session_id for e in _events(db_session, test_user.id)]
        assert linked == [mine.id, None, None]


class TestRecentMatureAccuracy:
    def test_only_review_state_before_counts(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.REVIEW.value)
        for i in range(12):
            _log(db_session, test_user.id, card.id, state_before='review', rating=3 if i < 9 else 1, ago_minutes=i)
        for i in range(5):  # relearning re-asks and learning steps must not inflate the figure
            _log(db_session, test_user.id, card.id, state_before='relearning', rating=3, ago_minutes=100 + i)
            _log(db_session, test_user.id, card.id, state_before='learning', rating=1, ago_minutes=200 + i)
        db_session.commit()
        assert recent_mature_accuracy(test_user.id, 40) == pytest.approx(75.0)

    def test_too_few_mature_grades_returns_none(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.REVIEW.value)
        for i in range(MIN_MATURE_GRADES_FOR_ACCURACY - 1):
            _log(db_session, test_user.id, card.id, state_before='review', rating=3, ago_minutes=i)
        db_session.commit()
        assert recent_mature_accuracy(test_user.id, 40) is None

    def test_window_keeps_the_most_recent_grades(self, app, db_session, test_user):
        card = _card(db_session, test_user, state=CardState.REVIEW.value)
        for i in range(20):  # newest 20: all recalled
            _log(db_session, test_user.id, card.id, state_before='review', rating=3, ago_minutes=i)
        for i in range(30):  # older 30: all missed
            _log(db_session, test_user.id, card.id, state_before='review', rating=1, ago_minutes=1000 + i)
        db_session.commit()
        assert recent_mature_accuracy(test_user.id, 20) == pytest.approx(100.0)
        assert recent_mature_accuracy(test_user.id, 40) == pytest.approx(50.0)

    def test_other_users_grades_are_ignored(self, app, db_session, test_user):
        other = User(username=f'o_{uuid.uuid4().hex[:8]}', email=f'{uuid.uuid4().hex[:8]}@example.com')
        other.set_password('Str0ng-Passw0rd!')
        db_session.add(other)
        db_session.commit()
        card = _card(db_session, other, state=CardState.REVIEW.value)
        for i in range(20):
            _log(db_session, other.id, card.id, state_before='review', rating=1, ago_minutes=i)
        db_session.commit()
        assert recent_mature_accuracy(test_user.id, 40) is None


class TestTierUsesTheLog:
    def test_log_beats_sticky_lifetime_counters(self, app, db_session, test_user):
        """Prod copy, user 1: lifetime 37 % kept the tier in collapse although recent sessions ran ~50 %."""
        card = _card(db_session, test_user, state=CardState.REVIEW.value, correct=3, incorrect=7)
        # Bridge: no log yet -> the lifetime counters still decide (30 % -> collapse).
        assert SRSService._accuracy_on_recent_reviews(test_user.id, 20) == pytest.approx(30.0)
        assert SRSService._tier_from_accuracy(SRSService._accuracy_on_recent_reviews(test_user.id, 20)) == 'collapse'
        for i in range(20):
            _log(db_session, test_user.id, card.id, state_before='review', rating=3 if i < 17 else 1, ago_minutes=i)
        db_session.commit()
        accuracy = SRSService._accuracy_on_recent_reviews(test_user.id, 20)
        assert accuracy == pytest.approx(85.0)
        assert SRSService._tier_from_accuracy(accuracy) == 'normal'

    def test_real_grades_feed_the_metric_end_to_end(self, app, db_session, test_user):
        cards = [_card(db_session, test_user, state=CardState.REVIEW.value) for _ in range(12)]
        for i, card in enumerate(cards):
            card.update_after_review(3 if i < 6 else 1)
        db_session.commit()
        assert SRSService._accuracy_on_recent_reviews(test_user.id, 20) == pytest.approx(50.0)


class TestMigrationFile:
    def test_revision_chain_and_table(self):
        from pathlib import Path
        src = Path('migrations/versions/20260906_card_grade_events.py').read_text(encoding='utf-8')
        assert "revision = '20260906_card_grade_events'" in src
        assert "down_revision = '20260829_perfect_day_unique_index'" in src
        assert "op.create_table(\n        'card_grade_events'" in src
        assert "op.drop_table('card_grade_events')" in src
        assert CardGradeEvent.__tablename__ == 'card_grade_events'
