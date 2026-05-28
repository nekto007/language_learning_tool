"""
Task 28: Study — deck management audit tests.
Covers: 404 for missing deck, ownership enforcement, cascade delete, empty-deck quiz guard.
"""
import pytest

from app.study.models import QuizDeck, QuizDeckWord, QuizResult
from app.utils.db import db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user_deck(db_session, test_user):
    """A deck owned by test_user."""
    deck = QuizDeck(
        title="Audit Test Deck",
        user_id=test_user.id,
        is_public=False,
    )
    db_session.add(deck)
    db_session.commit()
    return deck


@pytest.fixture
def deck_with_words(db_session, test_user):
    """A deck with two custom words."""
    deck = QuizDeck(
        title="Deck With Words",
        user_id=test_user.id,
        is_public=False,
    )
    db_session.add(deck)
    db_session.flush()

    for i in range(2):
        word = QuizDeckWord(
            deck_id=deck.id,
            custom_english=f"word_{i}",
            custom_russian=f"слово_{i}",
        )
        db_session.add(word)

    db_session.commit()
    return deck


@pytest.fixture
def deck_with_result(db_session, test_user):
    """A deck that has a QuizResult row."""
    deck = QuizDeck(
        title="Deck With Result",
        user_id=test_user.id,
        is_public=False,
    )
    db_session.add(deck)
    db_session.flush()

    result = QuizResult(
        deck_id=deck.id,
        user_id=test_user.id,
        total_questions=5,
        correct_answers=4,
        score_percentage=80.0,
        time_taken=120,
    )
    db_session.add(result)
    db_session.commit()
    return deck


@pytest.fixture
def other_user_deck(db_session, second_user):
    """A deck owned by second_user (not the authenticated user)."""
    deck = QuizDeck(
        title="Other User's Deck",
        user_id=second_user.id,
        is_public=False,
    )
    db_session.add(deck)
    db_session.commit()
    return deck


# ---------------------------------------------------------------------------
# 1. GET /study/my-decks/<id>/edit — 404 for non-existent deck
# ---------------------------------------------------------------------------

class TestDeckNotFound:
    def test_edit_nonexistent_deck_returns_404(self, authenticated_client, study_settings):
        response = authenticated_client.get("/study/my-decks/99999/edit")
        assert response.status_code == 404

    def test_delete_nonexistent_deck_returns_404(self, authenticated_client, study_settings):
        response = authenticated_client.post("/study/my-decks/99999/delete")
        assert response.status_code == 404

    def test_quiz_deck_nonexistent_returns_404(self, authenticated_client, study_settings):
        response = authenticated_client.get("/study/quiz/deck/99999")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 2. Ownership — another user cannot edit or delete someone else's deck
# ---------------------------------------------------------------------------

class TestDeckOwnership:
    def test_edit_other_users_deck_redirects(
        self, authenticated_client, other_user_deck, study_settings
    ):
        """Authenticated user cannot edit deck owned by second_user."""
        response = authenticated_client.get(
            f"/study/my-decks/{other_user_deck.id}/edit"
        )
        # Redirected away (access denied), not 200
        assert response.status_code == 302
        assert "/edit" not in response.location

    def test_delete_other_users_deck_forbidden(
        self, authenticated_client, other_user_deck, study_settings, db_session
    ):
        """Authenticated user cannot delete deck owned by second_user."""
        response = authenticated_client.post(
            f"/study/my-decks/{other_user_deck.id}/delete"
        )
        # Should redirect with error (DeckService returns 'Нет доступа')
        assert response.status_code in (302, 403)
        # Deck must still exist
        db_session.expire_all()
        assert QuizDeck.query.get(other_user_deck.id) is not None

    def test_quiz_other_users_private_deck_redirects(
        self, authenticated_client, other_user_deck, study_settings
    ):
        """Private deck owned by another user is inaccessible via quiz route."""
        response = authenticated_client.get(
            f"/study/quiz/deck/{other_user_deck.id}"
        )
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# 3. Cascade delete: deleting a deck removes its QuizDeckWord and QuizResult rows
# ---------------------------------------------------------------------------

class TestDeckCascadeDelete:
    def test_delete_deck_removes_deck_words(
        self, authenticated_client, deck_with_words, study_settings, db_session
    ):
        deck_id = deck_with_words.id
        word_ids = [w.id for w in deck_with_words.words.all()]
        assert word_ids, "fixture must create words"

        authenticated_client.post(f"/study/my-decks/{deck_id}/delete")

        for wid in word_ids:
            assert QuizDeckWord.query.get(wid) is None, (
                f"QuizDeckWord {wid} should have been cascade-deleted"
            )

    def test_delete_deck_removes_quiz_results(
        self, authenticated_client, deck_with_result, study_settings, db_session
    ):
        deck_id = deck_with_result.id
        result_count_before = QuizResult.query.filter_by(deck_id=deck_id).count()
        assert result_count_before > 0, "fixture must create a result"

        authenticated_client.post(f"/study/my-decks/{deck_id}/delete")

        db_session.expire_all()
        remaining = QuizResult.query.filter_by(deck_id=deck_id).count()
        assert remaining == 0, "QuizResult rows should have been cascade-deleted"


# ---------------------------------------------------------------------------
# 4. Empty deck does not crash quiz start
# ---------------------------------------------------------------------------

class TestEmptyDeckQuiz:
    def test_quiz_deck_with_no_words_redirects_gracefully(
        self, authenticated_client, user_deck, study_settings
    ):
        """Empty deck redirects with a warning instead of crashing."""
        assert user_deck.word_count == 0, "user_deck fixture must have 0 words"
        response = authenticated_client.get(f"/study/quiz/deck/{user_deck.id}")
        # Should redirect (flash warning), not 500
        assert response.status_code == 302
        assert response.status_code != 500

    def test_quiz_deck_with_words_starts_successfully(
        self, authenticated_client, deck_with_words, study_settings
    ):
        """Deck with words renders the quiz page (200)."""
        response = authenticated_client.get(
            f"/study/quiz/deck/{deck_with_words.id}"
        )
        assert response.status_code == 200
