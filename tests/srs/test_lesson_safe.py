"""Tests for lesson_safe (lesson_mode) flag and daily limit enforcement.

Covers:
- lesson_mode=True bypasses only the global new-card daily limit
- Free study without lesson_mode respects new_words_per_day setting
- Parallel-style requests with lesson_mode don't create duplicate UserCardDirection rows
- activate_srs=False in card lessons produces display-only cards (no SRS records)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.srs.constants import CardState
from app.srs.counting import count_new_cards_today, get_new_card_budget
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.utils.db import db as real_db
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _make_user(db_session) -> User:
    user = User(
        username=f"lsafe_{_uid()}",
        email=f"lsafe_{_uid()}@example.com",
        active=True,
    )
    user.set_password("secret123")
    db_session.add(user)
    db_session.commit()
    return user


def _make_word(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f"lsafe_{_uid()}",
        russian_word=f"безопасно_{_uid()}",
        level="A1",
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_settings(db_session, user, *, new_per_day: int = 5) -> StudySettings:
    settings = StudySettings(user_id=user.id)
    settings.new_words_per_day = new_per_day
    settings.reviews_per_day = 20
    db_session.add(settings)
    db_session.commit()
    return settings


def _mark_card_new_today(db_session, user: User, word: CollectionWords) -> UserCardDirection:
    """Create a UserCardDirection that counts as first-reviewed today (consumes new budget)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    uw = UserWord(user_id=user.id, word_id=word.id)
    db_session.add(uw)
    db_session.flush()
    card = UserCardDirection(user_word_id=uw.id, direction="eng-rus")
    card.state = CardState.LEARNING.value
    card.first_reviewed = now
    card.last_reviewed = now
    card.next_review = now + timedelta(minutes=10)
    db_session.add(card)
    db_session.commit()
    return card


# ---------------------------------------------------------------------------
# lesson_mode bypasses only the new-card limit
# ---------------------------------------------------------------------------

