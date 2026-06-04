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
    get_new_card_budget,
)
from app.study.models import StudySettings
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


class TestChunkIds:
    """chunk_ids correctness — used by count_due_cards for large word_ids."""

    def test_empty_list_yields_nothing(self):
        from app.utils.db_utils import chunk_ids
        assert list(chunk_ids([])) == []

    def test_list_smaller_than_chunk_size_single_chunk(self):
        from app.utils.db_utils import chunk_ids
        ids = list(range(500))
        chunks = list(chunk_ids(ids, chunk_size=1000))
        assert len(chunks) == 1
        assert chunks[0] == ids

    def test_list_larger_than_chunk_size_multiple_chunks(self):
        from app.utils.db_utils import chunk_ids
        ids = list(range(2500))
        chunks = list(chunk_ids(ids, chunk_size=1000))
        assert len(chunks) == 3
        assert sum(len(c) for c in chunks) == 2500


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

    def test_counts_regardless_of_userword_status(self, db_session):
        """`UserCardDirection.state` is authoritative — even a stale or
        diverged `UserWord.status` (e.g. legacy 'mastered', or 'new' after
        a partial recalc) must not hide a due direction from the counter.
        See app/srs/counting.py docstring for the rationale.
        """
        user = _make_user(db_session)
        now = _now_naive()
        for stale_status in ('mastered', 'new'):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word, status=stale_status)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now - timedelta(hours=1),
            )
        assert count_due_cards(user.id, real_db) == 2

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

    def test_word_ids_filter_restricts_to_subset(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        word_in = _make_word(db_session)
        word_out = _make_word(db_session)
        uw_in = _make_user_word(db_session, user, word_in)
        uw_out = _make_user_word(db_session, user, word_out)
        _make_direction(
            db_session, uw_in,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(minutes=5),
        )
        _make_direction(
            db_session, uw_out,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(minutes=5),
        )
        assert count_due_cards(user.id, real_db) == 2
        assert count_due_cards(user.id, real_db, word_ids=[word_in.id]) == 1
        assert count_due_cards(user.id, real_db, word_ids=[]) == 0

    def test_large_word_ids_list_chunks_correctly(self, db_session):
        """word_ids > 1000 triggers chunked queries and returns correct count."""
        user = _make_user(db_session)
        now = _now_naive()

        real_word_ids = []
        for _ in range(2):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now - timedelta(minutes=5),
            )
            real_word_ids.append(word.id)

        # Pad to >1000 with non-existent IDs
        fake_ids = list(range(99_000_000, 99_000_000 + 999))
        large_list = real_word_ids + fake_ids  # 1001 total → triggers chunk path

        result = count_due_cards(user.id, real_db, word_ids=large_list)
        assert result == 2

    def test_large_word_ids_empty_after_padding(self, db_session):
        """Large list of non-existent IDs returns 0 without crash."""
        user = _make_user(db_session)
        fake_ids = list(range(99_100_000, 99_100_000 + 1001))
        assert count_due_cards(user.id, real_db, word_ids=fake_ids) == 0


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

    def test_aware_now_utc_normalized_in_count_new_cards(self, db_session):
        """Passing tz-aware datetime to count_new_cards_today must work (no TypeError)."""
        user = _make_user(db_session)
        aware_now = datetime.now(timezone.utc)
        result = count_new_cards_today(user.id, real_db, now_utc=aware_now)
        assert result == 0

    def test_aware_now_utc_normalized_in_count_reviews_today(self, db_session):
        """Passing tz-aware datetime to count_reviews_today must work (no TypeError)."""
        user = _make_user(db_session)
        aware_now = datetime.now(timezone.utc)
        result = count_reviews_today(user.id, real_db, now_utc=aware_now)
        assert result == 0

    def test_timezone_boundary_card_reviewed_yesterday_not_counted(self, db_session):
        """Card reviewed 1 second before midnight UTC is excluded from today's count."""
        user = _make_user(db_session)
        today_start = _now_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        just_before_midnight = today_start - timedelta(seconds=1)

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            first_reviewed=just_before_midnight - timedelta(days=3),
            last_reviewed=just_before_midnight,
            next_review=today_start + timedelta(days=1),
        )

        # Neither count should include this card (it was reviewed yesterday)
        assert count_new_cards_today(user.id, real_db) == 0
        assert count_reviews_today(user.id, real_db) == 0


