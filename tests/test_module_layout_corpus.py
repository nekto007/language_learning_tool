"""Lesson audit item 18: the second flashcard lesson sits at position 9.

Guards the corpus layout and the position-field invariants the app relies on
(``number`` == ``order`` == ``id`` == array position).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1] / "module_completed" / "fixed"
pytestmark = pytest.mark.skipif(not MODULE_DIR.exists(), reason="module corpus not present in this checkout")

EXPECTED = [
    "vocabulary", "flashcards", "collocation_matching", "grammar", "sentence_completion", "reading",
    "listening_immersion", "listening_quiz", "flashcards", "audio_fill_blank", "shadow_reading", "dictation",
    "dialogue_completion_quiz", "ordering_quiz", "translation", "translation_quiz", "writing_prompt", "final_test",
]


def _modules():
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))["module"]) for p in sorted(MODULE_DIR.glob("*.json"))]


def test_second_deck_is_ninth_everywhere():
    off = [(name, [lesson["type"] for lesson in sorted(m["lessons"], key=lambda lesson: lesson["number"])])
           for name, m in _modules()]
    bad = [name for name, types in off if types != EXPECTED]
    assert bad == []


def test_position_fields_stay_in_step():
    for name, m in _modules():
        for pos, lesson in enumerate(m["lessons"], start=1):
            assert lesson["number"] == pos, (name, pos)
            assert lesson.get("order") == pos, (name, pos)
            assert lesson.get("id") == pos, (name, pos)


def test_six_lessons_separate_the_two_decks():
    for name, m in _modules():
        decks = sorted(lesson["number"] for lesson in m["lessons"] if lesson["type"] == "flashcards")
        assert decks == [2, 9], name


def test_script_is_idempotent_on_the_moved_layout():
    import importlib.util
    spec = importlib.util.spec_from_file_location("move_second_card_lesson", Path("scripts/move_second_card_lesson.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    name, m = _modules()[0]
    _patched, changed, warnings = mod.plan_module(Path(name), {"module": m})
    assert changed is False and warnings == []
