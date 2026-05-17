"""Tests for scripts/import_ipa_transcriptions.py.

Pure-function tests only — no DB or Flask app required.
DB/integration path is covered by the --no-db guard in main().
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import pytest

import sys

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from import_ipa_transcriptions import (  # noqa: E402
    IpaChange,
    IpaEntry,
    IpaPlan,
    Repository,
    apply_plan,
    format_report,
    load_csv,
    normalize_ipa,
    parse_row,
    plan_ipa,
)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeWord:
    def __init__(
        self,
        word_id: int,
        english_word: str,
        level: Optional[str] = None,
        ipa_transcription: Optional[str] = None,
    ):
        self.id = word_id
        self.english_word = english_word
        self.level = level
        self.ipa_transcription = ipa_transcription


class FakeRepository(Repository):
    def __init__(self, words: list):
        self._by_id = {w.id: w for w in words}
        self._by_name = {w.english_word.lower(): w for w in words}
        self._written: list = []

    def find_word_by_id(self, word_id: int) -> Optional[FakeWord]:
        return self._by_id.get(word_id)

    def find_word_by_name(self, english_word: str) -> Optional[FakeWord]:
        return self._by_name.get(english_word.lower())

    def set_ipa(self, word_id: int, ipa: str) -> None:
        w = self._by_id.get(word_id)
        if w is not None:
            w.ipa_transcription = ipa
            self._written.append((word_id, ipa))


def _make_repo(*words: tuple) -> FakeRepository:
    """words: (word_id, english_word, level, ipa_transcription)"""
    objs = [FakeWord(*w) for w in words]
    return FakeRepository(objs)


# ---------------------------------------------------------------------------
# normalize_ipa
# ---------------------------------------------------------------------------


class TestNormalizeIpa:
    def test_plain_value_unchanged(self):
        val, err = normalize_ipa("biː")
        assert err is None
        assert val == "biː"

    def test_strips_surrounding_slashes(self):
        val, err = normalize_ipa("/biː/")
        assert err is None
        assert val == "biː"

    def test_strips_whitespace(self):
        val, err = normalize_ipa("  biː  ")
        assert err is None
        assert val == "biː"

    def test_strips_slashes_and_whitespace(self):
        val, err = normalize_ipa("  /biː/  ")
        assert err is None
        assert val == "biː"

    def test_empty_string_returns_error(self):
        val, err = normalize_ipa("")
        assert val is None
        assert err is not None

    def test_only_slashes_returns_error(self):
        val, err = normalize_ipa("//")
        assert val is None
        assert err is not None

    def test_complex_ipa_preserved(self):
        val, err = normalize_ipa("ˌʌndərˈstænd")
        assert err is None
        assert val == "ˌʌndərˈstænd"

    def test_internal_slash_preserved(self):
        # Unusual but should not strip internal slashes
        val, err = normalize_ipa("a/b")
        assert err is None
        assert val == "a/b"


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


class TestParseRow:
    def test_valid_row(self):
        entry, err = parse_row({"english_word": "be", "ipa": "biː"})
        assert err is None
        assert entry.english_word == "be"
        assert entry.ipa == "biː"
        assert entry.word_id is None

    def test_strips_slashes_from_ipa(self):
        entry, err = parse_row({"english_word": "be", "ipa": "/biː/"})
        assert err is None
        assert entry.ipa == "biː"

    def test_empty_word_returns_error(self):
        _, err = parse_row({"english_word": "", "ipa": "biː"})
        assert err is not None

    def test_missing_word_returns_error(self):
        _, err = parse_row({"ipa": "biː"})
        assert err is not None

    def test_empty_ipa_returns_error(self):
        _, err = parse_row({"english_word": "be", "ipa": ""})
        assert err is not None

    def test_slash_only_ipa_returns_error(self):
        _, err = parse_row({"english_word": "be", "ipa": "//"})
        assert err is not None

    def test_accepts_ipa_transcription_column_alias(self):
        entry, err = parse_row({"english_word": "be", "ipa_transcription": "biː"})
        assert err is None
        assert entry.ipa == "biː"

    def test_word_id_parsed_when_present(self):
        entry, err = parse_row({"english_word": "be", "ipa": "biː", "word_id": "42"})
        assert err is None
        assert entry.word_id == 42

    def test_empty_word_id_treated_as_none(self):
        entry, err = parse_row({"english_word": "be", "ipa": "biː", "word_id": ""})
        assert err is None
        assert entry.word_id is None

    def test_invalid_word_id_returns_error(self):
        _, err = parse_row({"english_word": "be", "ipa": "biː", "word_id": "abc"})
        assert err is not None

    def test_strips_whitespace_from_word(self):
        entry, err = parse_row({"english_word": "  run  ", "ipa": "rʌn"})
        assert err is None
        assert entry.english_word == "run"


# ---------------------------------------------------------------------------
# load_csv
# ---------------------------------------------------------------------------


class TestLoadCsv:
    def _write_csv(self, path: Path, rows: list, comment: str = "") -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            if comment:
                fh.write(f"# {comment}\n")
            writer = csv.DictWriter(fh, fieldnames=["english_word", "ipa"])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_loads_valid_csv(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        self._write_csv(csv_path, [
            {"english_word": "be", "ipa": "biː"},
            {"english_word": "go", "ipa": "ɡoʊ"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 2

    def test_skips_comment_lines(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        csv_path.write_text(
            "# comment\nenglish_word,ipa\nhello,həˈloʊ\n",
            encoding="utf-8",
        )
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1

    def test_missing_english_word_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        csv_path.write_text("ipa\nbiː\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "english_word" in errors[0]

    def test_missing_ipa_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        csv_path.write_text("english_word\nbe\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "ipa" in errors[0]

    def test_invalid_row_reported_not_halted(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        self._write_csv(csv_path, [
            {"english_word": "be", "ipa": "biː"},
            {"english_word": "bad", "ipa": ""},
            {"english_word": "go", "ipa": "ɡoʊ"},
        ])
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert len(entries) == 2

    def test_duplicate_word_last_wins(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        self._write_csv(csv_path, [
            {"english_word": "go", "ipa": "ɡoʊ"},
            {"english_word": "go", "ipa": "ɡɔː"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1
        assert entries[0].ipa == "ɡɔː"

    def test_file_not_found_reported(self, tmp_path: Path):
        _, errors = load_csv([tmp_path / "missing.csv"])
        assert len(errors) == 1

    def test_merges_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        self._write_csv(f1, [{"english_word": "be", "ipa": "biː"}])
        self._write_csv(f2, [{"english_word": "go", "ipa": "ɡoʊ"}])
        entries, errors = load_csv([f1, f2])
        assert errors == []
        assert len(entries) == 2

    def test_slashes_stripped_during_load(self, tmp_path: Path):
        csv_path = tmp_path / "ipa.csv"
        self._write_csv(csv_path, [{"english_word": "be", "ipa": "/biː/"}])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert entries[0].ipa == "biː"


# ---------------------------------------------------------------------------
# plan_ipa
# ---------------------------------------------------------------------------


class TestPlanIpa:
    def _entry(self, word: str, ipa: str, word_id: Optional[int] = None) -> IpaEntry:
        return IpaEntry(english_word=word, ipa=ipa, word_id=word_id)

    def test_sets_null_ipa(self):
        repo = _make_repo((1, "be", "A1", None))
        plan = plan_ipa([self._entry("be", "biː")], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].ipa == "biː"

    def test_noop_when_already_same_value(self):
        repo = _make_repo((1, "be", "A1", "biː"))
        plan = plan_ipa([self._entry("be", "biː")], repo, force=True)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 1

    def test_skips_existing_ipa_without_force(self):
        repo = _make_repo((1, "be", "A1", "biː"))
        plan = plan_ipa([self._entry("be", "biːalt")], repo, force=False)
        skips = [c for c in plan.changes if c.action == "skip_force"]
        assert len(skips) == 1

    def test_overwrites_existing_ipa_with_force(self):
        repo = _make_repo((1, "be", "A1", "biː"))
        plan = plan_ipa([self._entry("be", "biːalt")], repo, force=True)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].ipa == "biːalt"

    def test_skips_missing_word(self):
        repo = _make_repo()
        plan = plan_ipa([self._entry("unknown", "ʌnˈnoʊn")], repo)
        skips = [c for c in plan.changes if c.action == "skip_no_match"]
        assert len(skips) == 1

    def test_case_insensitive_name_match(self):
        repo = _make_repo((1, "Hello", "A1", None))
        plan = plan_ipa([self._entry("hello", "həˈloʊ")], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_word_id_takes_priority_over_name(self):
        repo = _make_repo((1, "be", "A1", None), (2, "go", "A1", None))
        # word_id=2 points to "go" even though english_word says "be"
        plan = plan_ipa([self._entry("be", "ɡoʊ", word_id=2)], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].word_id == 2

    def test_priority_tier_filter_skips_wrong_tier(self):
        repo = _make_repo((1, "hello", "A1", None))
        priority_map = {"hello": 2}
        plan = plan_ipa(
            [self._entry("hello", "həˈloʊ")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        skips = [c for c in plan.changes if c.action == "skip_tier"]
        assert len(skips) == 1

    def test_priority_tier_filter_allows_matching_tier(self):
        repo = _make_repo((1, "hello", "A1", None))
        priority_map = {"hello": 1}
        plan = plan_ipa(
            [self._entry("hello", "həˈloʊ")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_multiple_entries_mixed_states(self):
        repo = _make_repo(
            (1, "be", "A1", None),
            (2, "go", "A2", "ɡoʊ"),
            (3, "think", "B1", None),
        )
        entries = [
            self._entry("be", "biː"),
            self._entry("go", "ɡoʊ"),
            self._entry("think", "θɪŋk"),
        ]
        plan = plan_ipa(entries, repo, force=False)
        c = plan.counts
        assert c.get("set", 0) == 2       # be and think
        assert c.get("skip_force", 0) == 1  # go already has value


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_applies_set_changes(self):
        repo = _make_repo((1, "be", "A1", None), (2, "go", "A2", None))
        plan = IpaPlan(changes=[
            IpaChange(action="set", english_word="be", ipa="biː", word_id=1),
            IpaChange(action="set", english_word="go", ipa="ɡoʊ", word_id=2),
        ])
        count = apply_plan(plan, repo)
        assert count == 2
        assert len(repo._written) == 2

    def test_skips_non_set_actions(self):
        repo = _make_repo((1, "be", "A1", "biː"))
        plan = IpaPlan(changes=[
            IpaChange(action="noop", english_word="be", ipa="biː", word_id=1),
            IpaChange(action="skip_force", english_word="be", ipa="biː", word_id=1),
            IpaChange(action="skip_no_match", english_word="missing", ipa="x"),
        ])
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo._written == []

    def test_idempotent_second_run(self):
        repo = _make_repo((1, "be", "A1", None))
        entry = IpaEntry(english_word="be", ipa="biː")
        plan1 = plan_ipa([entry], repo)
        apply_plan(plan1, repo)
        # Second plan: word now has ipa=biː, same value → noop
        plan2 = plan_ipa([entry], repo, force=True)
        noops = [c for c in plan2.changes if c.action == "noop"]
        assert len(noops) == 1
        apply_plan(plan2, repo)
        # Written only once total
        assert len(repo._written) == 1


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _plan(self, *changes) -> IpaPlan:
        return IpaPlan(changes=list(changes))

    def test_contains_title(self):
        plan = self._plan()
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "IPA Transcription Import Report" in report

    def test_dry_run_flag_visible(self):
        plan = self._plan()
        report = format_report(plan, dry_run=True, force=False, elapsed=0.1)
        assert "dry-run" in report

    def test_set_count_visible(self):
        plan = self._plan(
            IpaChange(action="set", english_word="be", ipa="biː", word_id=1),
            IpaChange(action="set", english_word="go", ipa="ɡoʊ", word_id=2),
        )
        report = format_report(plan, dry_run=False, force=False, elapsed=0.5)
        assert "set" in report
        assert "2" in report

    def test_errors_listed(self):
        plan = self._plan()
        plan.errors = ["ipa.csv[0]: empty IPA value"]
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "empty IPA value" in report

    def test_total_rows_written_shown(self):
        plan = self._plan(
            IpaChange(action="set", english_word="be", ipa="biː", word_id=1),
        )
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "Total rows written: 1" in report

    def test_not_found_words_listed(self):
        plan = self._plan(
            IpaChange(action="skip_no_match", english_word="xyzzy", ipa="ˈzɪzi"),
        )
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "xyzzy" in report


# ---------------------------------------------------------------------------
# Integration: real CSV file
# ---------------------------------------------------------------------------


class TestRealCsvFile:
    def test_real_csv_loads_without_errors(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "ipa_transcriptions.csv"
        if not csv_path.exists():
            pytest.skip("ipa_transcriptions.csv not present")
        entries, errors = load_csv([csv_path])
        assert errors == [], f"Unexpected load errors: {errors}"
        assert len(entries) > 0

    def test_no_values_have_surrounding_slashes(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "ipa_transcriptions.csv"
        if not csv_path.exists():
            pytest.skip("ipa_transcriptions.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert not e.ipa.startswith("/"), f"Slash prefix in {e.english_word!r}: {e.ipa!r}"
            assert not e.ipa.endswith("/"), f"Slash suffix in {e.english_word!r}: {e.ipa!r}"

    def test_all_english_words_are_non_empty(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "ipa_transcriptions.csv"
        if not csv_path.exists():
            pytest.skip("ipa_transcriptions.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert e.english_word.strip(), "Empty english_word in CSV"

    def test_real_csv_has_multiple_cefr_levels(self):
        """Sanity check: CSV should cover both simple and complex words."""
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "ipa_transcriptions.csv"
        if not csv_path.exists():
            pytest.skip("ipa_transcriptions.csv not present")
        entries, _ = load_csv([csv_path])
        words = {e.english_word.lower() for e in entries}
        # Basic words must be present
        assert "be" in words
        assert "have" in words
        # Complex words must be present
        assert "phenomenon" in words or "hypothesis" in words or "facilitate" in words


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from import_ipa_transcriptions import main
        assert main(["--no-db"]) == 0
