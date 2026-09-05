"""Corpus guards for lesson audit item 10: the two flashcard lessons of a module.

Facts the fix rests on (prod copy, 2026-09-05): the decks never share a word,
so «(повторение)» was a misnomer; 26 modules split the deck unevenly; 23 module
titles ended with a dot that leaked into 414 lesson titles.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1] / "module_completed" / "fixed"
CARD_TYPES = {"flashcards", "card"}
PART_RE = re.compile(r"^(?P<base>.+), часть (?P<part>[12])$")

pytestmark = pytest.mark.skipif(not MODULE_DIR.exists(), reason="module corpus not present in this checkout")


def _modules() -> list[tuple[str, dict]]:
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))["module"]) for p in sorted(MODULE_DIR.glob("*.json"))]


def _card_lessons(module: dict) -> list[dict]:
    return sorted((lesson for lesson in module["lessons"] if lesson["type"] in CARD_TYPES), key=lambda lesson: lesson["number"])


def test_corpus_present():
    assert len(_modules()) >= 80


def test_module_titles_have_no_trailing_dot():
    dotted = [name for name, m in _modules() if m["title"].rstrip().endswith(".")]
    assert dotted == []


def test_lesson_titles_carry_no_module_dot():
    bad = [
        (name, lesson["title"])
        for name, m in _modules()
        for lesson in m["lessons"]
        if lesson["title"].rstrip().endswith(".") or ". (" in lesson["title"]
    ]
    assert bad == []


def test_two_card_lessons_named_part_one_and_two():
    for name, m in _modules():
        cards = _card_lessons(m)
        assert len(cards) == 2, name
        matches = [PART_RE.match(lesson["title"]) for lesson in cards]
        assert all(matches), (name, [lesson["title"] for lesson in cards])
        assert [mt.group("part") for mt in matches] == ["1", "2"], name
        # authored distinct decks (C1_14) may differ in theme; the suffix is what is unified
        assert "повторение" not in cards[0]["title"] + cards[1]["title"], name


def test_decks_are_split_evenly():
    uneven = []
    for name, m in _modules():
        first, second = _card_lessons(m)
        n1, n2 = len(first["content"]["cards"]), len(second["content"]["cards"])
        if abs(n1 - n2) > 1 or n1 > n2:
            uneven.append((name, n1, n2))
    assert uneven == []


def test_decks_cover_the_vocabulary_exactly_once():
    """Compared by the word on the card front as a multiset: A2_23 numbers each
    deck 1..10 (ids are per deck), and B1_7 / B2_1 list one word twice in the
    vocabulary itself, so the decks legitimately carry it twice."""
    for name, m in _modules():
        first, second = _card_lessons(m)
        fronts = Counter(c["front"].strip().lower() for lesson in (first, second) for c in lesson["content"]["cards"])
        vocab = [lesson for lesson in m["lessons"] if lesson["type"] == "vocabulary"]
        if vocab and isinstance(vocab[0]["content"].get("vocabulary"), list):
            words = Counter(w["english"].strip().lower() for w in vocab[0]["content"]["vocabulary"])
            assert fronts == words, name
