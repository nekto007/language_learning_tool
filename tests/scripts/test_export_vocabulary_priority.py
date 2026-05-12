"""Tests for scripts/export_vocabulary_priority.py.

Pure-function tests only — no DB or Flask app required.
DB/integration path is covered by the --no-db guard in main().
"""
from __future__ import annotations

import csv
import sys
from io import StringIO
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from export_vocabulary_priority import (  # noqa: E402
    CSV_FIELDS,
    TIER_1_LEVELS,
    TIER_2_LEVELS,
    WordPriority,
    assign_tier_pure,
    export_csv,
    sort_priorities,
)


# ---------------------------------------------------------------------------
# assign_tier_pure
# ---------------------------------------------------------------------------

class TestAssignTier:
    def test_a1_level_is_tier1(self):
        assert assign_tier_pure("A1", 0, 0) == 1

    def test_a2_level_is_tier1(self):
        assert assign_tier_pure("A2", 0, 0) == 1

    def test_b1_level_no_usage_is_tier2(self):
        assert assign_tier_pure("B1", 0, 0) == 2

    def test_b2_level_no_usage_is_tier2(self):
        assert assign_tier_pure("B2", 0, 0) == 2

    def test_c1_no_usage_is_tier3(self):
        assert assign_tier_pure("C1", 0, 0) == 3

    def test_c2_no_usage_is_tier3(self):
        assert assign_tier_pure("C2", 0, 0) == 3

    def test_no_level_no_usage_is_tier3(self):
        assert assign_tier_pure(None, 0, 0) == 3

    def test_empty_level_no_usage_is_tier3(self):
        assert assign_tier_pure("", 0, 0) == 3

    def test_two_curriculum_lessons_elevates_to_tier1(self):
        assert assign_tier_pure("C1", 2, 0) == 1

    def test_many_curriculum_lessons_is_tier1(self):
        assert assign_tier_pure(None, 10, 0) == 1

    def test_three_users_elevates_to_tier1(self):
        assert assign_tier_pure("C2", 0, 3) == 1

    def test_many_users_is_tier1(self):
        assert assign_tier_pure(None, 0, 50) == 1

    def test_one_curriculum_lesson_is_tier2_for_unknown_level(self):
        assert assign_tier_pure(None, 1, 0) == 2

    def test_two_users_is_tier2_for_unknown_level(self):
        assert assign_tier_pure(None, 0, 2) == 2

    def test_one_user_is_tier2_for_unknown_level(self):
        assert assign_tier_pure(None, 0, 1) == 2

    def test_b1_with_many_users_is_tier1(self):
        assert assign_tier_pure("B1", 0, 5) == 1

    def test_a1_with_zero_usage_stays_tier1(self):
        # A1/A2 words are always tier 1 regardless of usage
        assert assign_tier_pure("A1", 0, 0) == 1


# ---------------------------------------------------------------------------
# sort_priorities
# ---------------------------------------------------------------------------

def _word(word_id: int, level: str, tier: int, curriculum: int = 0, users: int = 0) -> WordPriority:
    return WordPriority(
        word_id=word_id,
        english_word=f"word_{word_id}",
        level=level,
        curriculum_lessons=curriculum,
        user_count=users,
        priority_tier=tier,
        has_ipa=False,
        has_frequency_band=False,
        has_synonyms=False,
        has_antonyms=False,
        has_etymology=False,
    )


class TestSortPriorities:
    def test_tier1_before_tier2_before_tier3(self):
        words = [
            _word(3, "C1", 3),
            _word(1, "A1", 1),
            _word(2, "B1", 2),
        ]
        sorted_words = sort_priorities(words)
        assert [w.word_id for w in sorted_words] == [1, 2, 3]

    def test_within_tier1_a1_before_a2(self):
        words = [
            _word(2, "A2", 1),
            _word(1, "A1", 1),
        ]
        sorted_words = sort_priorities(words)
        assert [w.word_id for w in sorted_words] == [1, 2]

    def test_same_tier_same_level_sorted_by_word_id(self):
        words = [
            _word(5, "B1", 2),
            _word(2, "B1", 2),
            _word(9, "B1", 2),
        ]
        sorted_words = sort_priorities(words)
        assert [w.word_id for w in sorted_words] == [2, 5, 9]

    def test_empty_list_returns_empty(self):
        assert sort_priorities([]) == []

    def test_within_tier1_unknown_level_after_a2(self):
        words = [
            _word(2, "", 1, curriculum=5),  # no level but high usage → tier 1
            _word(1, "A2", 1),
        ]
        sorted_words = sort_priorities(words)
        assert sorted_words[0].word_id == 1  # A2 before unknown


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------

