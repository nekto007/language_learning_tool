"""Tests for scripts/import_frequency_bands.py.

Pure-function tests only — no DB or Flask app required.
DB/integration path is covered by the --no-db guard in main().
"""
from __future__ import annotations

import csv
import sys
from io import StringIO
from pathlib import Path
from typing import Optional

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from import_frequency_bands import (  # noqa: E402
    ALLOWED_BANDS,
    CEFR_TO_BAND,
    BandChange,
    BandEntry,
    BandPlan,
    Repository,
    apply_plan,
    format_report,
    load_csv,
    parse_row,
    plan_bands,
    plan_cefr_fallback,
)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeWord:
    def __init__(self, word_id: int, english_word: str, level: Optional[str] = None, frequency_band: Optional[int] = None):
        self.id = word_id
        self.english_word = english_word
        self.level = level
        self.frequency_band = frequency_band


class FakeRepository(Repository):
    def __init__(self, words: list):
        self._words = {w.english_word.lower(): w for w in words}
        self._written: list = []

    def find_word(self, english_word: str) -> Optional[FakeWord]:
        return self._words.get(english_word.lower())

    def get_all_null_band_words(self) -> list:
        return [
            (w.id, w.english_word, w.level)
            for w in self._words.values()
            if w.frequency_band is None
        ]

    def set_frequency_band(self, word_id: int, band: int) -> None:
        for w in self._words.values():
            if w.id == word_id:
                w.frequency_band = band
                self._written.append((word_id, band))
                break


def _make_repo(*words: tuple) -> FakeRepository:
    """words: (word_id, english_word, level, frequency_band)"""
    objs = [FakeWord(*w) for w in words]
    return FakeRepository(objs)


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


class TestParseRow:
    def test_valid_row(self):
        entry, err = parse_row({"english_word": "hello", "frequency_band": "1"})
        assert err is None
        assert entry.english_word == "hello"
        assert entry.frequency_band == 1

    def test_all_valid_bands(self):
        for band in (1, 2, 3):
            entry, err = parse_row({"english_word": "word", "frequency_band": str(band)})
            assert err is None
            assert entry.frequency_band == band

    def test_invalid_band_0(self):
        _, err = parse_row({"english_word": "word", "frequency_band": "0"})
        assert err is not None

    def test_invalid_band_4(self):
        _, err = parse_row({"english_word": "word", "frequency_band": "4"})
        assert err is not None

    def test_invalid_band_string(self):
        _, err = parse_row({"english_word": "word", "frequency_band": "high"})
        assert err is not None

    def test_empty_word(self):
        _, err = parse_row({"english_word": "", "frequency_band": "1"})
        assert err is not None

    def test_missing_word(self):
        _, err = parse_row({"frequency_band": "1"})
        assert err is not None

    def test_strips_whitespace(self):
        entry, err = parse_row({"english_word": "  run  ", "frequency_band": " 2 "})
        assert err is None
        assert entry.english_word == "run"
        assert entry.frequency_band == 2

    def test_integer_band_value(self):
        entry, err = parse_row({"english_word": "go", "frequency_band": 3})
        assert err is None
        assert entry.frequency_band == 3


# ---------------------------------------------------------------------------
# load_csv
# ---------------------------------------------------------------------------


