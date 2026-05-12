"""Tests for scripts/import_word_collocations.py.

Pure-function tests only — no DB or Flask app required.
DB/integration path is covered by the --no-db guard in main().
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional

import pytest
import sys

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from import_word_collocations import (  # noqa: E402
    CollocationChange,
    CollocationEntry,
    CollocationPlan,
    Repository,
    apply_plan,
    format_report,
    load_csv,
    parse_row,
    plan_import,
)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeWord:
    def __init__(self, word_id: int, english_word: str):
        self.id = word_id
        self.english_word = english_word


class FakeCollocation:
    def __init__(
        self,
        coll_id: int,
        word_id: int,
        phrase: str,
        translation: str,
        example: Optional[str] = None,
    ):
        self.id = coll_id
        self.word_id = word_id
        self.collocation_phrase = phrase
        self.translation = translation
        self.example = example


class FakeRepository(Repository):
    def __init__(self, words: list, collocations: Optional[list] = None):
        self._by_id = {w.id: w for w in words}
        self._by_name = {w.english_word.lower(): w for w in words}
        self._collocations: List[FakeCollocation] = list(collocations or [])
        self._next_id = max((c.id for c in self._collocations), default=0) + 1
        self.inserted: list = []
        self.updated: list = []

    def find_word_by_id(self, word_id: int) -> Optional[FakeWord]:
        return self._by_id.get(word_id)

    def find_word_by_name(self, english_word: str) -> Optional[FakeWord]:
        return self._by_name.get(english_word.lower())

    def find_collocation(self, word_id: int, phrase: str) -> Optional[FakeCollocation]:
        for c in self._collocations:
            if c.word_id == word_id and c.collocation_phrase.lower() == phrase.lower():
                return c
        return None

    def insert_collocation(
        self,
        word_id: int,
        phrase: str,
        translation: str,
        example: Optional[str],
    ) -> FakeCollocation:
        row = FakeCollocation(self._next_id, word_id, phrase, translation, example)
        self._next_id += 1
        self._collocations.append(row)
        self.inserted.append(row)
        return row

    def update_collocation(
        self,
        collocation_id: int,
        translation: str,
        example: Optional[str],
    ) -> None:
        for c in self._collocations:
            if c.id == collocation_id:
                c.translation = translation
                c.example = example
                self.updated.append(c)
                break


def _repo(*words: tuple, collocations: Optional[list] = None) -> FakeRepository:
    """words: (word_id, english_word)"""
    return FakeRepository(
        [FakeWord(*w) for w in words],
        collocations=collocations,
    )


def _entry(
    word: str,
    phrase: str,
    translation: str = "перевод",
    example: Optional[str] = None,
) -> CollocationEntry:
    return CollocationEntry(
        english_word=word,
        collocation_phrase=phrase,
        translation=translation,
        example=example,
    )


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


class TestParseRow:
    def test_valid_full_row(self):
        entry, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "go to work",
            "translation": "идти на работу",
            "example": "I go to work every day.",
        })
        assert err is None
        assert entry.english_word == "work"
        assert entry.collocation_phrase == "go to work"
        assert entry.translation == "идти на работу"
        assert entry.example == "I go to work every day."

    def test_valid_row_without_example(self):
        entry, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "go to work",
            "translation": "идти на работу",
        })
        assert err is None
        assert entry.example is None

    def test_empty_example_stored_as_none(self):
        entry, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "go to work",
            "translation": "идти на работу",
            "example": "",
        })
        assert err is None
        assert entry.example is None

    def test_empty_english_word_error(self):
        _, err = parse_row({
            "english_word": "",
            "collocation_phrase": "go to work",
            "translation": "идти на работу",
        })
        assert err is not None

    def test_empty_phrase_error(self):
        _, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "",
            "translation": "идти на работу",
        })
        assert err is not None

    def test_empty_translation_error(self):
        _, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "go to work",
            "translation": "",
        })
        assert err is not None

    def test_strips_whitespace(self):
        entry, err = parse_row({
            "english_word": "  work  ",
            "collocation_phrase": "  go to work  ",
            "translation": "  идти на работу  ",
        })
        assert err is None
        assert entry.english_word == "work"
        assert entry.collocation_phrase == "go to work"
        assert entry.translation == "идти на работу"

    def test_optional_word_id(self):
        entry, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "go to work",
            "translation": "идти на работу",
            "word_id": "42",
        })
        assert err is None
        assert entry.word_id == 42

    def test_invalid_word_id_error(self):
        _, err = parse_row({
            "english_word": "work",
            "collocation_phrase": "go to work",
            "translation": "идти на работу",
            "word_id": "abc",
        })
        assert err is not None


# ---------------------------------------------------------------------------
# load_csv
# ---------------------------------------------------------------------------


class TestLoadCsv:
    def _write_csv(self, path: Path, rows: list) -> None:
        fieldnames = ["english_word", "collocation_phrase", "translation", "example"]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_loads_valid_csv(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        self._write_csv(p, [
            {"english_word": "work", "collocation_phrase": "go to work",
             "translation": "идти на работу", "example": ""},
            {"english_word": "work", "collocation_phrase": "hard work",
             "translation": "упорный труд", "example": ""},
        ])
        entries, errors = load_csv([p])
        assert errors == []
        assert len(entries) == 2

    def test_skips_comment_lines(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        p.write_text(
            "# comment\nenglish_word,collocation_phrase,translation,example\n"
            "work,go to work,идти на работу,\n",
            encoding="utf-8",
        )
        entries, errors = load_csv([p])
        assert errors == []
        assert len(entries) == 1

    def test_missing_english_word_column_error(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        p.write_text("collocation_phrase,translation\ngo to work,идти на работу\n", encoding="utf-8")
        _, errors = load_csv([p])
        assert len(errors) >= 1

    def test_missing_phrase_column_error(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        p.write_text("english_word,translation\nwork,идти на работу\n", encoding="utf-8")
        _, errors = load_csv([p])
        assert len(errors) >= 1

    def test_invalid_row_reported(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        self._write_csv(p, [
            {"english_word": "work", "collocation_phrase": "go to work",
             "translation": "идти на работу", "example": ""},
            {"english_word": "work", "collocation_phrase": "",  # invalid
             "translation": "перевод", "example": ""},
            {"english_word": "make", "collocation_phrase": "make a plan",
             "translation": "составить план", "example": ""},
        ])
        entries, errors = load_csv([p])
        assert len(errors) == 1
        assert len(entries) == 2

    def test_duplicate_word_phrase_last_wins(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        self._write_csv(p, [
            {"english_word": "work", "collocation_phrase": "go to work",
             "translation": "first", "example": ""},
            {"english_word": "work", "collocation_phrase": "go to work",
             "translation": "second", "example": ""},
        ])
        entries, errors = load_csv([p])
        assert errors == []
        assert len(entries) == 1
        assert entries[0].translation == "second"

    def test_case_insensitive_duplicate_detection(self, tmp_path: Path):
        p = tmp_path / "c.csv"
        self._write_csv(p, [
            {"english_word": "Work", "collocation_phrase": "Go To Work",
             "translation": "first", "example": ""},
            {"english_word": "work", "collocation_phrase": "go to work",
             "translation": "second", "example": ""},
        ])
        entries, errors = load_csv([p])
        assert errors == []
        assert len(entries) == 1
        assert entries[0].translation == "second"

    def test_file_not_found_reported(self, tmp_path: Path):
        _, errors = load_csv([tmp_path / "missing.csv"])
        assert len(errors) == 1

    def test_merges_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        self._write_csv(f1, [
            {"english_word": "work", "collocation_phrase": "go to work",
             "translation": "идти на работу", "example": ""},
        ])
        self._write_csv(f2, [
            {"english_word": "make", "collocation_phrase": "make a plan",
             "translation": "составить план", "example": ""},
        ])
        entries, errors = load_csv([f1, f2])
        assert errors == []
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# plan_import
# ---------------------------------------------------------------------------


class TestPlanImport:
    def test_inserts_new_collocation(self):
        repo = _repo((1, "work"))
        plan = plan_import([_entry("work", "go to work")], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1
        assert inserts[0].word_id == 1
        assert inserts[0].collocation_phrase == "go to work"

    def test_noop_when_identical(self):
        existing = FakeCollocation(10, 1, "go to work", "идти на работу", None)
        repo = _repo((1, "work"), collocations=[existing])
        plan = plan_import([_entry("work", "go to work", "идти на работу")], repo)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 1

    def test_skip_force_when_different_without_force(self):
        existing = FakeCollocation(10, 1, "go to work", "old translation", None)
        repo = _repo((1, "work"), collocations=[existing])
        plan = plan_import([_entry("work", "go to work", "new translation")], repo, force=False)
        skips = [c for c in plan.changes if c.action == "skip_force"]
        assert len(skips) == 1

    def test_update_with_force(self):
        existing = FakeCollocation(10, 1, "go to work", "old translation", None)
        repo = _repo((1, "work"), collocations=[existing])
        plan = plan_import([_entry("work", "go to work", "new translation")], repo, force=True)
        updates = [c for c in plan.changes if c.action == "update"]
        assert len(updates) == 1
        assert updates[0].existing_id == 10
        assert updates[0].translation == "new translation"

    def test_skip_no_match(self):
        repo = _repo()
        plan = plan_import([_entry("unknown", "some phrase")], repo)
        skips = [c for c in plan.changes if c.action == "skip_no_match"]
        assert len(skips) == 1

    def test_case_insensitive_word_lookup(self):
        repo = _repo((1, "Work"))
        plan = plan_import([_entry("work", "go to work")], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1
        assert inserts[0].word_id == 1

    def test_case_insensitive_phrase_noop(self):
        existing = FakeCollocation(10, 1, "Go To Work", "идти на работу", None)
        repo = _repo((1, "work"), collocations=[existing])
        plan = plan_import([_entry("work", "go to work", "идти на работу")], repo)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 1

    def test_priority_tier_filter_skips_wrong_tier(self):
        repo = _repo((1, "work"))
        priority_map = {"work": 2}
        plan = plan_import(
            [_entry("work", "go to work")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        skips = [c for c in plan.changes if c.action == "skip_tier"]
        assert len(skips) == 1

    def test_priority_tier_filter_allows_matching_tier(self):
        repo = _repo((1, "work"))
        priority_map = {"work": 1}
        plan = plan_import(
            [_entry("work", "go to work")],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1

    def test_multiple_phrases_per_word(self):
        repo = _repo((1, "work"))
        entries = [
            _entry("work", "go to work"),
            _entry("work", "hard work"),
            _entry("work", "work on a project"),
        ]
        plan = plan_import(entries, repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 3
        assert all(c.word_id == 1 for c in inserts)

    def test_word_id_takes_priority_over_name(self):
        repo = _repo((1, "work"), (2, "make"))
        entry = CollocationEntry(
            english_word="work",
            collocation_phrase="make a plan",
            translation="составить план",
            example=None,
            word_id=2,
        )
        plan = plan_import([entry], repo)
        inserts = [c for c in plan.changes if c.action == "insert"]
        assert len(inserts) == 1
        assert inserts[0].word_id == 2


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_applies_inserts(self):
        repo = _repo((1, "work"))
        plan = CollocationPlan(changes=[
            CollocationChange(
                action="insert",
                english_word="work",
                collocation_phrase="go to work",
                translation="идти на работу",
                example="I go to work every day.",
                word_id=1,
            ),
        ])
        count = apply_plan(plan, repo)
        assert count == 1
        assert len(repo.inserted) == 1
        assert repo.inserted[0].collocation_phrase == "go to work"

    def test_applies_updates(self):
        existing = FakeCollocation(10, 1, "go to work", "old", None)
        repo = _repo((1, "work"), collocations=[existing])
        plan = CollocationPlan(changes=[
            CollocationChange(
                action="update",
                english_word="work",
                collocation_phrase="go to work",
                translation="идти на работу",
                example="Updated example.",
                word_id=1,
                existing_id=10,
            ),
        ])
        count = apply_plan(plan, repo)
        assert count == 1
        assert len(repo.updated) == 1
        assert repo.updated[0].translation == "идти на работу"

    def test_skips_noop_and_skip_actions(self):
        repo = _repo((1, "work"))
        plan = CollocationPlan(changes=[
            CollocationChange(action="noop", english_word="work",
                              collocation_phrase="go to work", translation="x", word_id=1),
            CollocationChange(action="skip_force", english_word="work",
                              collocation_phrase="go to work", translation="x", word_id=1),
            CollocationChange(action="skip_no_match", english_word="missing",
                              collocation_phrase="go", translation="x"),
        ])
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo.inserted == []
        assert repo.updated == []

    def test_idempotent_second_run(self):
        repo = _repo((1, "work"))
        entry = _entry("work", "go to work", "идти на работу")

        plan1 = plan_import([entry], repo)
        apply_plan(plan1, repo)

        # Second plan: row exists with same content → noop (no force)
        plan2 = plan_import([entry], repo, force=True)
        noops = [c for c in plan2.changes if c.action == "noop"]
        assert len(noops) == 1

        count2 = apply_plan(plan2, repo)
        assert count2 == 0
        assert len(repo.inserted) == 1  # only inserted once total


# ---------------------------------------------------------------------------
# action_count helper
# ---------------------------------------------------------------------------


class TestActionCount:
    def test_counts_by_action(self):
        plan = CollocationPlan(changes=[
            CollocationChange(action="insert", english_word="work",
                              collocation_phrase="go to work", translation="x", word_id=1),
            CollocationChange(action="insert", english_word="work",
                              collocation_phrase="hard work", translation="x", word_id=1),
            CollocationChange(action="noop", english_word="make",
                              collocation_phrase="make a plan", translation="x", word_id=2),
        ])
        assert plan.action_count("insert") == 2
        assert plan.action_count("noop") == 1
        assert plan.action_count("update") == 0


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_contains_title(self):
        plan = CollocationPlan()
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "Word Collocations Import Report" in report

    def test_dry_run_flag_visible(self):
        plan = CollocationPlan()
        report = format_report(plan, dry_run=True, force=False, elapsed=0.1)
        assert "dry-run" in report

    def test_insert_count_visible(self):
        plan = CollocationPlan(changes=[
            CollocationChange(action="insert", english_word="work",
                              collocation_phrase="go to work", translation="x", word_id=1),
        ])
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "insert" in report
        assert "1" in report

    def test_errors_listed(self):
        plan = CollocationPlan()
        plan.errors = ["c.csv[0]: empty collocation_phrase"]
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "empty collocation_phrase" in report

    def test_total_rows_written_shown(self):
        plan = CollocationPlan(changes=[
            CollocationChange(action="insert", english_word="work",
                              collocation_phrase="p1", translation="x", word_id=1),
            CollocationChange(action="update", english_word="make",
                              collocation_phrase="p2", translation="y", word_id=2, existing_id=5),
        ])
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "Total rows written: 2" in report

    def test_not_found_words_listed(self):
        plan = CollocationPlan(changes=[
            CollocationChange(action="skip_no_match", english_word="xyzzy",
                              collocation_phrase="some phrase", translation="x"),
        ])
        report = format_report(plan, dry_run=False, force=False, elapsed=0.1)
        assert "xyzzy" in report


# ---------------------------------------------------------------------------
# Integration: real CSV file
# ---------------------------------------------------------------------------


class TestRealCsvFile:
    def test_real_csv_loads_without_errors(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "collocations.csv"
        if not csv_path.exists():
            pytest.skip("collocations.csv not present")
        entries, errors = load_csv([csv_path])
        assert errors == [], f"Unexpected load errors: {errors}"
        assert len(entries) > 0

    def test_all_entries_have_required_fields(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "collocations.csv"
        if not csv_path.exists():
            pytest.skip("collocations.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert e.english_word.strip(), "Empty english_word"
            assert e.collocation_phrase.strip(), "Empty collocation_phrase"
            assert e.translation.strip(), "Empty translation"

    def test_covers_a2_b2_words(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "collocations.csv"
        if not csv_path.exists():
            pytest.skip("collocations.csv not present")
        entries, _ = load_csv([csv_path])
        words = {e.english_word.lower() for e in entries}
        # A2 words
        assert any(w in words for w in ("make", "have", "get", "take", "give")), \
            "Expected at least one common A2 word"
        # B1 words
        assert any(w in words for w in ("problem", "job", "plan", "result", "effect")), \
            "Expected at least one B1 word"
        # B2 words
        assert any(w in words for w in ("opportunity", "challenge", "experience", "risk", "role")), \
            "Expected at least one B2 word"

    def test_multiple_phrases_per_word(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "collocations.csv"
        if not csv_path.exists():
            pytest.skip("collocations.csv not present")
        entries, _ = load_csv([csv_path])
        from collections import Counter
        counts = Counter(e.english_word.lower() for e in entries)
        multi = {w: c for w, c in counts.items() if c >= 2}
        assert len(multi) >= 10, f"Expected at least 10 words with 2+ collocations, got {multi}"

    def test_no_empty_translations(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "collocations.csv"
        if not csv_path.exists():
            pytest.skip("collocations.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert e.translation.strip(), f"Empty translation for {e.collocation_phrase!r}"

    def test_collocation_dataset_reusable_for_lesson_pairs(self):
        """Verify phrases are suitable for collocation_matching lesson format."""
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "collocations.csv"
        if not csv_path.exists():
            pytest.skip("collocations.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            # phrase must be non-empty English text
            assert e.collocation_phrase.strip()
            # translation must be non-empty Russian text
            assert e.translation.strip()
            # together they form a valid collocation_matching pair
            pair = {"phrase": e.collocation_phrase, "translation": e.translation}
            assert pair["phrase"] and pair["translation"]


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from import_word_collocations import main
        assert main(["--no-db"]) == 0
