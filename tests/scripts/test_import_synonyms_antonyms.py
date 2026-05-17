"""Tests for scripts/import_synonyms_antonyms.py.

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

from import_synonyms_antonyms import (  # noqa: E402
    FieldChange,
    Repository,
    SynAntEntry,
    SynAntPlan,
    apply_plan,
    format_report,
    load_csv,
    parse_row,
    parse_word_list,
    plan_import,
)


# ---------------------------------------------------------------------------
# Fake repository for unit tests
# ---------------------------------------------------------------------------


class FakeWord:
    def __init__(
        self,
        word_id: int,
        english_word: str,
        synonyms: Optional[List[str]] = None,
        antonyms: Optional[List[str]] = None,
    ):
        self.id = word_id
        self.english_word = english_word
        self.synonyms = synonyms
        self.antonyms = antonyms


class FakeRepository(Repository):
    def __init__(self, words: list):
        self._by_id = {w.id: w for w in words}
        self._by_name = {w.english_word.lower(): w for w in words}
        self._written: list = []

    def find_word_by_id(self, word_id: int) -> Optional[FakeWord]:
        return self._by_id.get(word_id)

    def find_word_by_name(self, english_word: str) -> Optional[FakeWord]:
        return self._by_name.get(english_word.lower())

    def set_field(self, word_id: int, field_name: str, value: List[str]) -> None:
        w = self._by_id.get(word_id)
        if w is not None:
            setattr(w, field_name, value)
            self._written.append((word_id, field_name, value))


def _make_repo(*words: tuple) -> FakeRepository:
    """words: (word_id, english_word, synonyms, antonyms)"""
    objs = [FakeWord(*w) for w in words]
    return FakeRepository(objs)


# ---------------------------------------------------------------------------
# parse_word_list
# ---------------------------------------------------------------------------


class TestParseWordList:
    def test_single_item(self):
        result, err = parse_word_list("large")
        assert err is None
        assert result == ["large"]

    def test_multiple_semicolon_separated(self):
        result, err = parse_word_list("large;huge;big")
        assert err is None
        assert result == ["large", "huge", "big"]

    def test_strips_whitespace_around_items(self):
        result, err = parse_word_list(" large ; huge ; big ")
        assert err is None
        assert result == ["large", "huge", "big"]

    def test_empty_string_returns_none_none(self):
        result, err = parse_word_list("")
        assert result is None
        assert err is None

    def test_whitespace_only_returns_none_none(self):
        result, err = parse_word_list("   ")
        assert result is None
        assert err is None

    def test_deduplicates_case_insensitive(self):
        result, err = parse_word_list("Large;large;LARGE")
        assert err is None
        assert len(result) == 1
        assert result[0] == "Large"

    def test_preserves_order(self):
        result, err = parse_word_list("c;a;b")
        assert err is None
        assert result == ["c", "a", "b"]

    def test_single_semicolon_returns_error(self):
        result, err = parse_word_list(";")
        assert result is None
        assert err is not None

    def test_trailing_semicolon_ignored(self):
        result, err = parse_word_list("large;huge;")
        assert err is None
        assert result == ["large", "huge"]


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


class TestParseRow:
    def test_valid_row_with_both_fields(self):
        entry, err = parse_row({"english_word": "big", "synonyms": "large;huge", "antonyms": "small;tiny"})
        assert err is None
        assert entry.english_word == "big"
        assert entry.synonyms == ["large", "huge"]
        assert entry.antonyms == ["small", "tiny"]

    def test_valid_row_synonyms_only(self):
        entry, err = parse_row({"english_word": "big", "synonyms": "large", "antonyms": ""})
        assert err is None
        assert entry.synonyms == ["large"]
        assert entry.antonyms is None

    def test_valid_row_antonyms_only(self):
        entry, err = parse_row({"english_word": "big", "synonyms": "", "antonyms": "small"})
        assert err is None
        assert entry.synonyms is None
        assert entry.antonyms == ["small"]

    def test_both_empty_returns_error(self):
        _, err = parse_row({"english_word": "big", "synonyms": "", "antonyms": ""})
        assert err is not None

    def test_empty_english_word_returns_error(self):
        _, err = parse_row({"english_word": "", "synonyms": "large", "antonyms": ""})
        assert err is not None

    def test_missing_english_word_returns_error(self):
        _, err = parse_row({"synonyms": "large", "antonyms": "small"})
        assert err is not None

    def test_word_id_parsed_when_present(self):
        entry, err = parse_row({"english_word": "big", "synonyms": "large", "word_id": "42"})
        assert err is None
        assert entry.word_id == 42

    def test_empty_word_id_treated_as_none(self):
        entry, err = parse_row({"english_word": "big", "synonyms": "large", "word_id": ""})
        assert err is None
        assert entry.word_id is None

    def test_invalid_word_id_returns_error(self):
        _, err = parse_row({"english_word": "big", "synonyms": "large", "word_id": "abc"})
        assert err is not None

    def test_strips_whitespace_from_word(self):
        entry, err = parse_row({"english_word": "  big  ", "synonyms": "large"})
        assert err is None
        assert entry.english_word == "big"

    def test_missing_synonyms_column_treated_as_empty(self):
        entry, err = parse_row({"english_word": "big", "antonyms": "small"})
        assert err is None
        assert entry.synonyms is None
        assert entry.antonyms == ["small"]


# ---------------------------------------------------------------------------
# load_csv
# ---------------------------------------------------------------------------


class TestLoadCsv:
    def _write_csv(self, path: Path, rows: list) -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["english_word", "synonyms", "antonyms"])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_loads_valid_csv(self, tmp_path: Path):
        csv_path = tmp_path / "sa.csv"
        self._write_csv(csv_path, [
            {"english_word": "big", "synonyms": "large", "antonyms": "small"},
            {"english_word": "fast", "synonyms": "quick", "antonyms": "slow"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 2

    def test_skips_comment_lines(self, tmp_path: Path):
        csv_path = tmp_path / "sa.csv"
        csv_path.write_text(
            "# comment\nenglish_word,synonyms,antonyms\nbig,large,small\n",
            encoding="utf-8",
        )
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1

    def test_missing_english_word_column_reported(self, tmp_path: Path):
        csv_path = tmp_path / "sa.csv"
        csv_path.write_text("synonyms,antonyms\nlarge,small\n", encoding="utf-8")
        _, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert "english_word" in errors[0]

    def test_invalid_row_reported_not_halted(self, tmp_path: Path):
        csv_path = tmp_path / "sa.csv"
        self._write_csv(csv_path, [
            {"english_word": "big", "synonyms": "large", "antonyms": "small"},
            {"english_word": "bad_row", "synonyms": "", "antonyms": ""},  # both empty → error
            {"english_word": "fast", "synonyms": "quick", "antonyms": "slow"},
        ])
        entries, errors = load_csv([csv_path])
        assert len(errors) == 1
        assert len(entries) == 2

    def test_duplicate_word_last_wins(self, tmp_path: Path):
        csv_path = tmp_path / "sa.csv"
        self._write_csv(csv_path, [
            {"english_word": "big", "synonyms": "large", "antonyms": "small"},
            {"english_word": "big", "synonyms": "huge", "antonyms": "tiny"},
        ])
        entries, errors = load_csv([csv_path])
        assert errors == []
        assert len(entries) == 1
        assert entries[0].synonyms == ["huge"]

    def test_file_not_found_reported(self, tmp_path: Path):
        _, errors = load_csv([tmp_path / "missing.csv"])
        assert len(errors) == 1

    def test_merges_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        self._write_csv(f1, [{"english_word": "big", "synonyms": "large", "antonyms": "small"}])
        self._write_csv(f2, [{"english_word": "fast", "synonyms": "quick", "antonyms": "slow"}])
        entries, errors = load_csv([f1, f2])
        assert errors == []
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# plan_import
# ---------------------------------------------------------------------------


class TestPlanImport:
    def _entry(self, word: str, synonyms=None, antonyms=None, word_id=None) -> SynAntEntry:
        return SynAntEntry(
            english_word=word,
            synonyms=synonyms,
            antonyms=antonyms,
            word_id=word_id,
        )

    def test_sets_null_synonyms(self):
        repo = _make_repo((1, "big", None, None))
        plan = plan_import([self._entry("big", synonyms=["large"])], repo)
        sets = [c for c in plan.changes if c.action == "set" and c.field_name == "synonyms"]
        assert len(sets) == 1
        assert sets[0].new_value == ["large"]

    def test_sets_null_antonyms(self):
        repo = _make_repo((1, "big", None, None))
        plan = plan_import([self._entry("big", antonyms=["small"])], repo)
        sets = [c for c in plan.changes if c.action == "set" and c.field_name == "antonyms"]
        assert len(sets) == 1
        assert sets[0].new_value == ["small"]

    def test_noop_when_already_same_value(self):
        repo = _make_repo((1, "big", ["large"], ["small"]))
        plan = plan_import([self._entry("big", synonyms=["large"], antonyms=["small"])], repo, force=True)
        noops = [c for c in plan.changes if c.action == "noop"]
        assert len(noops) == 2

    def test_skips_existing_without_force(self):
        repo = _make_repo((1, "big", ["large"], ["small"]))
        plan = plan_import([self._entry("big", synonyms=["huge"], antonyms=["tiny"])], repo, force=False)
        skips = [c for c in plan.changes if c.action == "skip_force"]
        assert len(skips) == 2

    def test_overwrites_existing_with_force(self):
        repo = _make_repo((1, "big", ["large"], ["small"]))
        plan = plan_import([self._entry("big", synonyms=["huge"], antonyms=["tiny"])], repo, force=True)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 2

    def test_skips_missing_word(self):
        repo = _make_repo()
        plan = plan_import([self._entry("unknown", synonyms=["x"])], repo)
        skips = [c for c in plan.changes if c.action == "skip_no_match"]
        assert len(skips) >= 1

    def test_skips_empty_field(self):
        repo = _make_repo((1, "big", None, None))
        # synonyms only, antonyms=None
        plan = plan_import([self._entry("big", synonyms=["large"])], repo)
        skip_empty = [c for c in plan.changes if c.action == "skip_empty"]
        assert len(skip_empty) == 1
        assert skip_empty[0].field_name == "antonyms"

    def test_case_insensitive_name_match(self):
        repo = _make_repo((1, "Hello", None, None))
        plan = plan_import([self._entry("hello", synonyms=["hi"])], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_field_filter_synonyms_only(self):
        repo = _make_repo((1, "big", None, None))
        plan = plan_import(
            [self._entry("big", synonyms=["large"], antonyms=["small"])],
            repo,
            field_names=["synonyms"],
        )
        field_names_in_plan = {c.field_name for c in plan.changes}
        assert field_names_in_plan == {"synonyms"}

    def test_field_filter_antonyms_only(self):
        repo = _make_repo((1, "big", None, None))
        plan = plan_import(
            [self._entry("big", synonyms=["large"], antonyms=["small"])],
            repo,
            field_names=["antonyms"],
        )
        field_names_in_plan = {c.field_name for c in plan.changes}
        assert field_names_in_plan == {"antonyms"}

    def test_priority_tier_filter_skips_wrong_tier(self):
        repo = _make_repo((1, "hello", None, None))
        priority_map = {"hello": 2}
        plan = plan_import(
            [self._entry("hello", synonyms=["hi"])],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        skips = [c for c in plan.changes if c.action == "skip_tier"]
        assert len(skips) >= 1

    def test_priority_tier_filter_allows_matching_tier(self):
        repo = _make_repo((1, "hello", None, None))
        priority_map = {"hello": 1}
        plan = plan_import(
            [self._entry("hello", synonyms=["hi"])],
            repo,
            priority_tier=1,
            priority_map=priority_map,
        )
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1

    def test_word_id_takes_priority_over_name(self):
        repo = _make_repo((1, "big", None, None), (2, "fast", None, None))
        plan = plan_import([self._entry("big", synonyms=["quick"], word_id=2)], repo)
        sets = [c for c in plan.changes if c.action == "set"]
        assert len(sets) == 1
        assert sets[0].word_id == 2


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_applies_set_changes(self):
        repo = _make_repo((1, "big", None, None))
        plan = SynAntPlan(changes=[
            FieldChange(action="set", english_word="big", field_name="synonyms",
                        new_value=["large"], word_id=1),
            FieldChange(action="set", english_word="big", field_name="antonyms",
                        new_value=["small"], word_id=1),
        ])
        count = apply_plan(plan, repo)
        assert count == 2
        assert len(repo._written) == 2

    def test_skips_non_set_actions(self):
        repo = _make_repo((1, "big", ["large"], None))
        plan = SynAntPlan(changes=[
            FieldChange(action="noop", english_word="big", field_name="synonyms", word_id=1),
            FieldChange(action="skip_force", english_word="big", field_name="synonyms", word_id=1),
            FieldChange(action="skip_no_match", english_word="missing", field_name="synonyms"),
        ])
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo._written == []

    def test_idempotent_second_run(self):
        repo = _make_repo((1, "big", None, None))
        entry = SynAntEntry(english_word="big", synonyms=["large"], antonyms=None)
        plan1 = plan_import([entry], repo)
        apply_plan(plan1, repo)
        # Second plan: word now has synonyms=["large"], same value → noop with force
        plan2 = plan_import([entry], repo, force=True)
        noops = [c for c in plan2.changes if c.action == "noop" and c.field_name == "synonyms"]
        assert len(noops) == 1
        apply_plan(plan2, repo)
        # Written only once for synonyms field
        syn_writes = [w for w in repo._written if w[1] == "synonyms"]
        assert len(syn_writes) == 1


# ---------------------------------------------------------------------------
# action_count helper
# ---------------------------------------------------------------------------


class TestActionCount:
    def test_counts_by_action_and_field(self):
        plan = SynAntPlan(changes=[
            FieldChange(action="set", english_word="big", field_name="synonyms", word_id=1),
            FieldChange(action="set", english_word="big", field_name="antonyms", word_id=1),
            FieldChange(action="noop", english_word="fast", field_name="synonyms", word_id=2),
        ])
        assert plan.action_count("set") == 2
        assert plan.action_count("set", "synonyms") == 1
        assert plan.action_count("set", "antonyms") == 1
        assert plan.action_count("noop") == 1
        assert plan.action_count("noop", "synonyms") == 1
        assert plan.action_count("noop", "antonyms") == 0


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _plan(self, *changes) -> SynAntPlan:
        return SynAntPlan(changes=list(changes))

    def test_contains_title(self):
        plan = self._plan()
        report = format_report(plan, dry_run=False, force=False,
                               field_names=["synonyms", "antonyms"], elapsed=0.1)
        assert "Synonyms/Antonyms Import Report" in report

    def test_dry_run_flag_visible(self):
        plan = self._plan()
        report = format_report(plan, dry_run=True, force=False,
                               field_names=["synonyms", "antonyms"], elapsed=0.1)
        assert "dry-run" in report

    def test_set_count_visible(self):
        plan = self._plan(
            FieldChange(action="set", english_word="big", field_name="synonyms",
                        new_value=["large"], word_id=1),
        )
        report = format_report(plan, dry_run=False, force=False,
                               field_names=["synonyms"], elapsed=0.1)
        assert "synonyms" in report
        assert "1" in report

    def test_errors_listed(self):
        plan = self._plan()
        plan.errors = ["sa.csv[0]: both synonyms and antonyms are empty"]
        report = format_report(plan, dry_run=False, force=False,
                               field_names=["synonyms", "antonyms"], elapsed=0.1)
        assert "both synonyms and antonyms are empty" in report

    def test_total_writes_shown(self):
        plan = self._plan(
            FieldChange(action="set", english_word="big", field_name="synonyms",
                        new_value=["large"], word_id=1),
            FieldChange(action="set", english_word="big", field_name="antonyms",
                        new_value=["small"], word_id=1),
        )
        report = format_report(plan, dry_run=False, force=False,
                               field_names=["synonyms", "antonyms"], elapsed=0.1)
        assert "Total field writes: 2" in report

    def test_not_found_words_listed(self):
        plan = self._plan(
            FieldChange(action="skip_no_match", english_word="xyzzy", field_name="synonyms"),
        )
        report = format_report(plan, dry_run=False, force=False,
                               field_names=["synonyms"], elapsed=0.1)
        assert "xyzzy" in report


# ---------------------------------------------------------------------------
# Integration: real CSV file
# ---------------------------------------------------------------------------


class TestRealCsvFile:
    def test_real_csv_loads_without_errors(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "synonyms_antonyms.csv"
        if not csv_path.exists():
            pytest.skip("synonyms_antonyms.csv not present")
        entries, errors = load_csv([csv_path])
        assert errors == [], f"Unexpected load errors: {errors}"
        assert len(entries) > 0

    def test_all_english_words_are_non_empty(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "synonyms_antonyms.csv"
        if not csv_path.exists():
            pytest.skip("synonyms_antonyms.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            assert e.english_word.strip(), "Empty english_word in CSV"

    def test_all_synonym_lists_are_lists(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "synonyms_antonyms.csv"
        if not csv_path.exists():
            pytest.skip("synonyms_antonyms.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            if e.synonyms is not None:
                assert isinstance(e.synonyms, list)
                assert len(e.synonyms) >= 1

    def test_all_antonym_lists_are_lists(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "synonyms_antonyms.csv"
        if not csv_path.exists():
            pytest.skip("synonyms_antonyms.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            if e.antonyms is not None:
                assert isinstance(e.antonyms, list)
                assert len(e.antonyms) >= 1

    def test_covers_multiple_cefr_levels(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "synonyms_antonyms.csv"
        if not csv_path.exists():
            pytest.skip("synonyms_antonyms.csv not present")
        entries, _ = load_csv([csv_path])
        words = {e.english_word.lower() for e in entries}
        # A1-level words
        assert "big" in words or "good" in words or "fast" in words
        # B1-level words
        assert "achieve" in words or "improve" in words or "create" in words
        # C1-level words
        assert "facilitate" in words or "enhance" in words or "enormous" in words

    def test_no_empty_synonym_items(self):
        csv_path = Path(__file__).resolve().parents[2] / "content" / "vocabulary" / "synonyms_antonyms.csv"
        if not csv_path.exists():
            pytest.skip("synonyms_antonyms.csv not present")
        entries, _ = load_csv([csv_path])
        for e in entries:
            if e.synonyms is not None:
                for item in e.synonyms:
                    assert item.strip(), f"Empty synonym item for {e.english_word!r}"
            if e.antonyms is not None:
                for item in e.antonyms:
                    assert item.strip(), f"Empty antonym item for {e.english_word!r}"


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from import_synonyms_antonyms import main
        assert main(["--no-db"]) == 0
