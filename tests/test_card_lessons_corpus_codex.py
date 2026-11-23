"""Adversarial guards for the item-10 card-lesson migration."""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.rebalance_card_lessons import _dollar, emit_sql, plan_module


CORPUS = Path(__file__).resolve().parents[1] / "module_completed" / "fixed"


def _card(number: int, front: str) -> dict:
    return {"id": number, "front": front, "back": f"translation-{number}"}


def _module(deck1: list[dict], deck2: list[dict]) -> dict:
    return {
        "module": {
            "level": "B1",
            "order": 7,
            "title": "Спорт и достижения.",
            "lessons": [
                {
                    "number": 2,
                    "type": "flashcards",
                    "title": "Карточки: Спорт и достижения.",
                    "content": {"cards": deck1},
                },
                {
                    "number": 14,
                    "type": "card",
                    "title": "Карточки: Спорт и достижения. (повторение)",
                    "content": {"cards": deck2},
                },
            ],
        }
    }


def test_odd_deck_rebalance_preserves_order_identity_duplicates_and_input():
    # Duplicate fronts are legitimate in B1_7/B2_1; migration must move card
    # objects, not deduplicate/rebuild them.  Twenty-one-card modules become 10/11.
    deck1 = [_card(i, "coach" if i in (2, 9) else f"word-{i}") for i in range(1, 8)]
    deck2 = [_card(i, f"word-{i}") for i in range(8, 22)]
    source = _module(deck1, deck2)
    pristine = copy.deepcopy(source)

    patched, change, _warnings = plan_module(Path("module_B1_7.json"), source)
    lessons = patched["module"]["lessons"]
    new1, new2 = (lesson["content"]["cards"] for lesson in lessons)

    assert source == pristine, "planning must not mutate the import source"
    assert [len(new1), len(new2)] == [10, 11]
    assert [card["id"] for card in new1 + new2] == list(range(1, 22))
    assert Counter(card["front"] for card in new1 + new2) == Counter(
        card["front"] for card in deck1 + deck2
    )
    assert len(change.decks) == 2
    assert [lesson["title"] for lesson in lessons] == [
        "Карточки: Спорт и достижения, часть 1",
        "Карточки: Спорт и достижения, часть 2",
    ]


def test_apply_and_rollback_require_the_exact_expected_deck(tmp_path: Path):
    """Same-length editorial changes must make both migration directions no-op.

    The preflight already compares exact JSON.  Repeating that optimistic-lock
    predicate on UPDATE is essential: checking only array length can overwrite a
    deck changed between preflight/apply, or changed after apply/before rollback.
    """
    deck1 = [_card(i, f"word-{i}") for i in range(1, 8)]
    deck2 = [_card(i, f"word-{i}") for i in range(8, 22)]
    _patched, change, _warnings = plan_module(Path("module_B1_7.json"), _module(deck1, deck2))
    emit_sql([change], tmp_path)

    apply_sql = (tmp_path / "item10_card_lessons_2_apply.sql").read_text(encoding="utf-8")
    rollback_sql = (tmp_path / "item10_card_lessons_3_rollback.sql").read_text(encoding="utf-8")
    apply_deck_updates = [line for line in apply_sql.splitlines() if "jsonb_set" in line]
    rollback_deck_updates = [line for line in rollback_sql.splitlines() if "jsonb_set" in line]

    assert len(apply_deck_updates) == len(rollback_deck_updates) == 2
    for statement, (_number, old_cards, _new_cards) in zip(apply_deck_updates, change.decks, strict=True):
        old_json = json.dumps(old_cards, ensure_ascii=False)
        assert f"l.content::jsonb->'cards' = {_dollar(old_json)}::jsonb" in statement
    for statement, (_number, _old_cards, new_cards) in zip(rollback_deck_updates, change.decks, strict=True):
        new_json = json.dumps(new_cards, ensure_ascii=False)
        assert f"l.content::jsonb->'cards' = {_dollar(new_json)}::jsonb" in statement


@pytest.mark.parametrize('title', ['Знакомство', 'Знакомство.'])
def test_reviewed_introductory_a1_is_not_rebalanced_or_moved(title):
    from scripts.move_second_card_lesson import plan_module as move

    source = _module([_card(i, f'word-{i}') for i in range(6)],
                     [_card(i, f'word-{i}') for i in range(6, 20)])
    module = source['module']
    module.update(level='A1', order=1, title=title)
    module['lessons'][0]['title'] = 'Карточки: первые 6 фраз для знакомства'
    module['lessons'][1].update(number=10, title='Карточки: ещё 14 слов и вежливых фраз')
    module['lessons'].insert(1, {'number': 3, 'type': 'writing_prompt', 'title': 'Письмо', 'content': {}})
    pristine = copy.deepcopy(source)
    patched, change, warnings = plan_module(Path('module_A1_1.json'), source)
    assert patched == pristine == source and not change.touched and warnings == []
    patched, changed, warnings = move(Path('module_A1_1.json'), source)
    assert patched == pristine and changed is False and warnings == []


def test_similar_card_layout_in_another_module_still_uses_standard_rebalance():
    source = _module([_card(i, f'word-{i}') for i in range(6)],
                     [_card(i, f'word-{i}') for i in range(6, 20)])
    source['module'].update(level='A1', order=2)
    source['module']['lessons'][1]['number'] = 10
    source['module']['lessons'].insert(1, {'number': 3, 'type': 'writing_prompt', 'title': 'Письмо', 'content': {}})
    patched, change, _ = plan_module(Path('module_A1_2.json'), source)
    assert change.touched
    assert [len(lesson['content']['cards']) for lesson in patched['module']['lessons']
            if lesson['type'] in {'card', 'flashcards'}] == [10, 10]


@pytest.mark.skipif(not CORPUS.exists(), reason="module corpus not present in this checkout")
def test_known_corpus_exceptions_remain_intentional():
    modules = {}
    for path in CORPUS.glob("*.json"):
        module = json.loads(path.read_text(encoding="utf-8"))["module"]
        modules[(module["level"], module["order"])] = module

    for key, duplicated_word in [(('B1', 7), "coach"), (('B2', 1), "mindset")]:
        cards = [
            card
            for lesson in modules[key]["lessons"]
            if lesson["type"] in {"card", "flashcards"}
            for card in lesson["content"]["cards"]
        ]
        assert Counter(card["front"].strip().lower() for card in cards)[duplicated_word] == 2

    c1_titles = [
        lesson["title"]
        for lesson in modules[("C1", 14)]["lessons"]
        if lesson["type"] in {"card", "flashcards"}
    ]
    assert c1_titles == [
        "Карточки: Formal, Business, часть 1",
        "Карточки: Informal, BrE/AmE, Clichés, часть 2",
    ]
