"""Tests for scripts/generate_reading_annotations.py.

Pure-function tests only — no DB or Flask app required. The script imports
``create_app`` inside ``main()``, so importing the module here is safe.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from generate_reading_annotations import (  # noqa: E402
    LOAD_DRIFT,
    LOAD_INVALID,
    LOAD_SKIP_EXISTING,
    LOAD_UNMATCHED,
    LOAD_WRITE,
    LOAD_WRONG_TYPE,
    decide_load,
    fixture_key,
    make_batch_id,
    normalize_for_match,
    passage_digest,
    validate_scaffold,
)


PASSAGE = (
    "“They still haven’t caught him, then?” he asked. "
    "“No,” said Mr. Weasley, looking extremely grave. "
    "It’s the Azkaban guards who’ll get him back, You mark my words. "
    "Fred muttered under his breath, and Mrs. Weasley spoke, swelling with pride."
)


def _valid_scaffold() -> dict[str, Any]:
    return {
        "objectives": ["Первое", "Второе", "Третье"],
        "before_reading": {"goal": "Цель чтения", "tasks": ["Вопрос один", "Вопрос два"]},
        "annotations": [
            {
                "phrase": "You mark my words",
                "type": "lexical",
                "note": "Попомни мои слова.",
                "quick_use": ["You mark my words, he will be late."],
            },
            {
                "phrase": "under his breath",
                "type": "lexical",
                "note": "Себе под нос.",
                "quick_use": ["He muttered under his breath."],
            },
            {
                "phrase": "swelling with pride",
                "type": "cultural",
                "note": "Раздуваться от гордости.",
                "quick_use": ["She swelled with pride."],
            },
            {
                "phrase": "haven't caught him",
                "type": "grammar",
                "note": "Present Perfect.",
                "quick_use": ["They haven't caught him yet."],
            },
        ],
        "reflection": [
            {"question": "Why?", "hint": "Look closer.", "sample_answer": "Because."},
        ],
        "self_check": [
            {"statement": "A", "answer": True, "explanation": "yes"},
            {"statement": "B", "answer": False, "explanation": "no"},
            {"statement": "C", "answer": True, "explanation": "yes"},
        ],
        "can_do": ["Могу раз", "Могу два", "Могу три"],
    }


# ---------------------------------------------------------------------------
# normalize_for_match
# ---------------------------------------------------------------------------


def test_normalize_collapses_whitespace():
    assert normalize_for_match("  a \n\t b  ") == "a b"


def test_normalize_unifies_typographic_punctuation():
    assert normalize_for_match("“haven’t” — yes") == '"haven\'t" - yes'


# ---------------------------------------------------------------------------
# make_batch_id
# ---------------------------------------------------------------------------


def test_batch_id_is_derived_from_the_lesson_range():
    assert make_batch_id(3, 3158, 3168) == "course_3_03158-03168"


def test_batch_id_is_stable_for_the_same_lessons():
    """Re-exporting the same lessons must reuse the file name, so an existing
    result is recognised instead of being written past."""
    assert make_batch_id(3, 3158, 3168) == make_batch_id(3, 3158, 3168)


def test_batch_id_differs_once_earlier_lessons_are_imported():
    """Imported lessons leave the pending list; the next chunk must not inherit
    the previous chunk's name, or its lessons would be silently skipped."""
    assert make_batch_id(3, 3158, 3168) != make_batch_id(3, 3170, 3180)


def test_batch_id_sorts_lexicographically_by_lesson_id():
    ids = [make_batch_id(3, 990, 999), make_batch_id(3, 3158, 3168)]
    assert sorted(ids) == ids


# ---------------------------------------------------------------------------
# validate_scaffold — happy path
# ---------------------------------------------------------------------------


def test_valid_scaffold_has_no_errors():
    assert validate_scaffold(_valid_scaffold(), PASSAGE) == []


def test_straight_apostrophe_matches_typographic_passage():
    """The passage uses U+2019; a phrase typed with ' must still match."""
    scaffold = _valid_scaffold()
    assert any(
        "haven't caught him" == ann["phrase"] for ann in scaffold["annotations"]
    )
    assert validate_scaffold(scaffold, PASSAGE) == []


def test_phrase_matches_across_collapsed_whitespace():
    scaffold = _valid_scaffold()
    scaffold["annotations"][0]["phrase"] = "You  mark\nmy   words"
    assert validate_scaffold(scaffold, PASSAGE) == []


