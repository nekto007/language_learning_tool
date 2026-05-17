"""Tests for scripts/audit_remaining_lesson_types.py.

Covers pure-logic audit functions for:
  pronunciation, sentence_correction, sentence_completion,
  collocation_matching, idiom
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_remaining_lesson_types import (
    LessonAudit,
    ItemGap,
    _check_pronunciation,
    _check_sentence_correction,
    _check_sentence_completion,
    _check_collocation_matching,
    _check_idiom,
    _patch_sentence_correction_mode,
    audit_content,
    format_markdown,
    main,
)


# ---------------------------------------------------------------------------
# pronunciation checks
# ---------------------------------------------------------------------------

class TestCheckPronunciation:
    def test_valid_items_pass(self):
        content = {"items": [{"word": "hello", "phonetic": "/həˈloʊ/"}]}
        gaps, item_gaps = _check_pronunciation(content)
        assert gaps == []
        assert item_gaps == []

    def test_valid_with_audio(self):
        content = {"items": [{"word": "hello", "phonetic": "/həˈloʊ/", "audio": "/x.mp3"}]}
        gaps, item_gaps = _check_pronunciation(content)
        assert gaps == []
        assert item_gaps == []

    def test_exercises_key_alias(self):
        content = {"exercises": [{"word": "cat", "phonetic": "/kæt/"}]}
        gaps, item_gaps = _check_pronunciation(content)
        assert gaps == []
        assert item_gaps == []

    def test_missing_phonetic_flagged(self):
        content = {"items": [{"word": "hello"}]}
        gaps, item_gaps = _check_pronunciation(content)
        assert item_gaps
        assert "phonetic" in item_gaps[0].missing_fields

    def test_missing_word_flagged(self):
        content = {"items": [{"phonetic": "/kæt/"}]}
        gaps, item_gaps = _check_pronunciation(content)
        assert item_gaps
        assert "word" in item_gaps[0].missing_fields

    def test_missing_both_flagged(self):
        content = {"items": [{}]}
        gaps, item_gaps = _check_pronunciation(content)
        assert item_gaps
        assert "word" in item_gaps[0].missing_fields
        assert "phonetic" in item_gaps[0].missing_fields

    def test_empty_items_array_gap(self):
        content = {"items": []}
        gaps, item_gaps = _check_pronunciation(content)
        assert gaps
        assert "no items" in gaps[0]

    def test_no_items_key_gap(self):
        content = {}
        gaps, item_gaps = _check_pronunciation(content)
        assert gaps

    def test_item_idx_reported(self):
        content = {"items": [
            {"word": "hi", "phonetic": "/haɪ/"},
            {"word": "bye"},
        ]}
        gaps, item_gaps = _check_pronunciation(content)
        assert len(item_gaps) == 1
        assert item_gaps[0].item_idx == 1


# ---------------------------------------------------------------------------
# sentence_correction checks
# ---------------------------------------------------------------------------

class TestCheckSentenceCorrection:
    def test_valid_with_mode_and_incorrect(self):
        content = {"mode": "guided", "incorrect_sentence": "She go.", "correct_sentence": "She goes."}
        gaps, item_gaps = _check_sentence_correction(content, "A1")
        assert gaps == []
        assert item_gaps == []

    def test_missing_mode_flagged(self):
        content = {"incorrect_sentence": "She go."}
        gaps, _ = _check_sentence_correction(content, "A1")
        assert any("mode" in g for g in gaps)

    def test_missing_incorrect_sentence_top_level(self):
        content = {"mode": "guided"}
        gaps, _ = _check_sentence_correction(content, "A1")
        assert any("incorrect_sentence" in g for g in gaps)

    def test_items_array_checked(self):
        content = {
            "mode": "open",
            "items": [
                {"incorrect_sentence": "He go.", "correct_sentence": "He goes."},
                {"correct_sentence": "She goes."},  # missing incorrect_sentence
            ],
        }
        gaps, item_gaps = _check_sentence_correction(content, "A2")
        assert gaps == []
        assert len(item_gaps) == 1
        assert "incorrect_sentence" in item_gaps[0].missing_fields

    def test_items_array_all_ok(self):
        content = {
            "mode": "open",
            "items": [{"incorrect_sentence": "He go.", "correct_sentence": "He goes."}],
        }
        gaps, item_gaps = _check_sentence_correction(content, "A2")
        assert gaps == []
        assert item_gaps == []


class TestPatchSentenceCorrectionMode:
    def test_adds_mode_for_a1(self):
        content = {"incorrect_sentence": "She go."}
        patched, changed = _patch_sentence_correction_mode(content, "A1")
        assert changed is True
        assert patched["mode"] == "guided"

    def test_adds_mode_for_b2(self):
        content = {"incorrect_sentence": "She go."}
        patched, changed = _patch_sentence_correction_mode(content, "B2")
        assert changed is True
        assert patched["mode"] == "rubric"

    def test_no_change_if_mode_present(self):
        content = {"mode": "open", "incorrect_sentence": "x"}
        patched, changed = _patch_sentence_correction_mode(content, "A1")
        assert changed is False
        assert patched["mode"] == "open"

    def test_idempotent_on_already_patched(self):
        content = {"mode": "guided", "incorrect_sentence": "x"}
        _, changed1 = _patch_sentence_correction_mode(content, "A1")
        _, changed2 = _patch_sentence_correction_mode(content, "A1")
        assert changed1 is False
        assert changed2 is False

    def test_original_not_mutated(self):
        content = {"incorrect_sentence": "x"}
        original_str = str(content)
        _patch_sentence_correction_mode(content, "A1")
        assert str(content) == original_str

    def test_unknown_level_defaults_to_open(self):
        content = {"incorrect_sentence": "x"}
        patched, changed = _patch_sentence_correction_mode(content, "UNKNOWN")
        assert changed is True
        assert patched["mode"] == "open"


# ---------------------------------------------------------------------------
# sentence_completion checks
# ---------------------------------------------------------------------------

class TestCheckSentenceCompletion:
    def test_valid_items_pass(self):
        content = {"items": [{"prompt": "She ___ to school.", "answer": "goes"}]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert gaps == []
        assert item_gaps == []

    def test_valid_with_alternatives(self):
        content = {"items": [{"prompt": "He ___.", "answer": "runs", "alternatives": ["jogs"]}]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert gaps == []
        assert item_gaps == []

    def test_exercises_key_alias(self):
        content = {"exercises": [{"prompt": "She ___.", "answer": "goes"}]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert gaps == []

    def test_missing_prompt_flagged(self):
        content = {"items": [{"answer": "goes"}]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert item_gaps
        assert "prompt" in item_gaps[0].missing_fields

    def test_missing_answer_flagged(self):
        content = {"items": [{"prompt": "She ___"}]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert item_gaps
        assert "answer" in item_gaps[0].missing_fields

    def test_missing_both(self):
        content = {"items": [{}]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert item_gaps
        assert "prompt" in item_gaps[0].missing_fields
        assert "answer" in item_gaps[0].missing_fields

    def test_no_items_array_gap(self):
        content = {}
        gaps, _ = _check_sentence_completion(content)
        assert gaps

    def test_item_idx_correct(self):
        content = {"items": [
            {"prompt": "A ___", "answer": "x"},
            {"prompt": "B ___"},
        ]}
        gaps, item_gaps = _check_sentence_completion(content)
        assert item_gaps[0].item_idx == 1


# ---------------------------------------------------------------------------
# collocation_matching checks
# ---------------------------------------------------------------------------

class TestCheckCollocationMatching:
    def test_valid_pairs_pass(self):
        content = {"pairs": [{"phrase": "make a decision", "translation": "принять решение"}]}
        gaps, item_gaps = _check_collocation_matching(content)
        assert gaps == []
        assert item_gaps == []

    def test_missing_phrase_flagged(self):
        content = {"pairs": [{"translation": "принять решение"}]}
        gaps, item_gaps = _check_collocation_matching(content)
        assert item_gaps
        assert "phrase" in item_gaps[0].missing_fields

    def test_missing_translation_flagged(self):
        content = {"pairs": [{"phrase": "make a decision"}]}
        gaps, item_gaps = _check_collocation_matching(content)
        assert item_gaps
        assert "translation" in item_gaps[0].missing_fields

    def test_no_pairs_gap(self):
        content = {}
        gaps, _ = _check_collocation_matching(content)
        assert gaps
        assert "no pairs" in gaps[0]

    def test_multiple_pairs_second_bad(self):
        content = {"pairs": [
            {"phrase": "make a decision", "translation": "принять решение"},
            {"phrase": "break the rules"},
        ]}
        gaps, item_gaps = _check_collocation_matching(content)
        assert len(item_gaps) == 1
        assert item_gaps[0].item_idx == 1

    def test_extra_fields_not_flagged(self):
        content = {"pairs": [{"phrase": "p", "translation": "t", "example": "e"}]}
        gaps, item_gaps = _check_collocation_matching(content)
        assert gaps == []
        assert item_gaps == []


# ---------------------------------------------------------------------------
# idiom checks
# ---------------------------------------------------------------------------

class TestCheckIdiom:
    def test_valid_idiom_passes(self):
        content = {
            "phrase": "kick the bucket",
            "meaning_ru": "умереть",
            "example": "He kicked the bucket last year.",
            "example_ru": "Он умер в прошлом году.",
        }
        gaps, item_gaps = _check_idiom(content)
        assert gaps == []
        assert item_gaps == []

    def test_missing_phrase_flagged(self):
        content = {"meaning_ru": "x", "example": "x", "example_ru": "x"}
        gaps, _ = _check_idiom(content)
        assert any("phrase" in g for g in gaps)

    def test_missing_meaning_ru_flagged(self):
        content = {"phrase": "x", "example": "x", "example_ru": "x"}
        gaps, _ = _check_idiom(content)
        assert any("meaning_ru" in g for g in gaps)

    def test_missing_example_flagged(self):
        content = {"phrase": "x", "meaning_ru": "x", "example_ru": "x"}
        gaps, _ = _check_idiom(content)
        assert any("example" in g for g in gaps)

    def test_missing_example_ru_flagged(self):
        content = {"phrase": "x", "meaning_ru": "x", "example": "x"}
        gaps, _ = _check_idiom(content)
        assert any("example_ru" in g for g in gaps)

    def test_all_missing_reports_all(self):
        gaps, _ = _check_idiom({})
        assert len(gaps) == 4

    def test_extra_fields_allowed(self):
        content = {
            "phrase": "p", "meaning_ru": "m", "example": "e", "example_ru": "er",
            "notes": "additional note",
        }
        gaps, _ = _check_idiom(content)
        assert gaps == []


# ---------------------------------------------------------------------------
# audit_content dispatch
# ---------------------------------------------------------------------------

class TestAuditContent:
    def _make(self, lt, content, level_code="A1"):
        return audit_content(1, "L1", "M1", level_code, lt, content)

    def test_pronunciation_ok(self):
        a = self._make("pronunciation", {"items": [{"word": "hi", "phonetic": "/haɪ/"}]})
        assert a.ok

    def test_pronunciation_gap(self):
        a = self._make("pronunciation", {"items": [{"word": "hi"}]})
        assert not a.ok

    def test_sentence_correction_ok(self):
        a = self._make("sentence_correction", {"mode": "guided", "incorrect_sentence": "x"})
        assert a.ok

    def test_sentence_correction_gap(self):
        a = self._make("sentence_correction", {"incorrect_sentence": "x"})
        assert not a.ok

    def test_sentence_completion_ok(self):
        a = self._make("sentence_completion", {"items": [{"prompt": "p", "answer": "a"}]})
        assert a.ok

    def test_sentence_completion_gap(self):
        a = self._make("sentence_completion", {"items": [{"prompt": "p"}]})
        assert not a.ok

    def test_collocation_matching_ok(self):
        a = self._make("collocation_matching", {"pairs": [{"phrase": "p", "translation": "t"}]})
        assert a.ok

    def test_collocation_matching_gap(self):
        a = self._make("collocation_matching", {})
        assert not a.ok

    def test_idiom_ok(self):
        a = self._make("idiom", {"phrase": "p", "meaning_ru": "m", "example": "e", "example_ru": "er"})
        assert a.ok

    def test_idiom_gap(self):
        a = self._make("idiom", {"phrase": "p"})
        assert not a.ok


# ---------------------------------------------------------------------------
# format_markdown
# ---------------------------------------------------------------------------

class TestFormatMarkdown:
    def test_empty_audits(self):
        md = format_markdown([])
        assert "Remaining Lesson Types Schema Audit" in md
        assert "0" in md

    def test_all_ok_per_type(self):
        audits = [
            audit_content(1, "L1", "M1", "A1", "pronunciation",
                          {"items": [{"word": "hi", "phonetic": "/haɪ/"}]}),
        ]
        md = format_markdown(audits)
        assert "pronunciation: all OK" in md

    def test_gaps_shown(self):
        audits = [
            audit_content(1, "L1", "M1", "A1", "idiom",
                          {"phrase": "kick", "meaning_ru": "x"}),
        ]
        md = format_markdown(audits)
        assert "idiom" in md
        assert "gap" in md.lower() or "lesson(s)" in md

    def test_summary_table_present(self):
        audits = []
        md = format_markdown(audits)
        assert "Summary by type" in md
        assert "pronunciation" in md

    def test_changed_section_shown(self):
        md = format_markdown([], changed=[(1, "Lesson A", "guided")])
        assert "sentence_correction mode patches" in md
        assert "guided" in md


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_db_exits_zero(self):
        result = main(["--no-db"])
        assert result == 0

    def test_no_db_with_output(self, tmp_path):
        out = tmp_path / "report.md"
        result = main(["--no-db", "--output", str(out)])
        assert result == 0
