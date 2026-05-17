"""Tests for the listening_quiz inline audio audit script."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIO_BASE = PROJECT_ROOT / "app" / "static" / "audio"

sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Unit tests for the audit helpers (no DB required)
# ---------------------------------------------------------------------------

class TestSoundRefExtraction:
    """_extract_refs correctly parses [sound:...] patterns."""

    def _extract(self, exercises):
        from scripts.audit_listening_quiz_inline_audio import _extract_refs
        return _extract_refs(exercises, lesson_id=1, title="Test")

    def test_basic_extraction(self):
        exercises = [{"audio": "[sound:A1M1L6_ex1.mp3]", "type": "listening_choice"}]
        refs = self._extract(exercises)
        assert len(refs) == 1
        assert refs[0].filename == "A1M1L6_ex1.mp3"

    def test_no_audio_field_skipped(self):
        exercises = [{"type": "listening_choice", "question": "What did you hear?"}]
        refs = self._extract(exercises)
        assert len(refs) == 0

    def test_empty_audio_skipped(self):
        exercises = [{"audio": "", "type": "listening_choice"}]
        refs = self._extract(exercises)
        assert len(refs) == 0

    def test_multiple_exercises(self):
        exercises = [
            {"audio": "[sound:A1M1L6_ex1.mp3]"},
            {"audio": "[sound:A1M1L6_ex2.mp3]"},
            {"audio": "[sound:A1M1L6_ex3.mp3]"},
        ]
        refs = self._extract(exercises)
        assert len(refs) == 3
        assert [r.filename for r in refs] == [
            "A1M1L6_ex1.mp3",
            "A1M1L6_ex2.mp3",
            "A1M1L6_ex3.mp3",
        ]

    def test_exercise_index_recorded(self):
        exercises = [{"audio": "[sound:X.mp3]"}, {"audio": "[sound:Y.mp3]"}]
        refs = self._extract(exercises)
        assert refs[0].exercise_idx == 0
        assert refs[1].exercise_idx == 1

    def test_plain_filename_not_matched(self):
        exercises = [{"audio": "A1M1L6_ex1.mp3"}]
        refs = self._extract(exercises)
        assert len(refs) == 0, "Bare filenames are not [sound:...] format"


class TestAudioIndex:
    """_build_audio_index correctly enumerates files."""

    def test_indexes_direct_children(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        from scripts.audit_listening_quiz_inline_audio import _build_audio_index
        index = _build_audio_index(tmp_path)
        assert "a.mp3" in index
        assert "b.mp3" in index

    def test_indexes_subdirectory_files(self, tmp_path):
        sub = tmp_path / "immersion" / "dictation"
        sub.mkdir(parents=True)
        (sub / "deep.mp3").write_bytes(b"x")
        from scripts.audit_listening_quiz_inline_audio import _build_audio_index
        index = _build_audio_index(tmp_path)
        assert "deep.mp3" in index

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        from scripts.audit_listening_quiz_inline_audio import _build_audio_index
        index = _build_audio_index(tmp_path / "nonexistent")
        assert index == set()


class TestLessonAuditDataclass:
    """LessonAudit computed properties work correctly."""

    def _make_ref(self, exists):
        from scripts.audit_listening_quiz_inline_audio import ExerciseRef
        return ExerciseRef(lesson_id=1, lesson_title="T", exercise_idx=0, filename="x.mp3", exists=exists)

    def test_all_present(self):
        from scripts.audit_listening_quiz_inline_audio import LessonAudit
        la = LessonAudit(lesson_id=1, title="T", refs=[self._make_ref(True), self._make_ref(True)])
        assert la.total == 2
        assert la.present == 2
        assert la.missing == 0
        assert la.ok is True

    def test_some_missing(self):
        from scripts.audit_listening_quiz_inline_audio import LessonAudit
        la = LessonAudit(lesson_id=1, title="T", refs=[self._make_ref(True), self._make_ref(False)])
        assert la.missing == 1
        assert la.ok is False

    def test_empty_refs(self):
        from scripts.audit_listening_quiz_inline_audio import LessonAudit
        la = LessonAudit(lesson_id=1, title="T", refs=[])
        assert la.total == 0
        assert la.ok is True


class TestReportRendering:
    """_render_report produces correct Markdown output."""

    def _make_result(self, lesson_id, missing_count):
        from scripts.audit_listening_quiz_inline_audio import ExerciseRef, LessonAudit
        refs = [
            ExerciseRef(lesson_id=lesson_id, lesson_title="T", exercise_idx=i,
                        filename=f"f{i}.mp3", exists=(i >= missing_count))
            for i in range(4)
        ]
        return LessonAudit(lesson_id=lesson_id, title="T", refs=refs)

    def test_all_ok_contains_no_generation_needed(self):
        from scripts.audit_listening_quiz_inline_audio import _render_report
        results = [self._make_result(1, 0)]
        report = _render_report(results, {"f0.mp3", "f1.mp3", "f2.mp3", "f3.mp3"})
        assert "No generation needed" in report

    def test_missing_listed_in_report(self):
        from scripts.audit_listening_quiz_inline_audio import _render_report
        results = [self._make_result(1, 2)]  # exercises 0,1 missing
        report = _render_report(results, set())
        assert "f0.mp3" in report
        assert "f1.mp3" in report
        assert "f2.mp3" not in report  # present

    def test_design_note_present(self):
        from scripts.audit_listening_quiz_inline_audio import _render_report
        results = [self._make_result(1, 0)]
        report = _render_report(results, set())
        assert "item-level" in report
        assert "audio_url" in report

    def test_summary_counts_correct(self):
        from scripts.audit_listening_quiz_inline_audio import _render_report
        results = [self._make_result(1, 0), self._make_result(2, 0)]
        report = _render_report(results, set())
        assert "Total listening_quiz lessons audited: **2**" in report
        assert "Total exercise audio references: **8**" in report


# ---------------------------------------------------------------------------
# Integration smoke test: real filesystem check (no DB)
# ---------------------------------------------------------------------------

class TestFilesystemCheck:
    """Verify the real audio directory has no obvious gaps for [sound:...] files."""

    @pytest.mark.smoke
    def test_audio_base_exists(self):
        assert AUDIO_BASE.exists(), f"Audio base dir missing: {AUDIO_BASE}"

    @pytest.mark.smoke
    def test_ex_files_present_in_audio_base(self):
        """At least one _ex file must exist (confirms the directory structure)."""
        ex_files = list(AUDIO_BASE.glob("*_ex*.mp3"))
        assert len(ex_files) > 0, "No _ex*.mp3 files found directly in app/static/audio/"

    @pytest.mark.smoke
    def test_a1m1_lesson6_audio_present(self):
        """Spot-check: A1M1L6_ex1.mp3 must exist (foundational quiz lesson)."""
        target = AUDIO_BASE / "A1M1L6_ex1.mp3"
        assert target.exists(), f"Expected {target} to exist"

    def test_sound_ref_pattern_matches_real_filenames(self):
        """Filenames from the filesystem satisfy the [sound:...] regex extraction."""
        from scripts.audit_listening_quiz_inline_audio import SOUND_RE
        sample_refs = [
            "[sound:A1M1L6_ex1.mp3]",
            "[sound:B2M58L6_ex3.mp3]",
            "[sound:C1M71L6_ex8.mp3]",
        ]
        for ref in sample_refs:
            m = SOUND_RE.search(ref)
            assert m is not None, f"Pattern did not match: {ref}"
            filename = m.group(1)
            assert filename.endswith(".mp3")