def test_phrase_matches_regardless_of_case():
    """A sentence-initial capital in the passage must not reject the quote."""
    scaffold = _valid_scaffold()
    scaffold["annotations"][0]["phrase"] = "you mark my words"
    assert validate_scaffold(scaffold, PASSAGE) == []


def test_phrase_matches_when_passage_has_a_space_before_a_comma():
    """Some source texts read `word , next`; the quote is still verbatim."""
    passage = "He said the word , and then he left the room."
    scaffold = _valid_scaffold()
    scaffold["annotations"] = [
        {
            "phrase": "the word, and then he left",
            "type": "lexical",
            "note": "Проверка нормализации.",
            "quick_use": ["He left the room."],
        },
        {
            "phrase": "left the room",
            "type": "lexical",
            "note": "Вторая заметка.",
            "quick_use": ["She left the room."],
        },
        {
            "phrase": "He said",
            "type": "cultural",
            "note": "Третья заметка.",
            "quick_use": ["He said nothing."],
        },
        {
            "phrase": "and then",
            "type": "grammar",
            "note": "Четвёртая заметка.",
            "quick_use": ["And then we waited."],
        },
    ]
    assert validate_scaffold(scaffold, passage) == []


# ---------------------------------------------------------------------------
# validate_scaffold — rejections
# ---------------------------------------------------------------------------


def test_rejects_non_dict():
    errors = validate_scaffold(["not", "a", "dict"], PASSAGE)
    assert errors and "expected an object" in errors[0]


def test_rejects_missing_keys():
    scaffold = _valid_scaffold()
    del scaffold["can_do"]
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("missing keys" in e and "can_do" in e for e in errors)


def test_rejects_hallucinated_phrase():
    scaffold = _valid_scaffold()
    scaffold["annotations"][0]["phrase"] = "Harry drew his wand and shouted"
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("does not occur verbatim" in e for e in errors)


def test_rejects_duplicate_phrase():
    scaffold = _valid_scaffold()
    scaffold["annotations"][1]["phrase"] = scaffold["annotations"][0]["phrase"]
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("duplicate phrase" in e for e in errors)


def test_rejects_too_many_grammar_notes():
    scaffold = _valid_scaffold()
    scaffold["annotations"][0]["type"] = "grammar"
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("grammar note allowed" in e for e in errors)


def test_rejects_unknown_annotation_type():
    scaffold = _valid_scaffold()
    scaffold["annotations"][0]["type"] = "vocabulary"
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("annotations[0].type" in e for e in errors)


def test_rejects_too_few_annotations():
    scaffold = _valid_scaffold()
    scaffold["annotations"] = scaffold["annotations"][:2]
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any(e.startswith("annotations: expected") for e in errors)


def test_rejects_wrong_objectives_count():
    scaffold = _valid_scaffold()
    scaffold["objectives"] = ["Только один"]
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("objectives: expected 3 items" in e for e in errors)


def test_rejects_blank_string_items():
    scaffold = _valid_scaffold()
    scaffold["can_do"][1] = "   "
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("can_do[1]" in e for e in errors)


def test_rejects_missing_before_reading_task():
    scaffold = _valid_scaffold()
    scaffold["before_reading"]["tasks"] = ["Только один вопрос"]
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("before_reading.tasks: expected 2 items" in e for e in errors)


def test_rejects_string_answer_in_self_check():
    """A string would render as truthy in Jinja and flip the shown answer."""
    scaffold = _valid_scaffold()
    scaffold["self_check"][1]["answer"] = "false"
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("expected JSON true/false" in e for e in errors)


def test_rejects_self_check_without_a_false_answer():
    scaffold = _valid_scaffold()
    for item in scaffold["self_check"]:
        item["answer"] = True
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("mix at least one true and one false" in e for e in errors)


def test_rejects_incomplete_reflection():
    scaffold = _valid_scaffold()
    scaffold["reflection"][0]["sample_answer"] = ""
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("reflection[0].sample_answer" in e for e in errors)


def test_rejects_empty_quick_use():
    scaffold = _valid_scaffold()
    scaffold["annotations"][0]["quick_use"] = []
    errors = validate_scaffold(scaffold, PASSAGE)
    assert any("quick_use" in e for e in errors)


def test_validation_does_not_mutate_input():
    scaffold = _valid_scaffold()
    snapshot = deepcopy(scaffold)
    validate_scaffold(scaffold, PASSAGE)
    assert scaffold == snapshot


# ---------------------------------------------------------------------------
# passage_digest / fixture_key — carrying scaffolds between databases
# ---------------------------------------------------------------------------


