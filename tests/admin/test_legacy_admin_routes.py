# tests/admin/test_legacy_admin_routes.py

"""
Smoke tests for legacy admin routes in main_routes.py, modules.py, and quiz_decks.py.
These files have low coverage because they were present before the sub-blueprint refactor.
Goal: bring each from <40% to >60% by covering the GET happy paths.

Note: These tests use admin_client (which logs in via Flask-Login) without mock_admin_user.
mock_admin_user is only available in tests/admin/routes/ via its conftest.py.
"""

import uuid

import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# main_routes.py — curriculum routes
# ---------------------------------------------------------------------------


class TestMainRoutesCurriculum:
    """Smoke tests for curriculum routes still in main_routes.py."""

    @pytest.mark.smoke
    def test_curriculum_index_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/curriculum")
        assert resp.status_code == 200

    def test_level_list_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/curriculum/levels")
        assert resp.status_code == 200

    def test_module_list_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/curriculum/modules")
        assert resp.status_code == 200

    def test_lesson_list_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/curriculum/lessons")
        assert resp.status_code == 200

    def test_user_progress_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/curriculum/progress")
        assert resp.status_code == 200

    def test_import_curriculum_get_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/curriculum/import")
        assert resp.status_code == 200

    def test_curriculum_routes_require_admin(self, client):
        for path in [
            "/admin/curriculum",
            "/admin/curriculum/levels",
            "/admin/curriculum/modules",
            "/admin/curriculum/lessons",
            "/admin/curriculum/progress",
            "/admin/curriculum/import",
        ]:
            resp = client.get(path)
            assert resp.status_code == 302, f"{path} should redirect unauthenticated"


# ---------------------------------------------------------------------------
# modules.py — module admin routes
# ---------------------------------------------------------------------------


class TestModulesAdmin:
    """Smoke tests for the module admin routes registered via register_module_admin_routes."""

    @pytest.mark.smoke
    @patch("app.admin.modules.ModuleService")
    def test_modules_list_renders(self, mock_service, app, db_session, admin_client):
        mock_service.get_all_modules.return_value = []
        mock_service.get_module_statistics.return_value = {}

        resp = admin_client.get("/admin/modules")
        assert resp.status_code == 200

    @patch("app.admin.modules.ModuleService")
    def test_modules_statistics_renders(self, mock_service, app, db_session, admin_client):
        mock_service.get_module_statistics.return_value = {}

        resp = admin_client.get("/admin/modules/statistics")
        assert resp.status_code == 200

    def test_modules_routes_require_admin(self, client):
        resp = client.get("/admin/modules")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# quiz_decks.py — quiz deck admin routes
# ---------------------------------------------------------------------------


