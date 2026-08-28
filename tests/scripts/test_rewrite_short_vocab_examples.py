"""Unit tests for scripts/rewrite_short_vocab_examples.py (audit CNT-006).

The point of that script is not the rewrite mechanics — it is the 196 authored
sentences it carries. Those sentences are the thing that now holds the B1+
contextual-example bar, replacing a generator filler that held it before. So the
tests here assert the text itself: every replacement clears the floor its module
level demands, keeps the word it illustrates, and ships a Russian translation.

`module_completed/` is gitignored, so anything corpus-dependent skips when the
corpus is absent; the data-level invariants run everywhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.rewrite_short_vocab_examples import (
    CONTEXTUAL_EXAMPLE_MIN_WORDS,
    DEFAULT_SOURCE,
    FILLER,
    REPLACEMENTS,
    build_sql,
    check_entry,
    word_count,
)

LEVEL_RE = re.compile(r"^module_(A1|A2|B1|B2|C1)_")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def level_of(key: str) -> str:
    match = LEVEL_RE.match(key.split("|")[0])
    assert match, f"cannot read a CEFR level out of {key!r}"
    return match.group(1)


class TestAuthoredTextHoldsTheBar:
    """These sentences replaced the filler that was holding the bar for them."""

    def test_the_full_set_is_present(self):
        assert len(REPLACEMENTS) == 196

    @pytest.mark.parametrize("key", sorted(REPLACEMENTS))
    def test_replacement_clears_its_level_floor(self, key):
        floor = CONTEXTUAL_EXAMPLE_MIN_WORDS[level_of(key)]
        example = REPLACEMENTS[key]["example"]
        assert word_count(example) >= floor, f"{key}: {example!r}"

    def test_no_replacement_carries_the_filler(self):
        offenders = [k for k, v in REPLACEMENTS.items() if FILLER in v["example"]]
        assert not offenders

    def test_every_replacement_is_translated(self):
        untranslated = [
            k for k, v in REPLACEMENTS.items()
            if not CYRILLIC_RE.search(v.get("example_translation", ""))
        ]
        assert not untranslated

    def test_replacement_still_shows_the_word_it_teaches(self):
        """A longer sentence is worthless if it lost the vocabulary item."""
        missing = []
        for key, entry in REPLACEMENTS.items():
            lowered = entry["example"].lower()
            stems = [t[:5] for t in re.findall(r"[A-Za-z]+", entry["en"].lower()) if len(t) >= 3]
            if stems and not any(stem in lowered for stem in stems):
                missing.append(f"{key}: {entry['en']!r} not in {entry['example']!r}")
        assert not missing


class TestRefusesToGuess:
    """A corpus that moved must abort the run, not get rewritten blindly."""

    def _entry(self):
        return {"en": "urban", "old": f"Urban life is busy. {FILLER}",
                "example": "Urban life is very busy, but it never feels lonely.",
                "example_translation": "Городская жизнь очень загружена."}

    def test_word_drift_is_refused(self):
        item = {"english": "rural", "example": f"Urban life is busy. {FILLER}"}
        assert check_entry(item, self._entry(), "B1").startswith("english is")

    def test_already_applied_is_reported_not_rewritten(self):
        entry = self._entry()
        item = {"english": "urban", "example": entry["example"]}
        assert check_entry(item, entry, "B1") == "ALREADY_APPLIED"

    def test_text_edited_since_authoring_is_refused(self):
        """The recorded `old` is the contract: anything else means the corpus moved."""
        item = {"english": "urban", "example": "Someone edited this by hand."}
        assert check_entry(item, self._entry(), "B1") == (
            "example is not the text this rewrite was written against"
        )

    def test_a_replacement_below_the_floor_is_refused(self):
        entry = {**self._entry(), "example": "Urban life."}
        item = {"english": "urban", "example": entry["old"]}
        assert "floor is 6" in check_entry(item, entry, "B1")

    def test_non_string_example_is_refused(self):
        item = {"english": "urban", "example": None}
        assert check_entry(item, self._entry(), "B1") == "example is not a string"


class TestSqlSurvivesAnAlreadyPatchedCorpus:
    """Regression: SQL was first built from rows this run happened to rewrite.

    Locally the corpus is patched immediately, so a later `--sql` produced an
    empty file while production still needed all 196 statements. The replaced
    text is recorded per entry precisely so the handoff never depends on the
    state of this checkout.
    """

    def test_every_entry_records_the_text_it_replaces(self):
        missing = [k for k, v in REPLACEMENTS.items() if FILLER not in v.get("old", "")]
        assert not missing

    def test_recorded_old_text_differs_from_the_replacement(self):
        same = [k for k, v in REPLACEMENTS.items() if v["old"] == v["example"]]
        assert not same

    def test_full_handoff_is_emitted_from_data_alone(self):
        rows = [
            (e["en"], e["old"], e["example"], e["example_translation"])
            for _, e in sorted(REPLACEMENTS.items())
        ]
        sql = build_sql(rows)
        assert sql.count("UPDATE lessons l SET content") == 196


class TestGeneratedSql:
    def test_apostrophes_are_doubled(self):
        sql = build_sql([("reply", f"Old text. {FILLER}", "It isn't short now, truly.", "Ответ.")])
        assert "It isn''t short now, truly." in sql
        assert "isn't short" not in sql

    def test_statement_matches_on_content_not_ids(self):
        sql = build_sql([("urban", f"Urban life is busy. {FILLER}", "Urban life is busy downtown.", "Текст.")])
        assert "WHERE l.type = 'vocabulary'" in sql
        assert "l.id" not in sql
        assert FILLER in sql  # the old text is the lookup key


class TestAgainstTheCorpus:
    """Skips in a fresh checkout — `module_completed/` is gitignored."""

    def test_every_key_points_at_a_real_vocabulary_item(self):
        if not DEFAULT_SOURCE.is_dir() or not any(DEFAULT_SOURCE.glob("module_*.json")):
            pytest.skip(f"corpus not present at {DEFAULT_SOURCE}")

        problems = []
        for key, entry in REPLACEMENTS.items():
            name, li, ii = key.split("|")
            path = DEFAULT_SOURCE / name
            if not path.is_file():
                problems.append(f"{name}: missing")
                continue
            module = json.loads(path.read_text(encoding="utf-8"))["module"]
            try:
                item = module["lessons"][int(li)]["content"]["vocabulary"][int(ii)]
            except (IndexError, KeyError, TypeError):
                problems.append(f"{key}: item is gone")
                continue
            if item.get("english") != entry["en"]:
                problems.append(f"{key}: {item.get('english')!r} != {entry['en']!r}")
        assert not problems, problems[:5]

    def test_no_filler_survives_in_the_corpus(self):
        files = sorted(DEFAULT_SOURCE.glob("module_*.json")) if DEFAULT_SOURCE.is_dir() else []
        if not files:
            pytest.skip(f"corpus not present at {DEFAULT_SOURCE}")
        left = [p.name for p in files if FILLER in p.read_text(encoding="utf-8")]
        assert not left, f"filler still in: {left[:5]}"
