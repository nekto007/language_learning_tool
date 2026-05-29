"""Tests for app/srs/service.py — Task 12: grading and leech logic."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.srs.constants import (
    CardState,
    DEFAULT_EASE_FACTOR,
    LEECH_SUSPEND_DAYS,
    LEECH_THRESHOLD,
    MIN_EASE_FACTOR,
    RATING_DONT_KNOW,
    RATING_DOUBT,
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
        username=f'srssvc12_{suffix}',
        email=f'srssvc12_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_word(db_session) -> CollectionWords:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'word12_{suffix}',
        russian_word=f'слово12_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_review_card(
    db_session,
    user: User,
    *,
    lapses: int = 0,
    ease_factor: float = DEFAULT_EASE_FACTOR,
    interval: int = 10,
) -> UserCardDirection:
    word = _make_word(db_session)
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'review'
    db_session.add(uw)
    db_session.commit()

    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.REVIEW.value
    card.lapses = lapses
    card.repetitions = 5
    card.interval = interval
    card.ease_factor = ease_factor
    card.step_index = 0
    card.next_review = _now_naive()
    db_session.add(card)
    db_session.commit()
    return card


def _make_relearning_card(
    db_session,
    user: User,
    *,
    step_index: int = 0,
    lapses: int = 1,
) -> UserCardDirection:
    word = _make_word(db_session)
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'learning'
    db_session.add(uw)
    db_session.commit()

    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.RELEARNING.value
    card.lapses = lapses
    card.repetitions = 3
    card.interval = 1
    card.ease_factor = DEFAULT_EASE_FACTOR
    card.step_index = step_index
    card.next_review = _now_naive()
    db_session.add(card)
    db_session.commit()
    return card


class TestLeechSuspendAtomicity:
    """Leech suspend must happen in the same commit as the state change."""

    def test_leech_suspend_atomic_state_and_bury_together(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        # Both state change and bury must have persisted atomically
        assert card.state == CardState.RELEARNING.value
        assert card.lapses == LEECH_THRESHOLD
        assert card.buried_until is not None

    def test_leech_no_partial_state_on_sub_threshold(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 2)

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        assert card.state == CardState.RELEARNING.value
        assert card.lapses == LEECH_THRESHOLD - 1
        assert card.buried_until is None  # not yet a leech

    def test_leech_reburies_already_above_threshold(self, db_session):
        user = _make_user(db_session)
        # Card already past threshold and bury expired
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD + 2)
        # Make card available (bury expired)
        card.state = CardState.REVIEW.value
        card.buried_until = None
        db_session.commit()

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        assert card.buried_until is not None


class TestRelearningStepsOrder:
    """RELEARNING_STEPS=[10, 1440] must be applied step 0 then step 1."""

    def test_relearning_step0_gives_10_minutes(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.RELEARNING.value,
            step_index=0,
            repetitions=3,
            interval=1,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=1,
        )
        # After step 0 with know, advance to step 1
        assert result['state'] == CardState.RELEARNING.value
        assert result['step_index'] == 1
        assert result['requeue_minutes'] == RELEARNING_STEPS[1]  # 1440

    def test_relearning_lapse_at_step0_gives_10_minutes(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.RELEARNING.value,
            step_index=0,
            repetitions=3,
            interval=1,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=1,
        )
        assert result['state'] == CardState.RELEARNING.value
        assert result['step_index'] == 0
        assert result['requeue_minutes'] == RELEARNING_STEPS[0]  # 10

    def test_relearning_step1_graduates_to_review(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.RELEARNING.value,
            step_index=1,
            repetitions=4,
            interval=1,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=1,
        )
        assert result['state'] == CardState.REVIEW.value
        assert result['requeue_minutes'] is None
        assert result['days_until_review'] >= 1

    def test_relearning_full_sequence(self, db_session):
        """A lapsed card completes both relearning steps before returning to review."""
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=0)

        # Step 1: lapse the card (REVIEW → RELEARNING step 0)
        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True
        db_session.refresh(card)
        assert card.state == CardState.RELEARNING.value
        assert card.step_index == 0
        requeue_min_0 = result['requeue_minutes']
        assert requeue_min_0 == RELEARNING_STEPS[0]  # 10

        # Step 2: pass step 0 (RELEARNING step 0 → step 1)
        card.next_review = _now_naive()  # make it due
        db_session.commit()
        result2 = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result2['success'] is True
        db_session.refresh(card)
        assert card.state == CardState.RELEARNING.value
        assert card.step_index == 1
        assert result2['requeue_minutes'] == RELEARNING_STEPS[1]  # 1440

        # Step 3: pass step 1 (RELEARNING step 1 → REVIEW)
        card.next_review = _now_naive()
        db_session.commit()
        result3 = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result3['success'] is True
        db_session.refresh(card)
        assert card.state == CardState.REVIEW.value


class TestBuriedCardsExcluded:
    """Buried cards must not appear in due list, even with a fresh query."""

    def test_buried_card_excluded_from_due_list(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        # Bury the card
        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        # Force-refresh: query the DB directly (simulate new request)
        from app.study.models import UserCardDirection as UCD
        db_session.expire_all()  # flush all cached objects

        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=100)
        card_ids = [c.id for c in cards]
        assert card.id not in card_ids

    def test_buried_relearning_card_excluded(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=0)

        # Bury manually (simulate leech scenario)
        card.buried_until = _now_naive() + timedelta(days=7)
        card.state = CardState.RELEARNING.value
        card.next_review = _now_naive()
        db_session.commit()

        db_session.expire_all()
        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=100)
        assert card.id not in [c.id for c in cards]

    def test_bury_expired_card_reappears(self, db_session):
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=0)

        # Set bury to past (expired)
        card.buried_until = _now_naive() - timedelta(hours=1)
        card.next_review = _now_naive() - timedelta(hours=1)
        db_session.commit()

        db_session.expire_all()
        cards = UnifiedSRSService()._get_due_cards(user_id=user.id, limit=100)
        assert card.id in [c.id for c in cards]

    def test_fresh_query_still_excludes_buried_card(self, db_session):
        """Buried card excluded even when fetching via new service instance."""
        user = _make_user(db_session)
        card = _make_review_card(db_session, user, lapses=LEECH_THRESHOLD - 1)

        # Bury via grade
        UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )

        # New service instance, new query (no cached objects)
        service = UnifiedSRSService()
        cards = service._get_due_cards(user_id=user.id, limit=100)
        assert card.id not in [c.id for c in cards]


class TestEaseFactorFloor:
    """ease_factor must never drop below MIN_EASE_FACTOR regardless of lapses."""

    def test_ease_factor_at_min_after_single_lapse(self):
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=MIN_EASE_FACTOR,  # already at floor
            lapses=2,
        )
        assert result['ease_factor'] >= MIN_EASE_FACTOR

    def test_ease_factor_never_below_min_after_many_lapses(self):
        """Simulate 20 lapses by repeatedly calling calculate_sm2_update."""
        ef = DEFAULT_EASE_FACTOR
        interval = 10
        lapses = 0

        for _ in range(20):
            result = UnifiedSRSService.calculate_sm2_update(
                rating=RATING_DONT_KNOW,
                state=CardState.REVIEW.value,
                step_index=0,
                repetitions=5,
                interval=interval,
                ease_factor=ef,
                lapses=lapses,
            )
            ef = result['ease_factor']
            lapses = result['lapses']
            assert ef >= MIN_EASE_FACTOR, (
                f"ease_factor {ef} dropped below MIN_EASE_FACTOR {MIN_EASE_FACTOR} "
                f"after {lapses} lapses"
            )

    def test_ease_factor_never_below_min_after_hard_reviews(self):
        ef = DEFAULT_EASE_FACTOR
        interval = 5

        for _ in range(20):
            result = UnifiedSRSService.calculate_sm2_update(
                rating=RATING_DOUBT,
                state=CardState.REVIEW.value,
                step_index=0,
                repetitions=5,
                interval=interval,
                ease_factor=ef,
                lapses=0,
            )
            ef = result['ease_factor']
            interval = result['interval']
            assert ef >= MIN_EASE_FACTOR

    def test_grade_card_ease_factor_floor_applied(self, db_session):
        """grade_card must persist ease_factor >= MIN_EASE_FACTOR."""
        user = _make_user(db_session)
        # Start with ease just above floor
        card = _make_review_card(
            db_session, user, lapses=0, ease_factor=MIN_EASE_FACTOR + 0.01
        )

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_DONT_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        assert card.ease_factor >= MIN_EASE_FACTOR


def _make_new_card(db_session, user: User) -> UserCardDirection:
    """Create a NEW-state card with no review history."""
    from app.srs.constants import DEFAULT_EASE_FACTOR
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'newcard_{suffix}',
        russian_word=f'новое_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = 'new'
    db_session.add(uw)
    db_session.commit()
    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.NEW.value
    card.repetitions = 0
    card.interval = 0
    card.ease_factor = DEFAULT_EASE_FACTOR
    card.step_index = 0
    card.lapses = 0
    card.next_review = datetime.now(timezone.utc).replace(tzinfo=None)
    card.first_reviewed = None
    card.last_reviewed = None
    db_session.add(card)
    db_session.commit()
    return card


class TestFirstReviewedCanonicalPath:
    """grade_card must set first_reviewed on first grade (Task 1 fix, H2)."""

    def test_new_card_graded_sets_first_reviewed(self, db_session):
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)
        assert card.first_reviewed is None

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        db_session.refresh(card)
        assert card.first_reviewed is not None
        # Must be naive UTC
        assert card.first_reviewed.tzinfo is None

    def test_subsequent_grade_does_not_overwrite_first_reviewed(self, db_session):
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        UnifiedSRSService().grade_card(card_id=card.id, rating=RATING_KNOW, user_id=user.id)
        db_session.refresh(card)
        first = card.first_reviewed

        # Make card due again then grade again
        card.next_review = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.commit()
        UnifiedSRSService().grade_card(card_id=card.id, rating=RATING_KNOW, user_id=user.id)
        db_session.refresh(card)
        assert card.first_reviewed == first

    def test_last_reviewed_is_naive_utc(self, db_session):
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        UnifiedSRSService().grade_card(card_id=card.id, rating=RATING_KNOW, user_id=user.id)
        db_session.refresh(card)
        assert card.last_reviewed is not None
        assert card.last_reviewed.tzinfo is None

    def test_count_new_cards_today_sees_canonical_graded_card(self, db_session):
        from app.srs.counting import count_new_cards_today
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        before = count_new_cards_today(user.id)
        UnifiedSRSService().grade_card(card_id=card.id, rating=RATING_KNOW, user_id=user.id)
        after = count_new_cards_today(user.id)
        assert after == before + 1


class TestGradeCardCallerCommits:
    """grade_card flushes only; caller must commit (Task 2, M1)."""

    def test_grade_changes_visible_in_same_session_before_commit(self, db_session):
        """Changes flushed by grade_card are visible within the same session."""
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        # Flush makes changes visible to same-session queries
        db_session.refresh(card)
        assert card.state != CardState.NEW.value
        assert card.first_reviewed is not None

    def test_caller_rollback_undoes_grade(self, db_session):
        """If caller rolls back before committing, grade changes are undone."""
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        # Caller decides to roll back (e.g. downstream operation failed)
        db_session.rollback()

        db_session.refresh(card)
        assert card.state == CardState.NEW.value
        assert card.first_reviewed is None

    def test_exception_after_grade_rolled_back(self, db_session):
        """Simulated downstream exception causes grade to be rolled back."""
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        try:
            result = UnifiedSRSService().grade_card(
                card_id=card.id, rating=RATING_KNOW, user_id=user.id,
            )
            assert result['success'] is True
            # Simulate a downstream failure (e.g. XP write, plan recalc)
            raise ValueError("downstream failure after grade")
        except ValueError:
            db_session.rollback()

        db_session.refresh(card)
        assert card.state == CardState.NEW.value, (
            "Grade state change must not persist when caller rolls back"
        )
        assert card.first_reviewed is None

    def test_commit_after_grade_persists_changes(self, db_session):
        """When caller commits, all graded fields are persisted."""
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        # Caller commits
        db_session.commit()

        db_session.refresh(card)
        assert card.state != CardState.NEW.value
        assert card.first_reviewed is not None
        assert card.last_reviewed is not None

    def test_grading_and_additional_write_in_same_transaction(self, db_session):
        """grade_card + additional writes share one transaction and commit together."""
        user = _make_user(db_session)
        card = _make_new_card(db_session, user)

        # Simulate what a route would do: grade + additional write in one tx
        result = UnifiedSRSService().grade_card(
            card_id=card.id, rating=RATING_KNOW, user_id=user.id,
        )
        assert result['success'] is True

        # Additional write in the same session (simulating XP award, etc.)
        user.about = "xp_awarded"
        db_session.flush()

        # Commit everything together
        db_session.commit()

        db_session.refresh(card)
        db_session.refresh(user)
        assert card.state != CardState.NEW.value
        assert user.about == "xp_awarded"