class TestQuizDecksAdmin:
    """Smoke tests for quiz deck admin routes."""

    @pytest.mark.smoke
    def test_quiz_decks_list_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/quiz-decks")
        assert resp.status_code == 200

    def test_quiz_deck_create_get_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/quiz-decks/create")
        assert resp.status_code == 200

    def test_quiz_decks_require_admin(self, client):
        resp = client.get("/admin/quiz-decks")
        assert resp.status_code == 302

    def test_api_words_search_returns_json(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/api/words/search?q=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# audit.py — coverage for __repr__ and rollback path
# ---------------------------------------------------------------------------


class TestAuditLog:
    @pytest.mark.smoke
    def test_admin_audit_log_repr(self, app, db_session, test_user):
        from app.admin.audit import AdminAuditLog

        entry = AdminAuditLog(
            admin_id=test_user.id,
            action="test.action",
            target_type="word",
            target_id=42,
        )
        db_session.add(entry)
        db_session.flush()
        assert "AdminAuditLog" in repr(entry)
        assert "test.action" in repr(entry)

    def test_log_admin_action_swallows_write_failure(self, app, db_session, caplog):
        """When begin_nested / flush fails, log_admin_action doesn't raise."""
        from unittest.mock import patch

        from app.admin.audit import log_admin_action

        with patch("app.admin.audit.db.session.begin_nested", side_effect=RuntimeError("boom")):
            # Should not raise
            log_admin_action(None, "test.action", target_type="word", target_id=1)


# ---------------------------------------------------------------------------
# main_routes.py — helper function unit tests
# ---------------------------------------------------------------------------


class TestMainRoutesHelpers:
    """Unit tests for pure helper functions in main_routes.py."""

    @pytest.mark.smoke
    def test_get_level_name_known_codes(self):
        from app.admin.main_routes import get_level_name

        assert get_level_name("A1") == "Beginner"
        assert get_level_name("A2") == "Elementary"
        assert get_level_name("B1") == "Intermediate"
        assert get_level_name("B2") == "Upper Intermediate"
        assert get_level_name("C1") == "Advanced"

    def test_get_level_name_unknown_code(self):
        from app.admin.main_routes import get_level_name

        assert get_level_name("C2") == "Level C2"
        assert get_level_name("X9") == "Level X9"

    @pytest.mark.smoke
    def test_get_level_order_known_codes(self):
        from app.admin.main_routes import get_level_order

        assert get_level_order("A1") == 1
        assert get_level_order("A2") == 2
        assert get_level_order("B1") == 3
        assert get_level_order("B2") == 4
        assert get_level_order("C1") == 5

    def test_get_level_order_unknown_returns_99(self):
        from app.admin.main_routes import get_level_order

        assert get_level_order("C2") == 99
        assert get_level_order("X9") == 99

    @pytest.mark.smoke
    def test_process_grammar_fill_in_blank(self):
        from app.admin.main_routes import process_grammar

        data = {
            "rule": "Test rule",
            "description": "Test desc",
            "examples": ["Ex 1"],
            "exercises": [
                {
                    "type": "fill_in_blank",
                    "prompt": "Fill ___",
                    "explanation": "Explanation",
                    "correct_answer": ["answer"],
                    "alternative_answers": ["alt"],
                }
            ],
        }
        result = process_grammar(data)
        assert result["rule"] == "Test rule"
        assert result["description"] == "Test desc"
        assert result["examples"] == ["Ex 1"]
        assert len(result["exercises"]) == 1
        ex = result["exercises"][0]
        assert ex["type"] == "fill_in_blank"
        assert ex["answer"] == ["answer"]
        assert ex["alternative_answers"] == ["alt"]

    def test_process_grammar_multiple_choice(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "multiple_choice",
                    "prompt": "Choose",
                    "explanation": "",
                    "question": "What is it?",
                    "options": ["A", "B", "C"],
                    "correct_index": 0,
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert ex["options"] == ["A", "B", "C"]
        assert ex["answer"] == 0
        assert ex["question"] == "What is it?"

    def test_process_grammar_true_false(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "true_false",
                    "prompt": "Is it true?",
                    "explanation": "",
                    "question": "Is it?",
                    "correct_answer": True,
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert ex["answer"] is True
        assert ex["question"] == "Is it?"

    def test_process_grammar_match(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "match",
                    "prompt": "Match",
                    "explanation": "",
                    "pairs": [{"left": "a", "right": "b"}],
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert ex["pairs"] == [{"left": "a", "right": "b"}]

    def test_process_grammar_reorder(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "reorder",
                    "prompt": "Reorder",
                    "explanation": "",
                    "words": ["word1", "word2"],
                    "correct_answer": "word1 word2",
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert ex["words"] == ["word1", "word2"]
        assert ex["answer"] == "word1 word2"

    def test_process_grammar_translation(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "translation",
                    "prompt": "Translate",
                    "explanation": "",
                    "correct_answer": "run",
                    "alternative_answers": ["sprint"],
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert ex["answer"] == "run"
        assert ex["alternative_answers"] == ["sprint"]

    def test_process_grammar_unknown_type_fallback(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "custom_type",
                    "prompt": "Custom",
                    "explanation": "",
                    "answer": "x",
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert ex["answer"] == "x"

    def test_process_grammar_no_exercises_key(self):
        from app.admin.main_routes import process_grammar

        data = {"rule": "rule", "description": "desc", "examples": []}
        result = process_grammar(data)
        assert result["exercises"] == []
        assert result["rule"] == "rule"

    def test_process_grammar_fill_in_blank_no_alternatives(self):
        from app.admin.main_routes import process_grammar

        data = {
            "exercises": [
                {
                    "type": "fill_in_blank",
                    "prompt": "Fill",
                    "explanation": "",
                    "correct_answer": ["x"],
                    # no alternative_answers
                }
            ]
        }
        result = process_grammar(data)
        ex = result["exercises"][0]
        assert "alternative_answers" not in ex


# ---------------------------------------------------------------------------
# modules.py — extended route coverage
# ---------------------------------------------------------------------------


class TestModulesRoutesExtended:
    """Extended route tests for modules.py to improve coverage."""

    @pytest.fixture
    def module_in_db(self, db_session):
        from app.modules.models import SystemModule

        mod = SystemModule(
            code=f"test_{uuid.uuid4().hex[:6]}",
            name="Test Module",
            description="A test module",
            is_active=True,
        )
        db_session.add(mod)
        db_session.commit()
        return mod

    @pytest.mark.smoke
    def test_modules_create_get_renders(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/modules/create")
        assert resp.status_code == 200

    @pytest.mark.smoke
    def test_modules_edit_get_renders(self, app, db_session, admin_client, module_in_db):
        resp = admin_client.get(f"/admin/modules/{module_in_db.id}/edit")
        assert resp.status_code == 200

    def test_modules_edit_not_found_redirects(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/modules/99999/edit")
        assert resp.status_code == 302

    def test_modules_delete_not_found_returns_404(self, app, db_session, admin_client):
        resp = admin_client.post("/admin/modules/99999/delete")
        assert resp.status_code == 404

    @pytest.mark.smoke
    def test_modules_users_get_renders(self, app, db_session, admin_client, module_in_db):
        resp = admin_client.get(f"/admin/modules/{module_in_db.id}/users")
        assert resp.status_code == 200

    def test_modules_users_not_found_redirects(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/modules/99999/users")
        assert resp.status_code == 302

    @pytest.mark.smoke
    def test_user_modules_get_renders(self, app, db_session, admin_client, admin_user):
        resp = admin_client.get(f"/admin/modules/users/{admin_user.id}")
        assert resp.status_code == 200

    def test_user_modules_not_found_redirects(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/modules/users/99999")
        assert resp.status_code == 302

    @pytest.mark.smoke
    def test_get_module_users_data_returns_json(
        self, app, db_session, admin_client, module_in_db
    ):
        resp = admin_client.get(f"/admin/modules/{module_in_db.id}/users-data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "users" in data
        assert data["module"]["id"] == module_in_db.id

    def test_get_module_users_data_not_found(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/modules/99999/users-data")
        assert resp.status_code == 404

    def test_modules_delete_existing_returns_json(
        self, app, db_session, admin_client, module_in_db
    ):
        resp = admin_client.post(f"/admin/modules/{module_in_db.id}/delete")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_grant_module_success_returns_json(
        self, app, db_session, admin_client, module_in_db, admin_user
    ):
        resp = admin_client.post(
            f"/admin/modules/users/{admin_user.id}/grant/{module_in_db.id}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_revoke_module_success_returns_json(
        self, app, db_session, admin_client, module_in_db, admin_user
    ):
        # Grant first, then revoke
        admin_client.post(f"/admin/modules/users/{admin_user.id}/grant/{module_in_db.id}")
        resp = admin_client.post(
            f"/admin/modules/users/{admin_user.id}/revoke/{module_in_db.id}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_modules_delete_service_error_returns_500(
        self, app, db_session, admin_client, module_in_db
    ):
        with patch("app.admin.modules.ModuleService.delete_module", side_effect=Exception("db error")):
            resp = admin_client.post(f"/admin/modules/{module_in_db.id}/delete")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["success"] is False

    def test_register_module_routes_guard_returns_early(self):
        from unittest.mock import MagicMock

        from app.admin.modules import register_module_admin_routes

        # MagicMock auto-creates attributes so hasattr returns True → early return
        bp = MagicMock()
        register_module_admin_routes(bp)
        # route() should NOT have been called since we returned early
        bp.route.assert_not_called()


# ---------------------------------------------------------------------------
# quiz_decks.py — extended route coverage
# ---------------------------------------------------------------------------


class TestQuizDecksExtended:
    """Extended route tests for quiz_decks.py to improve coverage."""

    @pytest.fixture
    def deck_in_db(self, db_session, admin_user):
        from app.study.models import QuizDeck

        deck = QuizDeck(
            title="Coverage Test Deck",
            description="For coverage tests",
            user_id=admin_user.id,
            is_public=False,
        )
        db_session.add(deck)
        db_session.commit()
        return deck

    @pytest.mark.smoke
    def test_quiz_deck_view_renders(self, app, db_session, admin_client, deck_in_db):
        resp = admin_client.get(f"/admin/quiz-decks/{deck_in_db.id}")
        assert resp.status_code == 200

    @pytest.mark.smoke
    def test_quiz_deck_edit_get_renders(self, app, db_session, admin_client, deck_in_db):
        resp = admin_client.get(f"/admin/quiz-decks/{deck_in_db.id}/edit")
        assert resp.status_code == 200

    def test_quiz_deck_delete_returns_json(self, app, db_session, admin_client, deck_in_db):
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/delete",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_quiz_deck_search_filter(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/quiz-decks?search=coverage")
        assert resp.status_code == 200

    def test_quiz_deck_create_post_no_title_redirects(self, app, db_session, admin_client):
        resp = admin_client.post("/admin/quiz-decks/create", data={"title": ""})
        assert resp.status_code == 302

    @pytest.mark.smoke
    def test_quiz_deck_add_custom_word_returns_json(
        self, app, db_session, admin_client, deck_in_db
    ):
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "hello", "custom_russian": "привет"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_quiz_deck_add_word_missing_fields_redirects(
        self, app, db_session, admin_client, deck_in_db
    ):
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={},
        )
        assert resp.status_code == 302

    def test_quiz_deck_edit_post_returns_json(
        self, app, db_session, admin_client, deck_in_db
    ):
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/edit",
            data={"title": "Updated Title", "description": "Updated desc"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_quiz_deck_edit_post_redirect(self, app, db_session, admin_client, deck_in_db):
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/edit",
            data={"title": "Redirect Title", "description": ""},
        )
        # Without Accept: application/json, it redirects to view
        assert resp.status_code == 302

    def test_quiz_deck_remove_word_returns_json(
        self, app, db_session, admin_client, deck_in_db
    ):
        # First add a word to the deck
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "world", "custom_russian": "мир"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/delete",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_quiz_deck_reorder_words_returns_json(
        self, app, db_session, admin_client, deck_in_db
    ):
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/reorder",
            json={"word_ids": []},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_api_words_search_returns_results(self, app, db_session, admin_client):
        resp = admin_client.get("/admin/api/words/search?q=run")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_api_words_search_short_query_returns_empty(
        self, app, db_session, admin_client
    ):
        resp = admin_client.get("/admin/api/words/search?q=a")
        assert resp.status_code == 200
        assert resp.get_json() == []

    @pytest.mark.smoke
    def test_quiz_deck_create_post_creates_deck(self, app, db_session, admin_client):
        resp = admin_client.post(
            "/admin/quiz-decks/create",
            data={"title": "My New Deck", "description": "desc"},
        )
        # Redirects to edit page on success
        assert resp.status_code == 302

    def test_quiz_deck_delete_non_json_redirects(
        self, app, db_session, admin_client, deck_in_db
    ):
        resp = admin_client.post(f"/admin/quiz-decks/{deck_in_db.id}/delete")
        assert resp.status_code == 302

    def test_quiz_deck_update_word_returns_json(
        self, app, db_session, admin_client, deck_in_db
    ):
        # Add a custom word first
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "cat", "custom_russian": "кот"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/update",
            data={"custom_english": "kitten", "custom_russian": "котёнок"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_quiz_deck_update_word_missing_fields_returns_400(
        self, app, db_session, admin_client, deck_in_db
    ):
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "dog", "custom_russian": "собака"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/update",
            data={"custom_english": "", "custom_russian": ""},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 400

    def test_quiz_deck_reorder_with_items(
        self, app, db_session, admin_client, deck_in_db
    ):
        # Add two words first
        r1 = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "first", "custom_russian": "первый"},
            headers={"Accept": "application/json"},
        )
        r2 = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "second", "custom_russian": "второй"},
            headers={"Accept": "application/json"},
        )
        w1 = r1.get_json()["word"]["id"]
        w2 = r2.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/reorder",
            json={"word_ids": [w2, w1]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_quiz_deck_update_word_missing_non_json_redirects(
        self, app, db_session, admin_client, deck_in_db
    ):
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "fox", "custom_russian": "лиса"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/update",
            data={"custom_english": "", "custom_russian": ""},
        )
        assert resp.status_code == 302

    def test_quiz_deck_update_word_success_non_json_redirects(
        self, app, db_session, admin_client, deck_in_db
    ):
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "bear", "custom_russian": "медведь"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/update",
            data={"custom_english": "grizzly", "custom_russian": "гризли"},
        )
        assert resp.status_code == 302

    def test_quiz_deck_remove_word_non_json_redirects(
        self, app, db_session, admin_client, deck_in_db
    ):
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "wolf", "custom_russian": "волк"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/delete",
        )
        assert resp.status_code == 302

    def test_quiz_deck_create_public_generates_share_code(
        self, app, db_session, admin_client
    ):
        resp = admin_client.post(
            "/admin/quiz-decks/create",
            data={"title": "Public Deck", "description": "", "is_public": "on"},
        )
        assert resp.status_code == 302

    def test_quiz_deck_reset_word_custom_only_redirects(
        self, app, db_session, admin_client, deck_in_db
    ):
        # Add a fully-custom word (no word_id link)
        add_resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/add",
            data={"custom_english": "lion", "custom_russian": "лев"},
            headers={"Accept": "application/json"},
        )
        word_id = add_resp.get_json()["word"]["id"]

        # Reset should refuse (no collection link) and redirect
        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{word_id}/reset",
        )
        assert resp.status_code == 302

    def test_quiz_deck_reset_word_collection_link(
        self, app, db_session, admin_client, deck_in_db
    ):
        from app.words.models import CollectionWords
        from app.study.models import QuizDeckWord

        cw = CollectionWords(
            english_word=f"tiger_{uuid.uuid4().hex[:4]}",
            russian_word="тигр",
            level="A1",
        )
        db_session.add(cw)
        db_session.commit()

        deck_word = QuizDeckWord(
            deck_id=deck_in_db.id,
            word_id=cw.id,
            custom_english="tiger custom",
            custom_russian="тигр custom",
            order_index=1,
        )
        db_session.add(deck_word)
        db_session.commit()

        resp = admin_client.post(
            f"/admin/quiz-decks/{deck_in_db.id}/words/{deck_word.id}/reset",
        )
        assert resp.status_code == 302
