"""Tests for scripts/migrate_translation_lessons.py.

Covers:
  - patch_content() wraps legacy single russian/english pair into items[]
  - patch_content() sets mode per CEFR level
  - patch_content() skips lessons already in new schema
  - patch_content() preserves existing hint_words, alternatives, notes
  - patch_content() is idempotent (second call is no-op)
  - grading round-trip: migrated lesson content grades correctly
"""
from __future__ import annotations

import copy

import pytest

from scripts.migrate_translation_lessons import (
    DEFAULT_MODE,
    LEVEL_MODE,
    patch_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legacy(russian="Я иду домой", english="I go home", **kwargs) -> dict:
    """Build legacy single-item translation content."""
    c = {"russian": russian, "english": english}
    c.update(kwargs)
    return c


def _new_schema(items=None, mode="guided") -> dict:
    """Build already-migrated multi-item translation content."""
    return {
        "items": items
        or [{"russian": "Я иду домой", "english": "I go home", "hint_words": [], "alternatives": []}],
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# Legacy wrapping
# ---------------------------------------------------------------------------


class TestLegacyWrapping:
    def test_wraps_russian_english_into_items(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="A1")
        assert isinstance(patched["items"], list)
        assert len(patched["items"]) == 1
        item = patched["items"][0]
        assert item["russian"] == "Я иду домой"
        assert item["english"] == "I go home"
        assert "wrapped_legacy_to_items" in changes

    def test_sets_mode_for_a1(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="A1")
        assert patched["mode"] == "guided"
        assert "set_mode=guided" in changes

    def test_sets_mode_for_a0(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="A0")
        assert patched["mode"] == "guided"

    def test_sets_mode_for_a2(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="A2")
        assert patched["mode"] == "open"

    def test_sets_mode_for_b1(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="B1")
        assert patched["mode"] == "open"

    def test_sets_mode_for_b2(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="B2")
        assert patched["mode"] == "rubric"

    def test_sets_mode_for_c1(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="C1")
        assert patched["mode"] == "rubric"

    def test_sets_mode_for_c2(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="C2")
        assert patched["mode"] == "rubric"

    def test_unknown_level_falls_back_to_default_mode(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="XX")
        assert patched["mode"] == DEFAULT_MODE

    def test_empty_level_code_falls_back_to_default(self):
        content = _legacy()
        patched, changes = patch_content(content, level_code="")
        assert patched["mode"] == DEFAULT_MODE


# ---------------------------------------------------------------------------
# Field preservation
# ---------------------------------------------------------------------------


class TestFieldPreservation:
    def test_hint_words_moved_into_item(self):
        content = _legacy(hint_words=["I", "go", "home"])
        patched, _ = patch_content(content, level_code="A1")
        item = patched["items"][0]
        assert item["hint_words"] == ["I", "go", "home"]

    def test_alternatives_moved_into_item(self):
        content = _legacy(alternatives=["I'm going home", "I am going home"])
        patched, _ = patch_content(content, level_code="A1")
        item = patched["items"][0]
        assert item["alternatives"] == ["I'm going home", "I am going home"]

    def test_notes_preserved_in_item(self):
        content = _legacy(notes="Formal register")
        patched, _ = patch_content(content, level_code="A1")
        item = patched["items"][0]
        assert item.get("notes") == "Formal register"

    def test_empty_hint_words_list_preserved(self):
        content = _legacy(hint_words=[])
        patched, _ = patch_content(content, level_code="A1")
        item = patched["items"][0]
        assert item["hint_words"] == []

    def test_item_defaults_hint_words_to_empty_list(self):
        content = _legacy()  # no hint_words key
        patched, _ = patch_content(content, level_code="A1")
        item = patched["items"][0]
        assert item["hint_words"] == []

    def test_item_defaults_alternatives_to_empty_list(self):
        content = _legacy()
        patched, _ = patch_content(content, level_code="A1")
        item = patched["items"][0]
        assert item["alternatives"] == []


# ---------------------------------------------------------------------------
# Already-in-new-schema: skip
# ---------------------------------------------------------------------------


class TestAlreadyInNewSchema:
    def test_no_changes_when_items_and_mode_present(self):
        content = _new_schema()
        patched, changes = patch_content(content, level_code="A1")
        assert changes == []

    def test_items_and_mode_already_present_is_noop(self):
        content = _new_schema(mode="rubric")
        _, changes = patch_content(content, level_code="A1")
        assert changes == []

    def test_mode_not_overwritten_when_already_valid(self):
        content = _new_schema(mode="rubric")
        patched, _ = patch_content(content, level_code="A1")
        # Despite A1 normally mapping to "guided", explicit mode wins
        assert patched["mode"] == "rubric"

    def test_items_only_without_mode_gets_mode_added(self):
        content = {
            "items": [{"russian": "Привет", "english": "Hello", "hint_words": [], "alternatives": []}]
        }
        patched, changes = patch_content(content, level_code="A1")
        assert patched["mode"] == "guided"
        assert "set_mode=guided" in changes

    def test_mode_only_without_items_and_no_legacy_is_noop(self):
        # mode present but no items and no russian/english — incomplete content
        content = {"mode": "guided"}
        _, changes = patch_content(content, level_code="A1")
        # No russian/english to wrap, so nothing to do
        assert changes == []


# ---------------------------------------------------------------------------
# Incomplete content edge cases
# ---------------------------------------------------------------------------


class TestIncompleteContent:
    def test_empty_content_is_noop(self):
        _, changes = patch_content({}, level_code="A1")
        assert changes == []

    def test_missing_english_is_noop(self):
        content = {"russian": "Я иду домой"}
        _, changes = patch_content(content, level_code="A1")
        assert changes == []

    def test_missing_russian_is_noop(self):
        content = {"english": "I go home"}
        _, changes = patch_content(content, level_code="A1")
        assert changes == []

    def test_blank_russian_is_noop(self):
        content = {"russian": "   ", "english": "hello"}
        _, changes = patch_content(content, level_code="A1")
        assert changes == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_patch_on_legacy_is_noop(self):
        content = _legacy(hint_words=["I", "go"])
        patched_once, changes_1 = patch_content(content, level_code="A1")
        assert changes_1  # first run produces changes
        patched_twice, changes_2 = patch_content(patched_once, level_code="A1")
        assert changes_2 == []

    def test_original_not_mutated(self):
        content = _legacy(hint_words=["I", "go"])
        original = copy.deepcopy(content)
        patch_content(content, level_code="A1")
        assert content == original  # patch_content uses deepcopy internally

    def test_already_new_schema_second_run_is_noop(self):
        content = _new_schema()
        _, changes_1 = patch_content(content, level_code="B1")
        assert changes_1 == []
        _, changes_2 = patch_content(content, level_code="B1")
        assert changes_2 == []


# ---------------------------------------------------------------------------
# Grading round-trip
# ---------------------------------------------------------------------------


class TestGradingRoundTrip:
    """Ensure migrated items still grade correctly via the route helper."""

    def test_items_from_migrated_content_grade_correct_answer(self):
        from app.curriculum.grading import grade_translation_multi
        from app.curriculum.routes.lessons import _translation_items_from_content

        content = _legacy(english="I go home")
        patched, _ = patch_content(content, level_code="A1")

        items = _translation_items_from_content(patched)
        assert len(items) == 1

        result = grade_translation_multi(["I go home"], items)
        assert result["passed"] is True
        assert result["correct_items"] == 1

    def test_items_from_migrated_content_grade_wrong_answer(self):
        from app.curriculum.grading import grade_translation_multi
        from app.curriculum.routes.lessons import _translation_items_from_content

        content = _legacy(english="I go home")
        patched, _ = patch_content(content, level_code="A1")

        items = _translation_items_from_content(patched)
        result = grade_translation_multi(["She runs fast"], items)
        assert result["passed"] is False
        assert result["correct_items"] == 0

    def test_items_from_migrated_content_grade_with_alternatives(self):
        from app.curriculum.grading import grade_translation_multi
        from app.curriculum.routes.lessons import _translation_items_from_content

        content = _legacy(
            english="I go home",
            alternatives=["I am going home", "I'm going home"],
        )
        patched, _ = patch_content(content, level_code="A1")

        items = _translation_items_from_content(patched)
        result = grade_translation_multi(["I am going home"], items)
        assert result["passed"] is True

    def test_mode_auto_derived_from_items_when_no_explicit_mode(self):
        from app.curriculum.routes.lessons import (
            _translation_items_from_content,
            _translation_mode,
        )

        content = _legacy(hint_words=["I", "go"])
        patched, _ = patch_content(content, level_code="A1")

        items = _translation_items_from_content(patched)
        # explicit mode="guided" was set by migration, so it wins
        mode = _translation_mode(patched, items)
        assert mode == "guided"
