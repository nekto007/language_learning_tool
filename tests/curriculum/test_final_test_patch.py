"""Tests for scripts/patch_final_test_prompts.py.

Covers:
  - patch_content() round-trips: output is idempotent (second patch is no-op)
  - transformation prompt replacement
  - matching pair normalisation (left/right -> english/russian)
  - passing_score_percent defaulting
  - passing_score sync
  - already-patched content produces no changes
"""
from __future__ import annotations

import copy

import pytest

from scripts.patch_final_test_prompts import (
    DEFAULT_PASSING_SCORE,
    patch_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_content(
    *,
    sections=None,
    exercises=None,
    passing_score=None,
    passing_score_percent=None,
) -> dict:
    c: dict = {}
    if sections is not None:
        c["test_sections"] = sections
    if exercises is not None:
        c["exercises"] = exercises
    if passing_score is not None:
        c["passing_score"] = passing_score
    if passing_score_percent is not None:
        c["passing_score_percent"] = passing_score_percent
    return c


def _transform_q(prompt: str) -> dict:
    return {"type": "transformation", "question": prompt, "answer": "Is he going?"}


def _matching_q(pairs: list[dict]) -> dict:
    return {"type": "matching", "pairs": pairs}


# ---------------------------------------------------------------------------
# Transformation prompt patching
# ---------------------------------------------------------------------------


class TestTransformPromptPatch:
    def test_replaces_russian_stub(self):
        content = _make_content(exercises=[_transform_q("Сделайте вопрос")])
        patched, changes = patch_content(content)
        q = patched["exercises"][0]
        assert "Преобразуйте" in q["question"]
        assert "fixed_transform_prompt" in changes

    def test_replaces_english_stub(self):
        content = _make_content(exercises=[_transform_q("Make a question")])
        patched, changes = patch_content(content)
        assert "Преобразуйте" in patched["exercises"][0]["question"]

    def test_stub_inside_section(self):
        section = {
            "section": "Part 1",
            "exercises": [_transform_q("Сделайте вопрос.")],
        }
        content = _make_content(sections=[section])
        patched, changes = patch_content(content)
        ex = patched["test_sections"][0]["exercises"][0]
        assert "Преобразуйте" in ex["question"]

    def test_non_stub_text_unchanged(self):
        original_prompt = "Преобразуйте утверждение в вопрос:"
        content = _make_content(exercises=[_transform_q(original_prompt)])
        patched, changes = patch_content(content)
        assert patched["exercises"][0]["question"] == original_prompt
        assert "fixed_transform_prompt" not in changes

    def test_non_transformation_type_unchanged(self):
        content = _make_content(
            exercises=[{"type": "multiple_choice", "question": "Сделайте вопрос", "options": ["a"]}]
        )
        patched, changes = patch_content(content)
        # type is not transformation, so question is not touched
        assert patched["exercises"][0]["question"] == "Сделайте вопрос"
        assert "fixed_transform_prompt" not in changes


# ---------------------------------------------------------------------------
# Matching pair normalisation
# ---------------------------------------------------------------------------


class TestMatchingPairNormalisation:
    def test_left_right_converted(self):
        pairs = [{"left": "hello", "right": "привет"}]
        content = _make_content(exercises=[_matching_q(pairs)])
        patched, changes = patch_content(content)
        p = patched["exercises"][0]["pairs"][0]
        assert p == {"english": "hello", "russian": "привет"}
        assert "normalised_matching_pairs" in changes

    def test_english_russian_unchanged(self):
        pairs = [{"english": "hello", "russian": "привет"}]
        content = _make_content(exercises=[_matching_q(pairs)])
        patched, changes = patch_content(content)
        assert "normalised_matching_pairs" not in changes

    def test_extra_keys_preserved_on_normalisation(self):
        pairs = [{"left": "cat", "right": "кот", "hint": "animal"}]
        content = _make_content(exercises=[_matching_q(pairs)])
        patched, changes = patch_content(content)
        p = patched["exercises"][0]["pairs"][0]
        assert p["hint"] == "animal"
        assert p["english"] == "cat"

    def test_non_matching_type_pairs_untouched(self):
        q = {"type": "multiple_choice", "pairs": [{"left": "x", "right": "y"}]}
        content = _make_content(exercises=[q])
        patched, changes = patch_content(content)
        # pairs on a non-matching type are not touched
        assert patched["exercises"][0]["pairs"][0]["left"] == "x"
        assert "normalised_matching_pairs" not in changes


# ---------------------------------------------------------------------------
# passing_score_percent / passing_score sync
# ---------------------------------------------------------------------------


class TestPassingScoreSync:
    def test_default_added_when_missing(self):
        content = _make_content()
        patched, changes = patch_content(content)
        assert patched["passing_score_percent"] == DEFAULT_PASSING_SCORE
        assert f"set_passing_score_percent={DEFAULT_PASSING_SCORE}" in changes

    def test_derived_from_existing_passing_score(self):
        content = _make_content(passing_score=65)
        patched, changes = patch_content(content)
        assert patched["passing_score_percent"] == 65

    def test_passing_score_synced_to_percent(self):
        content = _make_content(passing_score_percent=80, passing_score=70)
        patched, changes = patch_content(content)
        assert patched["passing_score"] == 80
        assert "sync_passing_score=80" in changes

    def test_already_in_sync_is_noop(self):
        content = _make_content(passing_score_percent=75, passing_score=75)
        patched, changes = patch_content(content)
        assert "sync_passing_score" not in " ".join(changes)

    def test_pass_score_alias_synced(self):
        content: dict = {"pass_score": 60, "passing_score_percent": 80}
        patched, changes = patch_content(content)
        assert patched["pass_score"] == 80
        assert "sync_pass_score=80" in changes


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def _full_content(self):
        return {
            "test_sections": [
                {
                    "section": "Grammar",
                    "exercises": [
                        _transform_q("Сделайте вопрос"),
                        _matching_q([{"left": "cat", "right": "кот"}]),
                    ],
                }
            ],
            "passing_score": 60,
        }

    def test_second_patch_is_noop(self):
        content = self._full_content()
        patched_once, changes_1 = patch_content(content)
        assert changes_1  # first run produces changes
        patched_twice, changes_2 = patch_content(patched_once)
        assert changes_2 == []  # second run is a no-op

    def test_original_not_mutated(self):
        content = self._full_content()
        original = copy.deepcopy(content)
        patch_content(content)
        assert content == original  # patch_content uses deepcopy internally

    def test_empty_content_idempotent(self):
        content: dict = {}
        patched_once, _ = patch_content(content)
        patched_twice, changes_2 = patch_content(patched_once)
        assert changes_2 == []