class TestGetNewCardBudget:
    def _settings(self, db_session, user, *, new_per_day: int = 10, reviews_per_day: int = 50) -> StudySettings:
        settings = StudySettings(user_id=user.id)
        settings.new_words_per_day = new_per_day
        settings.reviews_per_day = reviews_per_day
        db_session.add(settings)
        db_session.commit()
        return settings

    def test_full_budget_with_no_activity(self, db_session):
        user = _make_user(db_session)
        self._settings(db_session, user, new_per_day=10, reviews_per_day=50)
        remaining_new, remaining_reviews = get_new_card_budget(user.id, real_db)
        assert remaining_new == 10
        assert remaining_reviews == 50

    def test_budget_consumed_by_new_cards(self, db_session):
        user = _make_user(db_session)
        self._settings(db_session, user, new_per_day=3, reviews_per_day=20)
        now = _now_naive()

        # Two first-reviewed-today cards.
        for _ in range(2):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.LEARNING.value,
                first_reviewed=now,
                last_reviewed=now,
                next_review=now + timedelta(days=1),
            )

        remaining_new, _ = get_new_card_budget(user.id, real_db)
        assert remaining_new == 1

    def test_budget_never_negative(self, db_session):
        user = _make_user(db_session)
        self._settings(db_session, user, new_per_day=1, reviews_per_day=5)
        now = _now_naive()

        for _ in range(3):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.LEARNING.value,
                first_reviewed=now,
                last_reviewed=now,
                next_review=now + timedelta(days=1),
            )

        remaining_new, remaining_reviews = get_new_card_budget(user.id, real_db)
        assert remaining_new == 0
        assert remaining_reviews == 5

    def test_budget_with_no_study_settings_returns_defaults(self, db_session):
        """Missing StudySettings triggers auto-creation with defaults (new=5, reviews=20)."""
        user = _make_user(db_session)
        # No StudySettings created; get_settings auto-creates with defaults
        remaining_new, remaining_reviews = get_new_card_budget(user.id, real_db)
        assert remaining_new >= 0
        assert remaining_reviews >= 0
        # Defaults: new_words_per_day=5, reviews_per_day=20
        assert remaining_new == 5
        assert remaining_reviews == 20

    def test_budget_reviews_never_negative_when_over_limit(self, db_session):
        """reviews remaining must be ≥ 0 even when more reviews happened than limit."""
        user = _make_user(db_session)
        self._settings(db_session, user, new_per_day=5, reviews_per_day=2)
        now = _now_naive()

        # 3 review-cards reviewed today (first_reviewed yesterday → review, not new)
        for _ in range(3):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                first_reviewed=now - timedelta(days=2),
                last_reviewed=now,
                next_review=now + timedelta(days=1),
            )

        _, remaining_reviews = get_new_card_budget(user.id, real_db)
        assert remaining_reviews == 0  # clamped to 0, not -1

    def test_low_accuracy_triggers_adaptive_cap(self, db_session):
        """70% accuracy on REVIEW cards → 'low' tier → NEW × 30%."""
        user = _make_user(db_session)
        self._settings(db_session, user, new_per_day=10, reviews_per_day=50)
        now = _now_naive()

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        card = _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            first_reviewed=now - timedelta(days=5),
            last_reviewed=now - timedelta(hours=1),
            next_review=now + timedelta(days=1),
        )
        card.correct_count = 7
        card.incorrect_count = 3  # 70% accuracy
        db_session.commit()

        remaining_new, _ = get_new_card_budget(user.id, real_db)
        # 'low' tier: NEW × 30% of base 10 = 3.
        assert remaining_new == 3


class TestUnifiedCountingAcrossCallsites:
    """mission-plan, linear-plan and /study must all see the same due count."""

    def test_mission_and_linear_agree(self, db_session):
        from app.daily_plan.assembler import _count_srs_due
        from app.daily_plan.linear.slots.srs_slot import count_srs_reviews_today
        from app.study.models import QuizDeck, QuizDeckWord

        user = _make_user(db_session)
        now = _now_naive()

        # Two due cards in different states, both in a quiz deck (= daily-plan mix).
        deck = QuizDeck(user_id=user.id, title='Test deck')
        db_session.add(deck)
        db_session.commit()

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
            db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word.id))
        db_session.commit()

        canonical = count_due_cards(user.id, real_db)
        assert canonical == 2
        # Mission assembler scopes to daily-plan mix (deck words); when all due
        # cards are in the mix, mission count equals the global canonical count.
        assert _count_srs_due(user.id) == canonical

        assert count_reviews_today(user.id, real_db) == count_srs_reviews_today(user.id, real_db)

    def test_mission_count_filters_by_mix_when_card_outside_mix(self, db_session):
        """Mission count must drop due cards not in the daily-plan mix."""
        from app.daily_plan.assembler import _count_srs_due
        from app.study.models import QuizDeck, QuizDeckWord

        user = _make_user(db_session)
        now = _now_naive()

        deck = QuizDeck(user_id=user.id, title='Test deck')
        db_session.add(deck)
        db_session.commit()

        word_in = _make_word(db_session)
        word_out = _make_word(db_session)
        for w in (word_in, word_out):
            uw = _make_user_word(db_session, user, w)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now - timedelta(minutes=5),
                first_reviewed=now - timedelta(days=2),
                last_reviewed=now - timedelta(hours=2),
            )
        db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word_in.id))
        db_session.commit()

        assert count_due_cards(user.id, real_db) == 2
        assert _count_srs_due(user.id) == 1


class TestUnifiedBudgetAcrossCallsites:
    """mission-plan, linear-plan and /study must all see the same new-card budget."""

    def _settings(self, db_session, user, *, new_per_day: int, reviews_per_day: int) -> StudySettings:
        settings = StudySettings(user_id=user.id)
        settings.new_words_per_day = new_per_day
        settings.reviews_per_day = reviews_per_day
        db_session.add(settings)
        db_session.commit()
        return settings

    def test_assembler_and_linear_budget_agree(self, db_session):
        from app.daily_plan.assembler import _get_remaining_card_budget

        user = _make_user(db_session)
        self._settings(db_session, user, new_per_day=7, reviews_per_day=30)
        now = _now_naive()
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.LEARNING.value,
            first_reviewed=now,
            last_reviewed=now,
            next_review=now + timedelta(days=1),
        )

        canonical_new, _canonical_reviews = get_new_card_budget(user.id, real_db)
        assert _get_remaining_card_budget(user.id)[0] == canonical_new