class TestLessonModeBypassesOnlyNewCardLimit:
    """lesson_mode=True lets a new card through even when new-card budget is 0."""

    @pytest.mark.smoke
    def test_lesson_mode_true_bypasses_global_new_card_limit(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """With new_words_per_day=0, lesson_mode=True allows a new card to be graded."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[0]
        response = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": True,
            "lesson_mode": True,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_lesson_mode_does_not_bypass_review_cards_are_never_blocked(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """Review cards (first_reviewed in the past) are never subject to the new-card limit
        regardless of lesson_mode. The bypass is only relevant for genuinely new cards."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[0]
        # Pre-create a UserWord and UserCardDirection with first_reviewed in the past
        from app.study.models import UserWord, UserCardDirection
        from app.auth.models import User
        # Get the authenticated user from DB
        user = db_session.query(User).filter(
            User.email == "test@example.com"
        ).first()
        if user is None:
            # Fall back to most recently created user
            user = db_session.query(User).order_by(User.id.desc()).first()

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        if not uw:
            uw = UserWord(user_id=user.id, word_id=word.id)
            db_session.add(uw)
            db_session.flush()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        card = UserCardDirection.query.filter_by(
            user_word_id=uw.id, direction="eng-rus"
        ).first()
        if not card:
            card = UserCardDirection(user_word_id=uw.id, direction="eng-rus")
            db_session.add(card)
            db_session.flush()

        # Mark as previously reviewed (not a new card)
        card.first_reviewed = now - timedelta(days=3)
        card.last_reviewed = now - timedelta(hours=1)
        card.state = CardState.REVIEW.value
        card.next_review = now - timedelta(minutes=5)
        db_session.commit()

        # Should succeed without lesson_mode because it's a review, not a new card
        response = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": False,
            "lesson_mode": False,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_lesson_mode_true_does_not_bypass_review_limits_separately(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """lesson_mode only bypasses the NEW-card check. The review path is always open."""
        # Set new limit to 0, reviews remain at 20
        study_settings.new_words_per_day = 0
        study_settings.reviews_per_day = 20
        db_session.commit()

        word = test_words_list[1]
        # Ensure the card already has first_reviewed set (it's a review card)
        from app.study.models import UserWord, UserCardDirection
        from app.auth.models import User
        user = db_session.query(User).filter_by(email="test@example.com").first()
        if user is None:
            user = db_session.query(User).order_by(User.id.desc()).first()

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        if not uw:
            uw = UserWord(user_id=user.id, word_id=word.id)
            db_session.add(uw)
            db_session.flush()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        card = UserCardDirection.query.filter_by(user_word_id=uw.id, direction="eng-rus").first()
        if not card:
            card = UserCardDirection(user_word_id=uw.id, direction="eng-rus")
            db_session.add(card)
            db_session.flush()
        card.first_reviewed = now - timedelta(days=5)
        card.last_reviewed = now - timedelta(days=1)
        card.state = CardState.REVIEW.value
        card.next_review = now - timedelta(hours=1)
        db_session.commit()

        response = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": False,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# Free study respects daily limits
# ---------------------------------------------------------------------------

class TestFreeStudyRespectsLimits:
    """Without lesson_mode, /api/update-study-item enforces new_words_per_day."""

    @pytest.mark.smoke
    def test_free_study_blocked_when_limit_zero(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """new_words_per_day=0 blocks a brand-new card without lesson_mode."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[2]
        response = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": True,
        })

        # Either 429 or 200 with error field
        assert response.status_code in (200, 429)
        data = response.get_json()
        if response.status_code == 200:
            assert data.get("success") is False
            assert "daily_limit" in (data.get("error") or "").lower()
        else:
            assert data.get("error") == "daily_limit_exceeded"

    def test_free_study_allowed_when_budget_available(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """When new_words_per_day > 0 and no cards reviewed today, a new card is allowed."""
        study_settings.new_words_per_day = 10
        db_session.commit()

        word = test_words_list[3]
        response = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": True,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_free_study_blocked_after_budget_consumed(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """After consuming all new-card slots, the next free-study new card is blocked."""
        study_settings.new_words_per_day = 1
        db_session.commit()

        # Grade the first word (consumes the 1 slot)
        word_a = test_words_list[4]
        resp1 = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word_a.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": True,
        })
        assert resp1.status_code == 200
        assert resp1.get_json()["success"] is True

        # Grade a second brand-new word — should be blocked
        word_b = test_words_list[5]
        resp2 = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word_b.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": True,
        })

        assert resp2.status_code in (200, 429)
        data2 = resp2.get_json()
        if resp2.status_code == 200:
            assert data2.get("success") is False
            assert "daily_limit" in (data2.get("error") or "").lower()
        else:
            assert data2.get("error") == "daily_limit_exceeded"

    def test_explicit_lesson_mode_false_still_enforces(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """lesson_mode=False (explicit) does not bypass the limit."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[6]
        response = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "is_new": True,
            "lesson_mode": False,
        })

        assert response.status_code in (200, 429)
        data = response.get_json()
        if response.status_code == 200:
            assert data.get("success") is False
        else:
            assert data.get("error") == "daily_limit_exceeded"


# ---------------------------------------------------------------------------
# Parallel requests don't create duplicate cards
# ---------------------------------------------------------------------------

class TestLessonModeNoDuplicateCards:
    """Two sequential lesson_mode requests for the same word yield one UserCardDirection."""

    @pytest.mark.smoke
    def test_duplicate_grade_same_word_direction_no_extra_row(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """Grading the same word twice with lesson_mode=True must not create two
        UserCardDirection rows for the same (user_word_id, direction) pair."""
        study_settings.new_words_per_day = 10
        db_session.commit()

        word = test_words_list[0]

        resp1 = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "lesson_mode": True,
        })
        assert resp1.status_code == 200
        assert resp1.get_json()["success"] is True

        resp2 = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "lesson_mode": True,
        })
        assert resp2.status_code == 200
        assert resp2.get_json()["success"] is True

        # Verify exactly one UserCardDirection for this word / direction combo
        from app.auth.models import User
        from app.study.models import UserWord, UserCardDirection
        user = db_session.query(User).filter_by(email="test@example.com").first()
        if user is None:
            user = db_session.query(User).order_by(User.id.desc()).first()

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        assert uw is not None
        directions = UserCardDirection.query.filter_by(
            user_word_id=uw.id, direction="eng-rus"
        ).all()
        assert len(directions) == 1, (
            f"Expected 1 UserCardDirection for word {word.id}, got {len(directions)}"
        )

    def test_lesson_mode_budget_saturation_still_one_direction_row(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """With budget already at zero, lesson_mode=True still only creates one card row."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[1]

        for _ in range(2):
            resp = authenticated_client.post("/study/api/update-study-item", json={
                "word_id": word.id,
                "direction": "eng-rus",
                "quality": 3,
                "lesson_mode": True,
            })
            assert resp.status_code == 200
            assert resp.get_json()["success"] is True

        from app.auth.models import User
        from app.study.models import UserWord, UserCardDirection
        user = db_session.query(User).filter_by(email="test@example.com").first()
        if user is None:
            user = db_session.query(User).order_by(User.id.desc()).first()

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        assert uw is not None
        count = UserCardDirection.query.filter_by(
            user_word_id=uw.id, direction="eng-rus"
        ).count()
        assert count == 1


# ---------------------------------------------------------------------------
# activate_srs=False produces display-only cards (no SRS records)
# ---------------------------------------------------------------------------

class TestActivateSrsFalseDisplayOnlyCards:
    """When SRS budget is 0, _build_cards_for_words with activate_srs=False
    must not create UserWord or UserCardDirection records for words that
    have never been in SRS before."""

    def test_display_only_cards_no_usercarddirection_created(self, db_session):
        """activate_srs=False for an unseen word produces a card dict with
        direction_id=None and does NOT write to the database."""
        from app.curriculum.routes.card_lessons import _build_cards_for_words

        user = _make_user(db_session)
        word = _make_word(db_session)

        # Verify no existing UserWord
        assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).first() is None

        cards = _build_cards_for_words([word], user.id, activate_srs=False)

        assert len(cards) == 1
        assert cards[0]["direction_id"] is None
        assert cards[0]["is_new"] is True

        # No UserWord or UserCardDirection should have been created
        assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).first() is None

    def test_display_only_does_not_consume_budget(self, db_session):
        """After calling _build_cards_for_words with activate_srs=False, the
        new-card budget remains unchanged."""
        from app.curriculum.routes.card_lessons import _build_cards_for_words

        user = _make_user(db_session)
        _make_settings(db_session, user, new_per_day=5)
        word = _make_word(db_session)

        budget_before, _ = get_new_card_budget(user.id, real_db)
        _build_cards_for_words([word], user.id, activate_srs=False)
        budget_after, _ = get_new_card_budget(user.id, real_db)

        assert budget_before == budget_after

    def test_activate_srs_true_creates_direction_and_consumes_budget(self, db_session):
        """activate_srs=True for a new word creates a UserCardDirection and
        will appear in count_new_cards_today once first_reviewed is set."""
        from app.curriculum.routes.card_lessons import _build_cards_for_words

        user = _make_user(db_session)
        _make_settings(db_session, user, new_per_day=5)
        word = _make_word(db_session)

        cards = _build_cards_for_words([word], user.id, activate_srs=True)

        assert len(cards) == 1
        assert cards[0]["direction_id"] is not None
        assert cards[0]["is_new"] is True

        uw = UserWord.query.filter_by(user_id=user.id, word_id=word.id).first()
        assert uw is not None
        card = UserCardDirection.query.filter_by(
            user_word_id=uw.id, direction="eng-rus"
        ).first()
        assert card is not None

    def test_activate_srs_false_existing_word_still_shows_card(self, db_session):
        """If a UserCardDirection already exists, activate_srs=False still
        includes the card (not display-only) because the direction is found."""
        from app.curriculum.routes.card_lessons import _build_cards_for_words

        user = _make_user(db_session)
        word = _make_word(db_session)

        # Pre-create the SRS record
        uw = UserWord(user_id=user.id, word_id=word.id)
        db_session.add(uw)
        db_session.flush()
        card = UserCardDirection(user_word_id=uw.id, direction="eng-rus")
        card.state = CardState.NEW.value
        db_session.add(card)
        db_session.commit()

        cards = _build_cards_for_words([word], user.id, activate_srs=False)

        assert len(cards) == 1
        # The existing direction is returned — direction_id is set (not None)
        assert cards[0]["direction_id"] == card.id


# ---------------------------------------------------------------------------
# Budget counting with lesson_mode — canonical source
# ---------------------------------------------------------------------------

class TestBudgetAfterLessonModeGrading:
    """After lesson_mode grading, count_new_cards_today reflects the review."""

    def test_lesson_mode_grade_increments_new_card_count(
        self, authenticated_client, test_words_list, study_settings, db_session
    ):
        """Grading a new card with lesson_mode=True still records first_reviewed
        and increments count_new_cards_today."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        from app.auth.models import User
        user = db_session.query(User).filter_by(email="test@example.com").first()
        if user is None:
            user = db_session.query(User).order_by(User.id.desc()).first()

        count_before = count_new_cards_today(user.id, real_db)

        word = test_words_list[7]
        resp = authenticated_client.post("/study/api/update-study-item", json={
            "word_id": word.id,
            "direction": "eng-rus",
            "quality": 3,
            "lesson_mode": True,
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        count_after = count_new_cards_today(user.id, real_db)
        assert count_after == count_before + 1