def _make_priority_row(word_id: int = 1) -> WordPriority:
    return WordPriority(
        word_id=word_id,
        english_word=f"test_{word_id}",
        level="A1",
        curriculum_lessons=3,
        user_count=5,
        priority_tier=1,
        has_ipa=True,
        has_frequency_band=False,
        has_synonyms=True,
        has_antonyms=False,
        has_etymology=False,
    )


class TestExportCsv:
    def test_dry_run_does_not_create_file(self, tmp_path: Path, capsys):
        out_path = tmp_path / "priority_words.csv"
        rows = [_make_priority_row(1), _make_priority_row(2)]
        count = export_csv(rows, out_path, tier_filter=None, dry_run=True, generator="test")
        assert not out_path.exists()
        assert count == 2
        captured = capsys.readouterr()
        assert "dry-run" in captured.out
        assert "2 rows" in captured.out

    def test_writes_csv_file(self, tmp_path: Path):
        out_path = tmp_path / "priority_words.csv"
        rows = [_make_priority_row(1), _make_priority_row(2)]
        count = export_csv(rows, out_path, tier_filter=None, dry_run=False, generator="test")
        assert out_path.exists()
        assert count == 2

    def test_csv_has_correct_header(self, tmp_path: Path):
        out_path = tmp_path / "priority_words.csv"
        export_csv([_make_priority_row()], out_path, tier_filter=None, dry_run=False, generator="test")
        content = out_path.read_text(encoding="utf-8")
        # Skip comment lines
        data_lines = [line for line in content.splitlines() if not line.startswith("#")]
        reader = csv.DictReader(data_lines)
        assert set(reader.fieldnames or []) == set(CSV_FIELDS)

    def test_csv_has_correct_values(self, tmp_path: Path):
        out_path = tmp_path / "priority_words.csv"
        row = _make_priority_row(42)
        export_csv([row], out_path, tier_filter=None, dry_run=False, generator="test")
        content = out_path.read_text(encoding="utf-8")
        data_lines = [line for line in content.splitlines() if not line.startswith("#")]
        reader = csv.DictReader(data_lines)
        parsed = list(reader)
        assert len(parsed) == 1
        r = parsed[0]
        assert r["word_id"] == "42"
        assert r["english_word"] == "test_42"
        assert r["level"] == "A1"
        assert r["curriculum_lessons"] == "3"
        assert r["user_count"] == "5"
        assert r["priority_tier"] == "1"
        assert r["has_ipa"] == "1"
        assert r["has_frequency_band"] == "0"
        assert r["has_synonyms"] == "1"
        assert r["has_antonyms"] == "0"
        assert r["has_etymology"] == "0"

    def test_tier_filter_keeps_only_matching_tier(self, tmp_path: Path):
        out_path = tmp_path / "priority_words.csv"
        tier1 = _make_priority_row(1)
        tier3 = WordPriority(
            word_id=2, english_word="rare", level="C2",
            curriculum_lessons=0, user_count=0, priority_tier=3,
            has_ipa=False, has_frequency_band=False,
            has_synonyms=False, has_antonyms=False, has_etymology=False,
        )
        count = export_csv(
            [tier1, tier3], out_path, tier_filter=1, dry_run=False, generator="test"
        )
        assert count == 1
        content = out_path.read_text(encoding="utf-8")
        data_lines = [line for line in content.splitlines() if not line.startswith("#")]
        reader = csv.DictReader(data_lines)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["word_id"] == "1"

    def test_comment_header_contains_metadata(self, tmp_path: Path):
        out_path = tmp_path / "priority_words.csv"
        export_csv([_make_priority_row()], out_path, tier_filter=2, dry_run=False, generator="scripts/test.py")
        lines = out_path.read_text(encoding="utf-8").splitlines()
        comments = [l for l in lines if l.startswith("#")]
        combined = "\n".join(comments)
        assert "generated_by" in combined
        assert "scripts/test.py" in combined
        assert "generated_at" in combined
        assert "tier_filter: 2" in combined

    def test_creates_parent_directories(self, tmp_path: Path):
        out_path = tmp_path / "nested" / "dir" / "priority_words.csv"
        export_csv([_make_priority_row()], out_path, tier_filter=None, dry_run=False, generator="test")
        assert out_path.exists()

    def test_empty_input_writes_header_only(self, tmp_path: Path):
        out_path = tmp_path / "priority_words.csv"
        count = export_csv([], out_path, tier_filter=None, dry_run=False, generator="test")
        assert count == 0
        content = out_path.read_text(encoding="utf-8")
        data_lines = [line for line in content.splitlines() if not line.startswith("#")]
        reader = csv.DictReader(data_lines)
        assert list(reader) == []


# ---------------------------------------------------------------------------
# main() --no-db guard
# ---------------------------------------------------------------------------

class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from export_vocabulary_priority import main
        assert main(["--no-db"]) == 0
