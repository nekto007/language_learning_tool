"""Tests for app/srs/counting.py — canonical SRS counting functions."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.srs.constants import CardState
from app.srs.counting import (
    count_due_cards,
    count_new_cards_today,
    count_reviews_today,
)
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db as real_db
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'srscount_{suffix}',
        email=f'srscount_{suffix}@example.com',
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


def _make_user_word(db_session, user: User, word: CollectionWords, *, status: str = 'learning') -> UserWord:
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = status
    db_session.add(uw)
    db_session.commit()
    return uw


def _make_direction(
    db_session,
    user_word: UserWord,
    *,
    state: str = CardState.REVIEW.value,
    next_review: datetime | None = None,
    last_reviewed: datetime | None = None,
    first_reviewed: datetime | None = None,
    buried_until: datetime | None = None,
    direction: str = 'eng-rus',
    repetitions: int = 0,
) -> UserCardDirection:
    row = UserCardDirection(user_word_id=user_word.id, direction=direction)
    row.state = state
    row.repetitions = repetitions
    row.next_review = next_review if next_review is not None else _now_naive()
    row.last_reviewed = last_reviewed
    row.first_reviewed = first_reviewed
    row.buried_until = buried_until
    db_session.add(row)
    db_session.commit()
    return row


class TestCountDueCards:
    def test_empty_db_returns_zero(self, db_session):
        user = _make_user(db_session)
        assert count_due_cards(user.id, real_db) == 0

    def test_includes_learning_relearning_review(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        for state in (
            CardState.LEARNING.value,
            CardState.RELEARNING.value,
            CardState.REVIEW.value,
        ):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=state,
                next_review=now - timedelta(minutes=5),
            )

        assert count_due_cards(user.id, real_db) == 3

    def test_excludes_new_state(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.NEW.value,
            next_review=now - timedelta(hours=1),
        )
        assert count_due_cards(user.id, real_db) == 0

    def test_excludes_buried(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
            buried_until=now + timedelta(hours=2),
        )
        assert count_due_cards(user.id, real_db) == 0

    def test_excludes_future_due(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now + timedelta(hours=1),
        )
        assert count_due_cards(user.id, real_db) == 0

    def test_excludes_mastered_user_word(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word, status='mastered')
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(hours=1),
        )
        assert count_due_cards(user.id, real_db) == 0

    def test_accepts_aware_now_utc(self, db_session):
        """Passing tz-aware datetime should be normalized to naive UTC internally."""
        user = _make_user(db_session)
        now_naive = _now_naive()
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now_naive - timedelta(minutes=5),
        )
        aware_now = datetime.now(timezone.utc)
        assert count_due_cards(user.id, real_db, now_utc=aware_now) == 1


class TestCountNewAndReviewsToday:
    def test_new_cards_today_and_reviews_disjoint(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()

        new_word = _make_word(db_session)
        new_uw = _make_user_word(db_session, user, new_word)
        _make_direction(
            db_session, new_uw,
            state=CardState.LEARNING.value,
            first_reviewed=now,
            last_reviewed=now,
            next_review=now + timedelta(days=1),
        )

        rev_word = _make_word(db_session)
        rev_uw = _make_user_word(db_session, user, rev_word)
        _make_direction(
            db_session, rev_uw,
            state=CardState.REVIEW.value,
            first_reviewed=now - timedelta(days=3),
            last_reviewed=now,
            next_review=now + timedelta(days=1),
        )

        assert count_new_cards_today(user.id, real_db) == 1
        assert count_reviews_today(user.id, real_db) == 1

    def test_reviews_today_excludes_yesterday(self, db_session):
        user = _make_user(db_session)
        today_start = _now_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today_start - timedelta(hours=2)

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            first_reviewed=yesterday - timedelta(days=2),
            last_reviewed=yesterday,
            next_review=today_start + timedelta(days=1),
        )

        assert count_reviews_today(user.id, real_db) == 0
        assert count_new_cards_today(user.id, real_db) == 0

    def test_new_cards_today_ignores_null_first_reviewed(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.NEW.value,
            first_reviewed=None,
        )
        assert count_new_cards_today(user.id, real_db) == 0


class TestNaiveUtcImport:
    def test_import_path(self):
        from app.srs.counting import count_due_cards as cdc  # noqa: F401


class TestUnifiedCountingAcrossCallsites:
    """mission-plan, linear-plan and /study must all see the same due count."""

    def test_mission_and_linear_agree(self, db_session):
        from app.daily_plan.assembler import _count_srs_due
        from app.daily_plan.linear.slots.srs_slot import (
            count_srs_due_cards,
            count_srs_reviews_today,
        )

        user = _make_user(db_session)
        now = _now_naive()

        # Two due cards in different states.
        for state in (CardState.LEARNING.value, CardState.REVIEW.value):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=state,
                next_review=now - timedelta(minutes=5),
                first_reviewed=now - timedelta(days=2),
                last_reviewed=now - timedelta(hours=2),
            )

        canonical = count_due_cards(user.id, real_db)
        assert canonical == 2
        assert _count_srs_due(user.id) == canonical
        assert count_srs_due_cards(user.id, real_db) == canonical

        assert count_reviews_today(user.id, real_db) == count_srs_reviews_today(user.id, real_db)
