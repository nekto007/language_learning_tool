"""Tests for scripts/migrate_writing_prompt_lessons.py.

Covers:
  - patch_content() sets mode per CEFR level
  - patch_content() sets prompt_ru default when absent
  - patch_content() sets min_sentences per level when absent
  - patch_content() sets min_checklist based on mode
  - patch_content() defaults hint_words and target_phrases to []
  - patch_content() skips lessons already in new schema (has mode + prompt_ru)
  - patch_content() is idempotent (second call is a no-op)
  - readiness gate: migrated lesson still passes submission validation
"""
from __future__ import annotations

import copy

import pytest

from scripts.migrate_writing_prompt_lessons import (
    DEFAULT_MIN_CHECKLIST,
    DEFAULT_MIN_SENTENCES,
    DEFAULT_MODE,
    DEFAULT_PROMPT_RU,
    LEVEL_MIN_SENTENCES,
    LEVEL_MODE,
    VALID_MODES,
    patch_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legacy(
    prompt: str = "Write about your daily routine.",
    min_words: int = 40,
    **kwargs,
) -> dict:
    """Build legacy writing_prompt content (no mode or prompt_ru)."""
    c = {"prompt": prompt, "min_words": min_words}
    c.update(kwargs)
    return c


def _new_schema(
    prompt: str = "Write about your daily routine.",
    mode: str = "guided",
    prompt_ru: str = "Напишите о вашей повседневной жизни:",
    min_sentences: int = 3,
    **kwargs,
) -> dict:
    """Build already-migrated writing_prompt content."""
    c = {
        "prompt": prompt,
        "mode": mode,
        "prompt_ru": prompt_ru,
        "min_sentences": min_sentences,
    }
    c.update(kwargs)
    return c


# ---------------------------------------------------------------------------
# Mode assignment by level
# ---------------------------------------------------------------------------


class TestModeByLevel:
    def test_a0_gets_guided(self):
        patched, changes = patch_content(_legacy(), level_code="A0")
        assert patched["mode"] == "guided"
        assert any("set_mode=guided" in c for c in changes)

    def test_a1_gets_guided(self):
        patched, changes = patch_content(_legacy(), level_code="A1")
        assert patched["mode"] == "guided"

    def test_a2_gets_structured(self):
        patched, changes = patch_content(_legacy(), level_code="A2")
        assert patched["mode"] == "structured"
        assert any("set_mode=structured" in c for c in changes)

    def test_b1_gets_paragraph(self):
        patched, changes = patch_content(_legacy(), level_code="B1")
        assert patched["mode"] == "paragraph"

    def test_b2_gets_opinion(self):
        patched, changes = patch_content(_legacy(), level_code="B2")
        assert patched["mode"] == "opinion"

    def test_c1_gets_style(self):
        patched, changes = patch_content(_legacy(), level_code="C1")
        assert patched["mode"] == "style"

    def test_c2_gets_rhetoric(self):
        patched, changes = patch_content(_legacy(), level_code="C2")
        assert patched["mode"] == "rhetoric"

    def test_unknown_level_falls_back_to_default_mode(self):
        patched, _ = patch_content(_legacy(), level_code="XX")
        assert patched["mode"] == DEFAULT_MODE

    def test_empty_level_falls_back_to_default(self):
        patched, _ = patch_content(_legacy(), level_code="")
        assert patched["mode"] == DEFAULT_MODE

    def test_level_mode_dict_covers_all_valid_modes(self):
        # All values in LEVEL_MODE map to valid modes
        for mode_value in LEVEL_MODE.values():
            assert mode_value in VALID_MODES


# ---------------------------------------------------------------------------
# prompt_ru assignment
# ---------------------------------------------------------------------------


class TestPromptRuAssignment:
    def test_sets_default_prompt_ru_when_absent(self):
        patched, changes = patch_content(_legacy(), level_code="A1")
        assert patched["prompt_ru"] == DEFAULT_PROMPT_RU
        assert any("set_prompt_ru" in c for c in changes)

    def test_does_not_overwrite_existing_prompt_ru(self):
        c = _legacy(prompt_ru="Расскажите о себе:")
        patched, changes = patch_content(c, level_code="A1")
        # Still has mode changes but prompt_ru is preserved
        assert patched["prompt_ru"] == "Расскажите о себе:"
        assert not any("set_prompt_ru" in ch for ch in changes)

    def test_whitespace_only_prompt_ru_is_replaced(self):
        c = _legacy(prompt_ru="   ")
        patched, changes = patch_content(c, level_code="A1")
        assert patched["prompt_ru"] == DEFAULT_PROMPT_RU
        assert any("set_prompt_ru" in ch for ch in changes)

    def test_empty_string_prompt_ru_is_replaced(self):
        c = _legacy(prompt_ru="")
        patched, changes = patch_content(c, level_code="A1")
        assert patched["prompt_ru"] == DEFAULT_PROMPT_RU


# ---------------------------------------------------------------------------
# min_sentences assignment
# ---------------------------------------------------------------------------


class TestMinSentences:
    @pytest.mark.parametrize("level,expected", [
        ("A0", 3), ("A1", 3), ("A2", 4), ("B1", 5), ("B2", 6), ("C1", 7), ("C2", 8),
    ])
    def test_min_sentences_by_level(self, level, expected):
        patched, changes = patch_content(_legacy(), level_code=level)
        assert patched["min_sentences"] == expected
        assert any(f"set_min_sentences={expected}" in c for c in changes)

    def test_unknown_level_falls_back_to_default(self):
        patched, _ = patch_content(_legacy(), level_code="ZZ")
        assert patched["min_sentences"] == DEFAULT_MIN_SENTENCES

    def test_existing_min_sentences_not_overwritten(self):
        c = _legacy(min_sentences=10)
        patched, changes = patch_content(c, level_code="A1")
        assert patched["min_sentences"] == 10
        assert not any("set_min_sentences" in ch for ch in changes)

    def test_level_min_sentences_dict_complete(self):
        assert set(LEVEL_MIN_SENTENCES.keys()) == {"A0", "A1", "A2", "B1", "B2", "C1", "C2"}


# ---------------------------------------------------------------------------
# min_checklist assignment
# ---------------------------------------------------------------------------


class TestMinChecklist:
    def test_guided_gets_min_checklist_3(self):
        patched, changes = patch_content(_legacy(), level_code="A1")
        assert patched["mode"] == "guided"
        assert patched["min_checklist"] == 3
        assert any("set_min_checklist=3" in c for c in changes)

    def test_structured_gets_min_checklist_2(self):
        patched, _ = patch_content(_legacy(), level_code="A2")
        assert patched["mode"] == "structured"
        assert patched["min_checklist"] == DEFAULT_MIN_CHECKLIST

    def test_paragraph_gets_min_checklist_2(self):
        patched, _ = patch_content(_legacy(), level_code="B1")
        assert patched["min_checklist"] == DEFAULT_MIN_CHECKLIST

    def test_existing_min_checklist_not_overwritten(self):
        c = _legacy(min_checklist=5)
        patched, changes = patch_content(c, level_code="A1")
        assert patched["min_checklist"] == 5
        assert not any("set_min_checklist" in ch for ch in changes)


# ---------------------------------------------------------------------------
# hint_words and target_phrases defaults
# ---------------------------------------------------------------------------


class TestListDefaults:
    def test_hint_words_defaults_to_empty_list(self):
        c = _legacy()
        assert "hint_words" not in c
        patched, changes = patch_content(c, level_code="A1")
        assert patched["hint_words"] == []
        assert any("set_hint_words" in ch for ch in changes)

    def test_target_phrases_defaults_to_empty_list(self):
        c = _legacy()
        assert "target_phrases" not in c
        patched, changes = patch_content(c, level_code="A1")
        assert patched["target_phrases"] == []
        assert any("set_target_phrases" in ch for ch in changes)

    def test_existing_hint_words_not_overwritten(self):
        c = _legacy(hint_words=["Hello", "My", "Name"])
        patched, changes = patch_content(c, level_code="A1")
        assert patched["hint_words"] == ["Hello", "My", "Name"]
        assert not any("set_hint_words" in ch for ch in changes)

    def test_existing_target_phrases_not_overwritten(self):
        c = _legacy(target_phrases=["every day", "usually"])
        patched, changes = patch_content(c, level_code="A1")
        assert patched["target_phrases"] == ["every day", "usually"]

    def test_existing_empty_hint_words_list_not_overwritten(self):
        c = _legacy(hint_words=[])
        patched, changes = patch_content(c, level_code="A1")
        assert patched["hint_words"] == []
        # Key exists, so no change emitted
        assert not any("set_hint_words" in ch for ch in changes)


# ---------------------------------------------------------------------------
# Already-in-new-schema: skip
# ---------------------------------------------------------------------------


class TestAlreadyInNewSchema:
    def test_no_changes_when_mode_and_prompt_ru_present(self):
        content = _new_schema()
        _, changes = patch_content(content, level_code="A1")
        assert changes == []

    def test_mode_not_overwritten_when_already_valid(self):
        content = _new_schema(mode="rhetoric", prompt_ru="Напишите эссе:")
        patched, changes = patch_content(content, level_code="A1")
        assert patched["mode"] == "rhetoric"
        assert changes == []

    def test_mode_only_without_prompt_ru_still_triggers_patch(self):
        # Has mode but no prompt_ru — should add prompt_ru (and min_sentences etc.)
        c = {"prompt": "Write something.", "mode": "guided", "min_words": 30}
        patched, changes = patch_content(c, level_code="A1")
        assert patched["prompt_ru"] == DEFAULT_PROMPT_RU
        assert "set_prompt_ru=default" in changes
        # mode was already set, so no mode change
        assert not any("set_mode" in ch for ch in changes)

    def test_prompt_ru_only_without_mode_still_triggers_patch(self):
        c = {"prompt": "Write something.", "prompt_ru": "Напишите что-нибудь:", "min_words": 30}
        patched, changes = patch_content(c, level_code="B1")
        assert patched["mode"] == "paragraph"
        assert "set_mode=paragraph" in changes
        # prompt_ru was already set, so no prompt_ru change
        assert not any("set_prompt_ru" in ch for ch in changes)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_patch_on_legacy_is_noop(self):
        content = _legacy()
        patched_once, changes_1 = patch_content(content, level_code="A1")
        assert changes_1  # first run produces changes
        patched_twice, changes_2 = patch_content(patched_once, level_code="A1")
        assert changes_2 == []

    def test_original_not_mutated(self):
        content = _legacy()
        original = copy.deepcopy(content)
        patch_content(content, level_code="A1")
        assert content == original  # patch_content uses deepcopy internally

    def test_already_new_schema_second_run_is_noop(self):
        content = _new_schema(mode="structured", prompt_ru="Напишите текст:")
        _, changes_1 = patch_content(content, level_code="A2")
        assert changes_1 == []
        _, changes_2 = patch_content(content, level_code="A2")
        assert changes_2 == []

    def test_all_levels_idempotent(self):
        for level in ("A0", "A1", "A2", "B1", "B2", "C1", "C2"):
            content = _legacy()
            patched, _ = patch_content(content, level_code=level)
            _, changes_2 = patch_content(patched, level_code=level)
            assert changes_2 == [], f"Second pass for {level} produced changes: {changes_2}"


# ---------------------------------------------------------------------------
# Readiness gate (submission validation path)
# ---------------------------------------------------------------------------


class TestReadinessGate:
    """Ensure migrated content still passes the route-level readiness check."""

    def test_migrated_a1_lesson_has_min_sentences(self):
        content = _legacy()
        patched, _ = patch_content(content, level_code="A1")
        # min_sentences should be truthy
        assert patched.get("min_sentences") or patched.get("min_words")

    def test_migrated_content_passes_validator(self):
        from app.curriculum.validators import WritingPromptContentSchema
        content = _legacy()
        patched, _ = patch_content(content, level_code="A1")
        schema = WritingPromptContentSchema()
        errors = schema.validate(patched)
        assert not errors, f"Validator errors: {errors}"

    def test_migrated_b1_content_passes_validator(self):
        from app.curriculum.validators import WritingPromptContentSchema
        content = _legacy(min_words=80)
        patched, _ = patch_content(content, level_code="B1")
        schema = WritingPromptContentSchema()
        errors = schema.validate(patched)
        assert not errors, f"Validator errors: {errors}"

    def test_all_levels_pass_validator(self):
        from app.curriculum.validators import WritingPromptContentSchema
        schema = WritingPromptContentSchema()
        for level in ("A0", "A1", "A2", "B1", "B2", "C1", "C2"):
            content = _legacy()
            patched, _ = patch_content(content, level_code=level)
            errors = schema.validate(patched)
            assert not errors, f"Level {level} validator errors: {errors}"

    def test_migrated_mode_is_one_of_valid_modes(self):
        for level in ("A0", "A1", "A2", "B1", "B2", "C1", "C2"):
            content = _legacy()
            patched, _ = patch_content(content, level_code=level)
            assert patched["mode"] in VALID_MODES

    def test_migrated_min_checklist_is_positive_int(self):
        for level in ("A0", "A1", "A2", "B1"):
            content = _legacy()
            patched, _ = patch_content(content, level_code=level)
            assert isinstance(patched["min_checklist"], int)
            assert patched["min_checklist"] >= 1