def test_digest_ignores_cosmetic_differences():
    """Two databases may store the same passage with different quote glyphs."""
    plain = PASSAGE.replace("“", '"').replace("”", '"').replace("’", "'")
    assert passage_digest(PASSAGE) == passage_digest(plain)
    assert passage_digest(PASSAGE) == passage_digest(f"  {PASSAGE}\n")


def test_digest_changes_when_the_passage_is_re_sliced():
    assert passage_digest(PASSAGE) != passage_digest(PASSAGE + " He left the room.")


def test_fixture_key_accepts_numbers_written_as_strings():
    """Numbers come back from JSON as ints, but a hand-edited file may hold strings."""
    assert fixture_key("slug", "2", "13", "reading") == ("slug", 2, 13, "reading")


def test_fixture_key_separates_lessons_of_the_same_day():
    part1 = fixture_key("slug", 1, 3, "reading_part1")
    part2 = fixture_key("slug", 1, 3, "reading_part2")
    assert part1 != part2


# ---------------------------------------------------------------------------
# decide_load
# ---------------------------------------------------------------------------


def _entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "course_slug": "english-course-test",
        "module_number": 1,
        "day_number": 2,
        "lesson_type": "reading",
        "passage_sha256": passage_digest(PASSAGE),
        "scaffold": _valid_scaffold(),
    }
    entry.update(overrides)
    return entry


def _target(**overrides: Any) -> dict[str, Any]:
    target = {"lesson_type": "reading", "slice_text": PASSAGE, "has_annotations": False}
    target.update(overrides)
    return target


def test_load_writes_a_matching_scaffold():
    outcome, messages = decide_load(_entry(), _target())
    assert (outcome, messages) == (LOAD_WRITE, [])


def test_load_reports_a_key_that_matched_nothing():
    """A course missing on the target must be visible, not silently dropped."""
    outcome, messages = decide_load(_entry(), None)
    assert outcome == LOAD_UNMATCHED
    assert "target database" in messages[0]


def test_load_refuses_a_lesson_that_is_not_a_reading_lesson():
    outcome, _ = decide_load(_entry(), _target(lesson_type="vocabulary"))
    assert outcome == LOAD_WRONG_TYPE


def test_load_keeps_an_existing_scaffold_by_default():
    outcome, messages = decide_load(_entry(), _target(has_annotations=True))
    assert outcome == LOAD_SKIP_EXISTING
    assert "--overwrite" in messages[0]


def test_load_replaces_an_existing_scaffold_when_asked():
    outcome, _ = decide_load(_entry(), _target(has_annotations=True), overwrite=True)
    assert outcome == LOAD_WRITE


def test_load_stops_when_the_target_passage_is_a_different_text():
    """The scaffold was written for another slice; its questions no longer fit."""
    outcome, messages = decide_load(_entry(), _target(slice_text="A completely other text."))
    assert outcome == LOAD_DRIFT
    assert "--allow-passage-drift" in messages[0]


def test_drift_is_refused_even_when_the_quotes_would_still_match():
    """Matching quotes are not enough: the rest of the scaffold describes the
    old passage, so the mismatch is reported rather than written."""
    outcome, _ = decide_load(_entry(), _target(slice_text=PASSAGE + " Extra sentence here."))
    assert outcome == LOAD_DRIFT


def test_drift_can_be_accepted_and_is_still_warned_about():
    outcome, messages = decide_load(
        _entry(), _target(slice_text=PASSAGE + " Extra sentence here."),
        allow_passage_drift=True,
    )
    assert outcome == LOAD_WRITE
    assert any("differs" in message for message in messages)


def test_load_validates_against_the_target_passage_not_the_fixture():
    """The digest may be absent (hand-written fixture) — the quotes still have to
    occur in the text the student will read."""
    entry = _entry(passage_sha256=None)
    outcome, messages = decide_load(entry, _target(slice_text="An unrelated passage entirely."))
    assert outcome == LOAD_INVALID
    assert any("does not occur verbatim" in message for message in messages)


def test_load_rejects_a_scaffold_that_lost_a_section():
    entry = _entry()
    del entry["scaffold"]["can_do"]
    outcome, messages = decide_load(entry, _target())
    assert outcome == LOAD_INVALID
    assert any("missing keys" in message for message in messages)


def test_load_rejects_an_entry_without_a_scaffold():
    outcome, _ = decide_load(_entry(scaffold=None), _target())
    assert outcome == LOAD_INVALID
