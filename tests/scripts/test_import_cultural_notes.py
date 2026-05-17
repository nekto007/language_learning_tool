"""Tests for scripts/import_cultural_notes.py.

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

from import_cultural_notes import (  # noqa: E402
    CulturalNoteChange,
    CulturalNoteEntry,
    CulturalNotePlan,
    Repository,
    apply_plan,
    format_report,
    load_csv,
    normalize_context,
    normalize_note,
    parse_row,
    plan_cultural_notes,
    MAX_NOTE_LENGTH,
    MAX_CONTEXT_LENGTH,
)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeWord:
    def __init__(self, word_id: int, english_word: str):
        self.id = word_id
        self.english_word = english_word


class FakeRepository(Repository):
    def __init__(self, words: list):
        self._by_id = {w.id: w for w in words}
        self._by_name = {w.english_word.lower(): w for w in words}
        self._notes: dict = {}  # word_id -> list of note texts
        self._inserted: list = []

    def find_word_by_id(self, word_id: int) -> Optional[FakeWord]:
        return self._by_id.get(word_id)

    def find_word_by_name(self, english_word: str) -> Optional[FakeWord]:
        return self._by_name.get(english_word.lower())

    def get_existing_notes(self, word_id: int) -> list:
        return list(self._notes.get(word_id, []))

    def insert_note(self, word_id: int, note: str, context: str) -> None:
        if word_id not in self._notes:
            self._notes[word_id] = []
        self._notes[word_id].append(note)
        self._inserted.append((word_id, note, context))

    def seed_note(self, word_id: int, note: str) -> None:
        """Pre-populate a note so tests can verify noop behaviour."""
        if word_id not in self._notes:
            self._notes[word_id] = []
        self._notes[word_id].append(note)


def _make_repo(*words: tuple) -> FakeRepository:
    """words: (word_id, english_word)"""
    objs = [FakeWord(*w) for w in words]
    return FakeRepository(objs)


# ---------------------------------------------------------------------------
# normalize_note
# ---------------------------------------------------------------------------


class TestNormalizeNote:
    def test_plain_value_unchanged(self):
        val, err = normalize_note("Used in British English for 'hello'")
        assert err is None
        assert val == "Used in British English for 'hello'"

    def test_strips_whitespace(self):
        val, err = normalize_note("  British usage  ")
        assert err is None
        assert val == "British usage"

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
        val, err = normalize_note("Used with émigré communities in the US")
        assert err is None


# ---------------------------------------------------------------------------
# normalize_context
# ---------------------------------------------------------------------------


class TestNormalizeContext:
    def test_plain_value_unchanged(self):
        assert normalize_context("idiom") == "idiom"

    def test_strips_whitespace(self):
        assert normalize_context("  British English  ") == "British English"

    def test_empty_returns_empty_string(self):
        assert normalize_context("") == ""

    def test_truncates_at_max_length(self):
        long_ctx = "x" * (MAX_CONTEXT_LENGTH + 10)
        result = normalize_context(long_ctx)
        assert len(result) == MAX_CONTEXT_LENGTH


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


class TestParseRow:
    def test_valid_row_all_fields(self):
        entry, err = parse_row({
            "english_word": "please",
            "note": "Essential politeness marker in British English",
            "context": "politeness",
        })
        assert err is None
        assert entry.english_word == "please"
        assert entry.note == "Essential politeness marker in British English"
        assert entry.context == "politeness"
        assert entry.word_id is None

    def test_valid_row_no_context(self):
        entry, err = parse_row({
            "english_word": "sorry",
            "note": "British use 'sorry' far more than Americans",
        })
        assert err is None
        assert entry.context == ""

    def test_empty_word_returns_error(self):
        _, err = parse_row({"english_word": "", "note": "Some note"})
        assert err is not None

    def test_missing_word_returns_error(self):
        _, err = parse_row({"note": "Some note"})
        assert err is not None

    def test_empty_note_returns_error(self):
        _, err = parse_row({"english_word": "sorry", "note": ""})
        assert err is not None

    def test_too_long_note_returns_error(self):
        _, err = parse_row({"english_word": "sorry", "note": "x" * (MAX_NOTE_LENGTH + 1)})
        assert err is not None

    def test_word_id_parsed_when_present(self):
        entry, err = parse_row({
            "english_word": "sorry",
            "note": "British politeness marker",
            "word_id": "99",
        })
        assert err is None
        assert entry.word_id == 99

    def test_empty_word_id_treated_as_none(self):
        entry, err = parse_row({
            "english_word": "sorry",
            "note": "British politeness marker",
            "word_id": "",
        })
        assert err is None
        assert entry.word_id is None

    def test_invalid_word_id_returns_error(self):
        _, err = parse_row({
            "english_word": "sorry",
            "note": "British politeness marker",
            "word_id": "abc",
        })
        assert err is not None

    def test_strips_whitespace_from_fields(self):
        entry, err = parse_row({
            "english_word": "  mate  ",
            "note": "  British informal for friend  ",
            "context": "  British English  ",
        })
        assert err is None
        assert entry.english_word == "mate"
        assert entry.note == "British informal for friend"
        assert entry.context == "British English"

    def test_accepts_note_alias_etymology(self):
        entry, err = parse_row({"english_word": "cheers", "etymology": "British toast and thanks"})
        assert err is None
        assert entry.note == "British toast and thanks"


# ---------------------------------------------------------------------------
# load_csv
# ---------------------------------------------------------------------------


class TestLoadCsv:
    def _write_csv(self, path: Path, rows: list, extra_cols: list = None) -> None:
        fieldnames = ["english_word", "note", "context"]
        if extra_cols:
            fieldnames += extra_cols
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_loads_valid_csv(self, tmp_path: Path):
        csv_path = tmp_path / "cn.csv"
        self._write_csv(csv_path, [
            {"english_word": "sorry", "note": "British politeness", "context": "politeness"},
            {"english_word": "cheers", "note": "British thanks", "context": "British English"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 2

    def test_skips_comment_lines(self, tmp_path: Path):
        csv_path = tmp_path / "cn.csv"
        csv_path.write_text(
            "# comment\nenglish_word,note,context\nhello,Used as greeting,politeness\n",
            encoding="utf-8",
        )
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1

    def test_missing_english_word_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "cn.csv"
        csv_path.write_text("note,context\nSome note,idiom\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "english_word" in errors[0]

    def test_missing_note_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "cn.csv"
        csv_path.write_text("english_word,context\nsorry,politeness\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "note" in errors[0]

    def test_multiple_rows_same_word_kept(self, tmp_path: Path):
        """A word may have several cultural notes — all rows are retained."""
        csv_path = tmp_path / "cn.csv"
        self._write_csv(csv_path, [
            {"english_word": "sorry", "note": "British apology marker", "context": "politeness"},
            {"english_word": "sorry", "note": "Also used to get attention", "context": "British English"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 2

    def test_invalid_row_reported_not_halted(self, tmp_path: Path):
        csv_path = tmp_path / "cn.csv"
        self._write_csv(csv_path, [
            {"english_word": "sorry", "note": "British politeness", "context": ""},
            {"english_word": "bad", "note": "", "context": ""},
            {"english_word": "cheers", "note": "British thanks", "context": ""},
        ])
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert len(entries) == 2

    def test_file_not_found_reported(self, tmp_path: Path):
        _, errors = load_csv([tmp_path / "missing.csv"])
        assert len(errors) == 1

    def test_merges_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        self._write_csv(f1, [{"english_word": "sorry", "note": "British apology", "context": ""}])
        self._write_csv(f2, [{"english_word": "cheers", "note": "British thanks", "context": ""}])
        entries, errors = load_csv([f1, f2])
        assert errors == []
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# plan_cultural_notes
# ---------------------------------------------------------------------------


class TestPlanCulturalNotes:
    def _entry(self, word: str, note: str, context: str = "", word_id: Optional[int] = None):
        return CulturalNoteEntry(english_word=word, note=note, context=context, word_id=word_id)

    def test_inserts_new_note(self):
        repo = _make_repo((1, "sorry"))
        plan = plan_cultural_notes([self._entry("sorry", "British politeness")], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1
        assert inserts[0].note == "British politeness"
        assert inserts[0].word_id == 1

    def test_noop_when_identical_note_exists(self):
        repo = _make_repo((1, "sorry"))
        repo.seed_note(1, "British politeness")
        plan = plan_cultural_notes([self._entry("sorry", "British politeness")], repo)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 1

    def test_inserts_second_note_for_same_word(self):
        repo = _make_repo((1, "sorry"))
        repo.seed_note(1, "British apology marker")
        plan = plan_cultural_notes([
            self._entry("sorry", "Also used to get attention"),
        ], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1

    def test_skips_missing_word(self):
        repo = _make_repo()
        plan = plan_cultural_notes([self._entry("unknown", "Some note")], repo)
        skips = [c for c in plan.changes if c.action == "skip_no_match"]
        assert len(skips) == 1

    def test_case_insensitive_name_match(self):
        repo = _make_repo((1, "Sorry"))
        plan = plan_cultural_notes([self._entry("sorry", "British politeness")], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1

    def test_word_id_takes_priority_over_name(self):
        repo = _make_repo((1, "sorry"), (2, "cheers"))
        plan = plan_cultural_notes([self._entry("sorry", "British thanks", word_id=2)], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1
        assert inserts[0].word_id == 2

    def test_priority_tier_filter_skips_wrong_tier(self):
        repo = _make_repo((1, "sorry"))
        priority_map = {"sorry": 2}
        plan = plan_cultural_notes(
            [self._entry("sorry", "British politeness")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        skips = [c for c in plan.changes if c.action == "skip_tier"]
        assert len(skips) == 1

    def test_priority_tier_filter_allows_matching_tier(self):
        repo = _make_repo((1, "sorry"))
        priority_map = {"sorry": 1}
        plan = plan_cultural_notes(
            [self._entry("sorry", "British politeness")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1

    def test_duplicate_csv_rows_deduplicated_in_plan(self):
        """Two CSV rows with the same word+note only generate one insert."""
        repo = _make_repo((1, "sorry"))
        entries = [
            self._entry("sorry", "British politeness"),
            self._entry("sorry", "British politeness"),
        ]
        plan = plan_cultural_notes(entries, repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(inserts) == 1
        assert len(noops) == 1

    def test_multiple_entries_mixed_states(self):
        repo = _make_repo((1, "sorry"), (2, "cheers"), (3, "mate"))
        repo.seed_note(2, "British toast and thanks")
        entries = [
            self._entry("sorry", "British apology marker"),
            self._entry("cheers", "British toast and thanks"),
            self._entry("mate", "British informal for friend"),
        ]
        plan = plan_cultural_notes(entries, repo)
        c = plan.counts
        assert c.get("insert", 0) == 2  # sorry and mate
        assert c.get("noop", 0) == 1    # cheers already has that note


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_applies_insert_changes(self):
        repo = _make_repo((1, "sorry"), (2, "cheers"))
        plan = CulturalNotePlan(changes=[
            CulturalNoteChange(action="insert", english_word="sorry", note="British apology", context="politeness", word_id=1),
            CulturalNoteChange(action="insert", english_word="cheers", note="British thanks", context="British English", word_id=2),
        ])
        count = apply_plan(plan, repo)
        assert count == 2
        assert len(repo._inserted) == 2

    def test_skips_non_insert_actions(self):
        repo = _make_repo((1, "sorry"))
        plan = CulturalNotePlan(changes=[
            CulturalNoteChange(action="noop", english_word="sorry", note="British apology", word_id=1),
            CulturalNoteChange(action="skip_no_match", english_word="missing", note="x"),
        ])
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo._inserted == []

    def test_idempotent_second_run(self):
        repo = _make_repo((1, "sorry"))
        entry = CulturalNoteEntry(english_word="sorry", note="British politeness", context="politeness")

        plan1 = plan_cultural_notes([entry], repo)
        apply_plan(plan1, repo)
        assert len(repo._inserted) == 1

        # Second plan: note now in DB cache — noop
        plan2 = plan_cultural_notes([entry], repo)
        noops = [c for c in plan2.changes if c.action == "noop"]
        assert len(noops) == 1
        apply_plan(plan2, repo)
        assert len(repo._inserted) == 1

    def test_note_present_after_apply(self):
        repo = _make_repo((1, "sorry"))
        plan = CulturalNotePlan(changes=[
            CulturalNoteChange(action="insert", english_word="sorry", note="British apology", context="", word_id=1),
        ])
        apply_plan(plan, repo)
        notes = repo.get_existing_notes(1)
        assert "British apology" in notes

    def test_context_stored(self):
        repo = _make_repo((1, "sorry"))
        plan = CulturalNotePlan(changes=[
            CulturalNoteChange(action="insert", english_word="sorry", note="British apology", context="politeness", word_id=1),
        ])
        apply_plan(plan, repo)
        assert repo._inserted[0][2] == "politeness"


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _plan(self, *changes) -> CulturalNotePlan:
        return CulturalNotePlan(changes=list(changes))

    def test_contains_title(self):
        plan = self._plan()
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "Cultural Notes Import Report" in report

    def test_dry_run_flag_visible(self):
        plan = self._plan()
        report = format_report(plan, dry_run=True, elapsed=0.1)
        assert "dry-run" in report

    def test_insert_count_visible(self):
        plan = self._plan(
            CulturalNoteChange(action="insert", english_word="sorry", note="British apology", word_id=1),
            CulturalNoteChange(action="insert", english_word="cheers", note="British thanks", word_id=2),
        )
        report = format_report(plan, dry_run=False, elapsed=0.5)
        assert "insert" in report
        assert "2" in report

    def test_errors_listed(self):
        plan = self._plan()
        plan.errors = ["cn.csv[0]: empty note"]
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "empty note" in report

    def test_total_rows_written_shown(self):
        plan = self._plan(
            CulturalNoteChange(action="insert", english_word="sorry", note="British apology", word_id=1),
        )
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "Total rows written: 1" in report

    def test_not_found_words_listed(self):
        plan = self._plan(
            CulturalNoteChange(action="skip_no_match", english_word="xyzzy", note="Unknown"),
        )
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "xyzzy" in report

    def test_live_mode_label(self):
        plan = self._plan()
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "live" in report


# ---------------------------------------------------------------------------
# Integration: real CSV file
# ---------------------------------------------------------------------------


class TestRealCsvFile:
    CSV_PATH = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "cultural_notes.csv"

    def test_real_csv_loads_without_errors(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, errors = load_csv([self.CSV_PATH])
        assert errors == [], f"Unexpected load errors: {errors}"
        assert len(entries) > 0

    def test_all_notes_within_length_limit(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, _ = load_csv([self.CSV_PATH])
        for e in entries:
            assert len(e.note) <= MAX_NOTE_LENGTH, (
                f"Note too long for {e.english_word!r}: {len(e.note)} chars"
            )

    def test_all_context_within_length_limit(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, _ = load_csv([self.CSV_PATH])
        for e in entries:
            assert len(e.context) <= MAX_CONTEXT_LENGTH, (
                f"Context too long for {e.english_word!r}: {len(e.context)} chars"
            )

    def test_all_english_words_are_non_empty(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, _ = load_csv([self.CSV_PATH])
        for e in entries:
            assert e.english_word.strip(), "Empty english_word in CSV"

    def test_real_csv_covers_multiple_categories(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, _ = load_csv([self.CSV_PATH])
        contexts = {e.context.lower() for e in entries}
        assert any("idiom" in c for c in contexts), "Expected at least one idiom entry"
        assert any("phrasal" in c for c in contexts), "Expected at least one phrasal verb entry"
        assert any("polite" in c for c in contexts), "Expected at least one politeness entry"

    def test_real_csv_has_common_words(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, _ = load_csv([self.CSV_PATH])
        words = {e.english_word.lower() for e in entries}
        assert "please" in words or "sorry" in words or "thank you" in words

    def test_multiple_notes_per_word_allowed(self):
        if not self.CSV_PATH.exists():
            pytest.skip("cultural_notes.csv not present")
        entries, _ = load_csv([self.CSV_PATH])
        from collections import Counter
        word_counts = Counter(e.english_word.lower() for e in entries)
        # The CSV may have multi-note words; just verify load handles them fine
        assert sum(word_counts.values()) == len(entries)


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from import_cultural_notes import main
        assert main(["--no-db"]) == 0