class TestLoadCsv:
    def _write_csv(self, path: Path, rows: list, comment: str = "") -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            if comment:
                fh.write(f"# {comment}\n")
            writer = csv.DictWriter(fh, fieldnames=["english_word", "frequency_band"])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_loads_valid_csv(self, tmp_path: Path):
        csv_path = tmp_path / "bands.csv"
        self._write_csv(csv_path, [
            {"english_word": "be", "frequency_band": 1},
            {"english_word": "ability", "frequency_band": 3},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 2
        assert entries[0].english_word == "be"
        assert entries[0].frequency_band == 1

    def test_skips_comment_lines(self, tmp_path: Path):
        csv_path = tmp_path / "bands.csv"
        csv_path.write_text(
            "# comment line\nenglish_word,frequency_band\nhello,1\n",
            encoding="utf-8",
        )
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1

    def test_missing_column_english_word(self, tmp_path: Path):
        csv_path = tmp_path / "bands.csv"
        csv_path.write_text("frequency_band\n1\n", encoding="utf-8")
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "english_word" in errors[0]

    def test_missing_column_frequency_band(self, tmp_path: Path):
        csv_path = tmp_path / "bands.csv"
        csv_path.write_text("english_word\nhello\n", encoding="utf-8")
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "frequency_band" in errors[0]

    def test_invalid_row_reported_not_halted(self, tmp_path: Path):
        csv_path = tmp_path / "bands.csv"
        self._write_csv(csv_path, [
            {"english_word": "good", "frequency_band": 1},
            {"english_word": "bad_band", "frequency_band": 9},
            {"english_word": "fine", "frequency_band": 2},
        ])
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert len(entries) == 2

    def test_duplicate_word_last_wins(self, tmp_path: Path):
        csv_path = tmp_path / "bands.csv"
        self._write_csv(csv_path, [
            {"english_word": "go", "frequency_band": 1},
            {"english_word": "go", "frequency_band": 2},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1
        assert entries[0].frequency_band == 2

    def test_file_not_found(self, tmp_path: Path):
        _, errors = load_csv([tmp_path / "missing.csv"])
        assert len(errors) == 1

    def test_merges_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        self._write_csv(f1, [{"english_word": "hello", "frequency_band": 1}])
        self._write_csv(f2, [{"english_word": "world", "frequency_band": 2}])
        entries, errors = load_csv([f1, f2])
        assert errors == []
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# plan_bands
# ---------------------------------------------------------------------------


class TestPlanBands:
    def _entry(self, word: str, band: int) -> BandEntry:
        return BandEntry(english_word=word, frequency_band=band)

    def test_sets_null_band(self):
        repo = _make_repo((1, "hello", "A1", None))
        plan = plan_bands([self._entry("hello", 1)], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].frequency_band == 1

    def test_noop_when_already_same_value(self):
        repo = _make_repo((1, "hello", "A1", 1))
        plan = plan_bands([self._entry("hello", 1)], repo, force=True)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 1

    def test_skips_existing_band_without_force(self):
        repo = _make_repo((1, "hello", "A1", 2))
        plan = plan_bands([self._entry("hello", 1)], repo, force=False)
        skips = [c for c in plan.changes if c.action == "skip_force"]
        assert len(skips) == 1

    def test_overwrites_existing_band_with_force(self):
        repo = _make_repo((1, "hello", "A1", 2))
        plan = plan_bands([self._entry("hello", 1)], repo, force=True)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].frequency_band == 1

    def test_skips_missing_word(self):
        repo = _make_repo()
        plan = plan_bands([self._entry("unknown", 1)], repo)
        skips = [c for c in plan.changes if c.action == "skip_no_match"]
        assert len(skips) == 1

    def test_case_insensitive_match(self):
        repo = _make_repo((1, "Hello", "A1", None))
        plan = plan_bands([self._entry("hello", 1)], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_priority_tier_filter_skips_wrong_tier(self):
        repo = _make_repo((1, "hello", "A1", None))
        priority_map = {"hello": 2}
        plan = plan_bands(
            [self._entry("hello", 1)],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        skips = [c for c in plan.changes if c.action == "skip_tier"]
        assert len(skips) == 1

    def test_priority_tier_filter_allows_matching_tier(self):
        repo = _make_repo((1, "hello", "A1", None))
        priority_map = {"hello": 1}
        plan = plan_bands(
            [self._entry("hello", 1)],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_multiple_entries(self):
        repo = _make_repo(
            (1, "be", "A1", None),
            (2, "run", "A2", 1),
            (3, "analyze", "C1", None),
        )
        entries = [
            self._entry("be", 1),
            self._entry("run", 1),
            self._entry("analyze", 3),
        ]
        plan = plan_bands(entries, repo, force=False)
        c = plan.counts
        assert c.get("set", 0) == 2   # be and analyze
        assert c.get("skip_force", 0) == 1  # run has existing band


# ---------------------------------------------------------------------------
# plan_cefr_fallback
# ---------------------------------------------------------------------------


class TestPlanCefrFallback:
    def test_a1_gets_band_1(self):
        repo = _make_repo((1, "hello", "A1", None))
        plan = plan_cefr_fallback(repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].frequency_band == 1

    def test_a2_gets_band_1(self):
        repo = _make_repo((1, "go", "A2", None))
        plan = plan_cefr_fallback(repo)
        assert plan.changes[0].frequency_band == 1

    def test_b1_gets_band_2(self):
        repo = _make_repo((1, "discuss", "B1", None))
        plan = plan_cefr_fallback(repo)
        assert plan.changes[0].frequency_band == 2

    def test_b2_gets_band_2(self):
        repo = _make_repo((1, "negotiate", "B2", None))
        plan = plan_cefr_fallback(repo)
        assert plan.changes[0].frequency_band == 2

    def test_c1_gets_band_3(self):
        repo = _make_repo((1, "phenomenon", "C1", None))
        plan = plan_cefr_fallback(repo)
        assert plan.changes[0].frequency_band == 3

    def test_null_level_gets_band_3(self):
        repo = _make_repo((1, "unknown_word", None, None))
        plan = plan_cefr_fallback(repo)
        assert plan.changes[0].frequency_band == 3

    def test_already_set_words_not_returned(self):
        repo = _make_repo(
            (1, "hello", "A1", 1),
            (2, "world", "A2", None),
        )
        plan = plan_cefr_fallback(repo)
        assert len(plan.changes) == 1
        assert plan.changes[0].english_word == "world"

    def test_empty_db_returns_empty_plan(self):
        repo = _make_repo()
        plan = plan_cefr_fallback(repo)
        assert plan.changes == []


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_applies_set_changes(self):
        repo = _make_repo((1, "hello", "A1", None), (2, "world", "A2", None))
        plan = BandPlan(changes=[
            BandChange(action="set", english_word="hello", frequency_band=1, word_id=1),
            BandChange(action="set", english_word="world", frequency_band=1, word_id=2),
        ])
        count = apply_plan(plan, repo)
        assert count == 2
        assert len(repo._written) == 2

    def test_skips_non_set_changes(self):
        repo = _make_repo((1, "hello", "A1", 1))
        plan = BandPlan(changes=[
            BandChange(action="noop", english_word="hello", frequency_band=1, word_id=1),
            BandChange(action="skip_force", english_word="hello", frequency_band=2, word_id=1),
            BandChange(action="skip_no_match", english_word="missing", frequency_band=1),
        ])
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo._written == []

    def test_idempotent_after_apply(self):
        repo = _make_repo((1, "hello", "A1", None))
        entry = BandEntry(english_word="hello", frequency_band=1)
        plan1 = plan_bands([entry], repo)
        apply_plan(plan1, repo)
        # Second plan: word now has band=1, same value → noop
        plan2 = plan_bands([entry], repo, force=True)
        noops = [c for c in plan2.changes if c.action == "noop"]
        assert len(noops) == 1
        apply_plan(plan2, repo)
        # Written only once total
        assert len(repo._written) == 1


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _plan(self, *changes) -> BandPlan:
        return BandPlan(changes=list(changes))

    def test_contains_title(self):
        plan = self._plan()
        report = format_report(plan, None, dry_run=False, force=False, elapsed=0.1)
        assert "Frequency Band Import Report" in report

    def test_dry_run_flag_visible(self):
        plan = self._plan()
        report = format_report(plan, None, dry_run=True, force=False, elapsed=0.1)
        assert "dry-run" in report

    def test_set_count_shown(self):
        plan = self._plan(
            BandChange(action="set", english_word="go", frequency_band=1, word_id=1),
            BandChange(action="set", english_word="be", frequency_band=1, word_id=2),
        )
        report = format_report(plan, None, dry_run=False, force=False, elapsed=0.5)
        assert "set" in report
        assert "2" in report

    def test_errors_listed(self):
        plan = self._plan()
        plan.errors = ["file.csv[0]: bad band"]
        report = format_report(plan, None, dry_run=False, force=False, elapsed=0.1)
        assert "bad band" in report

    def test_fallback_section_when_provided(self):
        csv_plan = self._plan()
        fb_plan = self._plan(
            BandChange(action="set", english_word="analyze", frequency_band=3, word_id=5),
        )
        report = format_report(csv_plan, fb_plan, dry_run=False, force=False, elapsed=0.1)
        assert "CEFR Fallback" in report

    def test_no_fallback_section_when_none(self):
        plan = self._plan()
        report = format_report(plan, None, dry_run=False, force=False, elapsed=0.1)
        assert "CEFR Fallback" not in report

    def test_total_rows_written(self):
        plan = self._plan(
            BandChange(action="set", english_word="go", frequency_band=1, word_id=1),
        )
        report = format_report(plan, None, dry_run=False, force=False, elapsed=0.1)
        assert "Total rows written: 1" in report


# ---------------------------------------------------------------------------
# Integration: CSV file round-trip (uses real frequency_bands.csv)
# ---------------------------------------------------------------------------


class TestRealCsvFile:
    def test_real_csv_loads_without_errors(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "frequency_bands.csv"
        if not csv_path.exists():
            pytest.skip("frequency_bands.csv not present")
        entries, errors = load_csv([csv_path])
        assert errors == [], f"Unexpected errors: {errors}"
        assert len(entries) > 0

    def test_all_bands_are_valid(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "frequency_bands.csv"
        if not csv_path.exists():
            pytest.skip("frequency_bands.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert e.frequency_band in ALLOWED_BANDS, (
                f"Invalid band {e.frequency_band!r} for word {e.english_word!r}"
            )

    def test_real_csv_has_all_three_bands(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "frequency_bands.csv"
        if not csv_path.exists():
            pytest.skip("frequency_bands.csv not present")
        entries, _ = load_csv([csv_path])
        bands_present = {e.frequency_band for e in entries}
        assert bands_present == {1, 2, 3}, f"Expected all 3 bands, got {bands_present}"


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from import_frequency_bands import main
        assert main(["--no-db"]) == 0
