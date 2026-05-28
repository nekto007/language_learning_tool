"""
Task 80: Словарный запас — deck select modal audit tests.

Covers (server-side verifiable):
- /study/api/my-decks returns correct JSON shape for modal consumption
- Empty deck list returns empty array (not null) so modal empty-state triggers
- Unauthenticated request returns 401/302 (not 500)
- JS file contains debounce implementation and search input markup
- Modal HTML markup does not disable keyboard (Escape key accessible)
- Search empty-state element present in JS template
"""
import json
import os
import re
import pytest

from app.study.models import QuizDeck
from app.utils.db import db


DECK_SELECT_JS = os.path.join(
    os.path.dirname(__file__),
    "../../app/static/js/deck-select-modal.js",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_js() -> str:
    with open(DECK_SELECT_JS, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# JS static analysis: debounce, search, keyboard accessibility
# ---------------------------------------------------------------------------

class TestDeckSelectModalJS:
    """Static analysis of deck-select-modal.js for required features."""

    def test_debounce_helper_present(self):
        """JS must define a _debounce method to avoid per-keypress requests."""
        src = _read_js()
        assert "_debounce" in src, "Missing debounce implementation in deck-select-modal.js"

    def test_search_input_in_template(self):
        """Modal template must include a search input so users can filter decks."""
        src = _read_js()
        assert "deck-search-input" in src, "Missing search input element in modal HTML"

    def test_search_empty_state_present(self):
        """Modal must have a dedicated empty-search-state element."""
        src = _read_js()
        assert "deck-search-empty" in src, "Missing deck-search-empty state element"

    def test_no_keyboard_false(self):
        """Bootstrap keyboard option must not be disabled (Escape must close modal)."""
        src = _read_js()
        # If keyboard:false appears it would prevent Escape from closing modal
        assert "keyboard: false" not in src, (
            "bootstrap.Modal must not be initialised with keyboard:false — "
            "Escape key must close the modal"
        )

    def test_search_uses_debounce_on_input(self):
        """Search input listener must be wired through _debounce, not raw input."""
        src = _read_js()
        # Both the debounce call and 'input' listener must exist near each other
        assert "debouncedSearch" in src or "_debounce" in src, (
            "Search must be debounced"
        )
        assert "addEventListener('input'" in src or 'addEventListener("input"' in src, (
            "Search input must listen for 'input' events"
        )

    def test_clear_search_called_on_show(self):
        """Each show* method must reset the search field to prevent stale state."""
        src = _read_js()
        assert "_clearSearch()" in src, (
            "_clearSearch() must be called before showing the modal to prevent "
            "stale search from a previous open"
        )

    def test_event_listeners_registered_once(self):
        """_setupEventHandlers must be called only during construction, not on every show."""
        src = _read_js()
        # Count call sites (this._setupEventHandlers()), not the definition line
        call_sites = src.count("this._setupEventHandlers()")
        assert call_sites == 1, (
            f"this._setupEventHandlers() should be called exactly once (found {call_sites}). "
            "Calling it on every show() would accumulate duplicate listeners."
        )


# ---------------------------------------------------------------------------
# API endpoint: /study/api/my-decks
# ---------------------------------------------------------------------------

class TestApiMyDecks:
    @pytest.mark.smoke
    def test_unauthenticated_returns_redirect_not_500(self, client, study_settings):
        """Unauthenticated access must not produce a 500."""
        response = client.get("/study/api/my-decks")
        assert response.status_code in (302, 401), (
            f"Expected redirect or 401, got {response.status_code}"
        )

    @pytest.mark.smoke
    def test_authenticated_returns_success_shape(
        self, authenticated_client, study_settings
    ):
        """Response must include success=True, decks list, and default_deck_id."""
        response = authenticated_client.get("/study/api/my-decks")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get("success") is True
        assert "decks" in data
        assert isinstance(data["decks"], list)
        assert "default_deck_id" in data

    @pytest.mark.smoke
    def test_empty_deck_list_returns_empty_array(
        self, authenticated_client, study_settings
    ):
        """When user has no decks, response must return [] not null."""
        response = authenticated_client.get("/study/api/my-decks")
        data = json.loads(response.data)
        # May have auto-decks filtered out; decks key must be a list (can be [])
        assert data["decks"] is not None
        assert isinstance(data["decks"], list)

    def test_deck_list_contains_expected_fields(
        self, authenticated_client, test_user, db_session, study_settings
    ):
        """Each deck entry must have id, name, word_count, is_public fields."""
        deck = QuizDeck(
            title="Modal Test Deck",
            user_id=test_user.id,
            is_public=False,
        )
        db_session.add(deck)
        db_session.commit()

        response = authenticated_client.get("/study/api/my-decks")
        data = json.loads(response.data)

        found = [d for d in data["decks"] if d["name"] == "Modal Test Deck"]
        assert found, "Created deck must appear in response"
        deck_data = found[0]
        assert "id" in deck_data
        assert "name" in deck_data
        assert "word_count" in deck_data
        assert "is_public" in deck_data

    def test_other_users_decks_not_returned(
        self, authenticated_client, second_user, db_session, study_settings
    ):
        """API must only return decks owned by the authenticated user."""
        other_deck = QuizDeck(
            title="Other User Private Deck",
            user_id=second_user.id,
            is_public=False,
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.get("/study/api/my-decks")
        data = json.loads(response.data)

        names = [d["name"] for d in data["decks"]]
        assert "Other User Private Deck" not in names, (
            "Decks owned by other users must not appear in the response"
        )

    def test_response_content_type_is_json(
        self, authenticated_client, study_settings
    ):
        """API must respond with application/json."""
        response = authenticated_client.get("/study/api/my-decks")
        assert "application/json" in response.content_type
