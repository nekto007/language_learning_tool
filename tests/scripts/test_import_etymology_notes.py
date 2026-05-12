"""Tests for scripts/import_etymology_notes.py.

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

from import_etymology_notes import (  # noqa: E402
    EtymologyChange,
    EtymologyEntry,
    EtymologyPlan,
    Repository,
    apply_plan,
    format_report,
    load_csv,
    normalize_note,
    parse_row,
    plan_etymology,
    MAX_NOTE_LENGTH,
)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeWord:
    def __init__(
        self,
        word_id: int,
        english_word: str,
        etymology: Optional[str] = None,
    ):
        self.id = word_id
        self.english_word = english_word
        self.etymology = etymology


class FakeRepository(Repository):
    def __init__(self, words: list):
        self._by_id = {w.id: w for w in words}
        self._by_name = {w.english_word.lower(): w for w in words}
        self._written: list = []

    def find_word_by_id(self, word_id: int) -> Optional[FakeWord]:
        return self._by_id.get(word_id)

    def find_word_by_name(self, english_word: str) -> Optional[FakeWord]:
        return self._by_name.get(english_word.lower())

    def set_etymology(self, word_id: int, note: str) -> None:
        w = self._by_id.get(word_id)
        if w is not None:
            w.etymology = note
            self._written.append((word_id, note))


def _make_repo(*words: tuple) -> FakeRepository:
    """words: (word_id, english_word, etymology_or_None)"""
    objs = [FakeWord(*w) for w in words]
    return FakeRepository(objs)


# ---------------------------------------------------------------------------
# normalize_note
# ---------------------------------------------------------------------------


class TestNormalizeNote:
    def test_plain_value_unchanged(self):
        val, err = normalize_note("From Latin 'verbum'")
        assert err is None
        assert val == "From Latin 'verbum'"

    def test_strips_whitespace(self):
        val, err = normalize_note("  From Latin  ")
        assert err is None
        assert val == "From Latin"

    def test_empty_string_returns_error(self):
        val, err = normalize_note("")
        assert val is None
        assert err is not None

    def test_whitespace_only_returns_error(self):
        val, err = normalize_note("   ")
        assert val is None
        assert err is not None

    def test_note_at_max_length_accepted(self):
        note = "x" * MAX_NOTE_LENGTH
        val, err = normalize_note(note)
        assert err is None
        assert val == note

    def test_note_over_max_length_rejected(self):
        note = "x" * (MAX_NOTE_LENGTH + 1)
        val, err = normalize_note(note)
        assert val is None
        assert err is not None
        assert "too long" in err

    def test_unicode_content_accepted(self):
        val, err = normalize_note("From Proto-Germanic *beuną")
        assert err is None
        assert "beuną" in val


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


class TestParseRow:
    def test_valid_row(self):
        entry, err = parse_row({"english_word": "be", "etymology": "Old English 'beon'"})
        assert err is None
        assert entry.english_word == "be"
        assert entry.note == "Old English 'beon'"
        assert entry.word_id is None

    def test_accepts_note_column_alias(self):
        entry, err = parse_row({"english_word": "go", "note": "Old English 'gan'"})
        assert err is None
        assert entry.note == "Old English 'gan'"

    def test_empty_word_returns_error(self):
        _, err = parse_row({"english_word": "", "etymology": "Old English 'beon'"})
        assert err is not None

    def test_missing_word_returns_error(self):
        _, err = parse_row({"etymology": "Old English 'beon'"})
        assert err is not None

    def test_empty_note_returns_error(self):
        _, err = parse_row({"english_word": "be", "etymology": ""})
        assert err is not None

    def test_too_long_note_returns_error(self):
        _, err = parse_row({"english_word": "be", "etymology": "x" * (MAX_NOTE_LENGTH + 1)})
        assert err is not None

    def test_word_id_parsed_when_present(self):
        entry, err = parse_row({"english_word": "be", "etymology": "Old English", "word_id": "42"})
        assert err is None
        assert entry.word_id == 42

    def test_empty_word_id_treated_as_none(self):
        entry, err = parse_row({"english_word": "be", "etymology": "Old English", "word_id": ""})
        assert err is None
        assert entry.word_id is None

    def test_invalid_word_id_returns_error(self):
        _, err = parse_row({"english_word": "be", "etymology": "Old English", "word_id": "abc"})
        assert err is not None

    def test_strips_whitespace_from_word(self):
        entry, err = parse_row({"english_word": "  run  ", "etymology": "Old English"})
        assert err is None
        assert entry.english_word == "run"

    def test_strips_whitespace_from_note(self):
        entry, err = parse_row({"english_word": "run", "etymology": "  Old English  "})
        assert err is None
        assert entry.note == "Old English"


# ---------------------------------------------------------------------------
# load_csv
# ---------------------------------------------------------------------------


class TestLoadCsv:
    def _write_csv(self, path: Path, rows: list, comment: str = "") -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            if comment:
                fh.write(f"# {comment}\n")
            writer = csv.DictWriter(fh, fieldnames=["english_word", "etymology"])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_loads_valid_csv(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        self._write_csv(csv_path, [
            {"english_word": "be", "etymology": "Old English 'beon'"},
            {"english_word": "go", "etymology": "Old English 'gan'"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 2

    def test_skips_comment_lines(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        csv_path.write_text(
            "# comment\nenglish_word,etymology\nhello,From Latin\n",
            encoding="utf-8",
        )
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1

    def test_missing_english_word_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        csv_path.write_text("etymology\nOld English\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "english_word" in errors[0]

    def test_missing_etymology_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        csv_path.write_text("english_word\nbe\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "etymology" in errors[0]

    def test_invalid_row_reported_not_halted(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        self._write_csv(csv_path, [
            {"english_word": "be", "etymology": "Old English"},
            {"english_word": "bad", "etymology": ""},
            {"english_word": "go", "etymology": "Old English"},
        ])
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert len(entries) == 2

    def test_duplicate_word_last_wins(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        self._write_csv(csv_path, [
            {"english_word": "go", "etymology": "First note"},
            {"english_word": "go", "etymology": "Second note"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1
        assert entries[0].note == "Second note"

    def test_file_not_found_reported(self, tmp_path: Path):
        _, errors = load_csv([tmp_path / "missing.csv"])
        assert len(errors) == 1

    def test_merges_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        self._write_csv(f1, [{"english_word": "be", "etymology": "Old English"}])
        self._write_csv(f2, [{"english_word": "go", "etymology": "Old Norse"}])
        entries, errors = load_csv([f1, f2])
        assert errors == []
        assert len(entries) == 2

    def test_whitespace_stripped_during_load(self, tmp_path: Path):
        csv_path = tmp_path / "etym.csv"
        self._write_csv(csv_path, [{"english_word": "be", "etymology": "  Old English  "}])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert entries[0].note == "Old English"


# ---------------------------------------------------------------------------
# plan_etymology
# ---------------------------------------------------------------------------


class TestPlanEtymology:
    def _entry(self, word: str, note: str, word_id: Optional[int] = None) -> EtymologyEntry:
        return EtymologyEntry(english_word=word, note=note, word_id=word_id)

    def test_sets_null_etymology(self):
        repo = _make_repo((1, "be", None))
        plan = plan_etymology([self._entry("be", "Old English 'beon'")], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].note == "Old English 'beon'"

    def test_noop_when_already_same_value(self):
        repo = _make_repo((1, "be", "Old English 'beon'"))
        plan = plan_etymology([self._entry("be", "Old English 'beon'")], repo, force=True)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 1

    def test_skips_existing_note_without_force(self):
        repo = _make_repo((1, "be", "Old English 'beon'"))
        plan = plan_etymology([self._entry("be", "Updated note")], repo, force=False)
        skips = [c for c in plan.changes if c.action == "skip_force"]
        assert len(skips) == 1

    def test_overwrites_existing_note_with_force(self):
        repo = _make_repo((1, "be", "Old English 'beon'"))
        plan = plan_etymology([self._entry("be", "Updated note")], repo, force=True)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].note == "Updated note"

    def test_skips_missing_word(self):
        repo = _make_repo()
        plan = plan_etymology([self._entry("unknown", "Some origin")], repo)
        skips = [c for c in plan.changes if c.action == "skip_no_match"]
        assert len(skips) == 1

    def test_case_insensitive_name_match(self):
        repo = _make_repo((1, "Hello", None))
        plan = plan_etymology([self._entry("hello", "Old English 'hál'")], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_word_id_takes_priority_over_name(self):
        repo = _make_repo((1, "be", None), (2, "go", None))
        plan = plan_etymology([self._entry("be", "Old Norse 'geta'", word_id=2)], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].word_id == 2

    def test_priority_tier_filter_skips_wrong_tier(self):
        repo = _make_repo((1, "hello", None))
        priority_map = {"hello": 2}
        plan = plan_etymology(
            [self._entry("hello", "Old English")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        skips = [c for c in plan.changes if c.action == "skip_tier"]
        assert len(skips) == 1

    def test_priority_tier_filter_allows_matching_tier(self):
        repo = _make_repo((1, "hello", None))
        priority_map = {"hello": 1}
        plan = plan_etymology(
            [self._entry("hello", "Old English")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_multiple_entries_mixed_states(self):
        repo = _make_repo(
            (1, "be", None),
            (2, "go", "Old English"),
            (3, "think", None),
        )
        entries = [
            self._entry("be", "Old English 'beon'"),
            self._entry("go", "Old English 'gan'"),
            self._entry("think", "Old English 'þencan'"),
        ]
        plan = plan_etymology(entries, repo, force=False)
        c = plan.counts
        assert c.get("set", 0) == 2        # be and think
        assert c.get("skip_force", 0) == 1  # go already has value


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_applies_set_changes(self):
        repo = _make_repo((1, "be", None), (2, "go", None))
        plan = EtymologyPlan(changes=[
            EtymologyChange(action="set", english_word="be", note="Old English", word_id=1),
            EtymologyChange(action="set", english_word="go", note="Old Norse", word_id=2),
        ])
        count = apply_plan(plan, repo)
        assert count == 2
        assert len(repo._written) == 2

    def test_skips_non_set_actions(self):
        repo = _make_repo((1, "be", "Old English"))
        plan = EtymologyPlan(changes=[
            EtymologyChange(action="noop", english_word="be", note="Old English", word_id=1),
            EtymologyChange(action="skip_force", english_word="be", note="Old English", word_id=1),
            EtymologyChange(action="skip_no_match", english_word="missing", note="x"),
        ])
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo._written == []

    def test_idempotent_second_run(self):
        repo = _make_repo((1, "be", None))
        entry = EtymologyEntry(english_word="be", note="Old English 'beon'")
        plan1 = plan_etymology([entry], repo)
        apply_plan(plan1, repo)
        # Second plan: word now has etymology set — same value → noop
        plan2 = plan_etymology([entry], repo, force=True)
        noops = [c for c in plan2.changes if c.action == "noop"]
        assert len(noops) == 1
        apply_plan(plan2, repo)
        # Written only once total
        assert len(repo._written) == 1

    def test_word_state_updated_in_memory(self):
        repo = _make_repo((1, "be", None))
        plan = EtymologyPlan(changes=[
            EtymologyChange(action="set", english_word="be", note="Old English", word_id=1),
        ])
        apply_plan(plan, repo)
        word = repo.find_word_by_id(1)
        assert word.etymology == "Old English"


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _plan(self, *changes) -> EtymologyPlan:
        return EtymologyPlan(changes=list(changes))

    def test_contains_title(self):
        plan = self._plan()
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "Etymology Notes Import Report" in report

    def test_dry_run_flag_visible(self):
        plan = self._plan()
        report = format_report(plan, dry_run=True, force=False, elapsed=0.1)
        assert "dry-run" in report

    def test_set_count_visible(self):
        plan = self._plan(
            EtymologyChange(action="set", english_word="be", note="Old English", word_id=1),
            EtymologyChange(action="set", english_word="go", note="Old Norse", word_id=2),
        )
        report = format_report(plan, dry_run=False, force=False, elapsed=0.5)
        assert "set" in report
        assert "2" in report

    def test_errors_listed(self):
        plan = self._plan()
        plan.errors = ["etym.csv[0]: empty etymology note"]
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "empty etymology note" in report

    def test_total_rows_written_shown(self):
        plan = self._plan(
            EtymologyChange(action="set", english_word="be", note="Old English", word_id=1),
        )
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "Total rows written: 1" in report

    def test_not_found_words_listed(self):
        plan = self._plan(
            EtymologyChange(action="skip_no_match", english_word="xyzzy", note="Unknown origin"),
        )
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "xyzzy" in report

    def test_live_mode_label(self):
        plan = self._plan()
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "live" in report


# ---------------------------------------------------------------------------
# Integration: real CSV file
# ---------------------------------------------------------------------------


class TestRealCsvFile:
    def test_real_csv_loads_without_errors(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "etymology_notes.csv"
        if not csv_path.exists():
            pytest.skip("etymology_notes.csv not present")
        entries, errors = load_csv([csv_path])
        assert errors == [], f"Unexpected load errors: {errors}"
        assert len(entries) > 0

    def test_all_notes_within_length_limit(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "etymology_notes.csv"
        if not csv_path.exists():
            pytest.skip("etymology_notes.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert len(e.note) <= MAX_NOTE_LENGTH, (
                f"Note too long for {e.english_word!r}: {len(e.note)} chars"
            )

    def test_all_english_words_are_non_empty(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "etymology_notes.csv"
        if not csv_path.exists():
            pytest.skip("etymology_notes.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert e.english_word.strip(), "Empty english_word in CSV"

    def test_real_csv_has_common_words(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "etymology_notes.csv"
        if not csv_path.exists():
            pytest.skip("etymology_notes.csv not present")
        entries, _ = load_csv([csv_path])
        words = {e.english_word.lower() for e in entries}
        assert "be" in words
        assert "have" in words

    def test_real_csv_covers_multiple_origins(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "etymology_notes.csv"
        if not csv_path.exists():
            pytest.skip("etymology_notes.csv not present")
        entries, _ = load_csv([csv_path])
        notes_lower = " ".join(e.note.lower() for e in entries)
        assert "latin" in notes_lower or "old english" in notes_lower or "greek" in notes_lower

    def test_no_duplicate_words_in_csv(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "etymology_notes.csv"
        if not csv_path.exists():
            pytest.skip("etymology_notes.csv not present")
        entries, _ = load_csv([csv_path])
        words = [e.english_word.lower() for e in entries]
        assert len(words) == len(set(words)), "Duplicate words found in CSV"


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from import_etymology_notes import main
        assert main(["--no-db"]) == 0
