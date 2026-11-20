"""Deterministic semantic tables under JSONB-style object key ordering."""

from copy import deepcopy
from itertools import permutations
from uuid import uuid4

import pytest

from app.api.native_lessons import _theory
from app.grammar_lab.routes import _order_theory_cells
from app.grammar_lab.theory_schema import ordered_theory_keys
from tests.api.test_account_deletion import native_app as _native_app


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def test_all_object_key_orders_produce_the_same_labeled_native_row():
    values = {"pronoun": "I", "form": "am", "example": "I am here.", "translation": "Я здесь."}
    expected = {"headers": ["Местоимение", "Форма", "Пример", "Перевод"], "rows": [list(values.values())]}
    for keys in permutations(values):
        row = {key: values[key] for key in keys}
        source = {"sections": [{"table": [row]}]}
        original = deepcopy(source)
        assert _theory(source)[0]["table"] == expected
        assert source == original


def test_explicit_author_column_order_is_preserved_under_scrambled_dict_keys():
    source = {
        "table": {
            "columns": [
                {"key": "example", "label": "Сначала пример"},
                {"key": "translation", "label": "Потом перевод"},
                {"key": "pronoun", "label": "Затем лицо"},
                {"key": "form", "label": "Форма"},
            ],
            "rows": [{"form": "am", "translation": "Я здесь.", "pronoun": "I", "example": "I am here."}],
        }
    }
    assert _theory(source)[0]["table"] == {
        "headers": ["Сначала пример", "Потом перевод", "Затем лицо", "Форма"],
        "rows": [["I am here.", "Я здесь.", "I", "am"]],
    }


def test_word_translation_precedes_example_only_when_example_has_its_own_translation():
    keys = ["example_translation", "translation", "example", "word"]
    assert ordered_theory_keys(keys) == ["word", "translation", "example", "example_translation"]
    assert ordered_theory_keys(["translation", "example", "word"]) == ["word", "example", "translation"]


def test_browser_order_uses_the_same_priorities_and_keeps_unknown_tail_unchanged():
    keys = ["unknown_b", "translation", "example", "form", "unknown_a", "pronoun"]
    row = {key: key for key in keys}
    rendered = _order_theory_cells({"sections": [{"table": [row]}]})
    assert list(rendered["sections"][0]["table"][0]) == ordered_theory_keys(keys)
    assert ordered_theory_keys(keys)[-2:] == ["unknown_b", "unknown_a"]


def test_public_theory_page_keeps_semantic_order_after_shared_constant_extraction(native_app):
    from app.grammar_lab.models import GrammarTopic
    from app.utils.db import db

    # Simulate JSONB's length-based key reordering using a disposable SQLite DB.
    row = {
        "form": "FORM_MARKER",
        "example": "EXAMPLE_MARKER",
        "pronoun": "SUBJECT_MARKER",
        "translation": "TRANSLATION_MARKER",
    }
    topic = GrammarTopic(
        slug="mobile-order-" + uuid4().hex,
        title="Cells",
        title_ru="Ячейки",
        level="A1",
        content={"introduction": "x", "sections": [{"subtitle": "Rules", "table": [row]}]},
    )
    db.session.add(topic)
    db.session.commit()
    db.session.expire_all()
    response = native_app.test_client().get("/grammar-lab/topic/" + topic.slug)
    assert response.status_code == 200
    positions = [
        response.text.index(value)
        for value in ["SUBJECT_MARKER", "FORM_MARKER", "EXAMPLE_MARKER", "TRANSLATION_MARKER"]
    ]
    assert positions == sorted(positions)


def test_public_theory_page_still_escapes_cells_and_excludes_media(native_app):
    from app.grammar_lab.models import GrammarTopic
    from app.utils.db import db

    topic = GrammarTopic(
        slug="mobile-escape-" + uuid4().hex,
        title="Cells",
        title_ru="Ячейки",
        level="A1",
        content={
            "sections": [
                {
                    "subtitle": "Rules",
                    "table": [
                        {
                            "rule": "&lt;img src=x onerror=alert(2121)&gt;",
                            "pattern": "<script>alert(2121)</script>",
                            "audio": "HIDDEN_AUDIO_MARKER",
                        },
                        "NOT_A_ROW_MARKER",
                    ],
                }
            ]
        },
    )
    db.session.add(topic)
    db.session.commit()
    response = native_app.test_client().get("/grammar-lab/topic/" + topic.slug)
    assert response.status_code == 200
    assert "<img src=x onerror=alert(2121)>" not in response.text
    assert "<script>alert(2121)</script>" not in response.text
    assert "&lt;img src=x onerror=alert(2121)&gt;" in response.text
    assert "&lt;script&gt;alert(2121)&lt;/script&gt;" in response.text
    assert "HIDDEN_AUDIO_MARKER" not in response.text and "NOT_A_ROW_MARKER" not in response.text


def test_native_seed_priorities_do_not_change_browser_unknown_column_order():
    keys = ["translation", "short", "pronoun", "full"]
    assert ordered_theory_keys(keys) == ["pronoun", "translation", "short", "full"]
    block = _theory({"table": [{"translation": "Я есть.", "short": "I'm", "pronoun": "I", "full": "I am"}]})[0]
    assert block["table"] == {
        "headers": ["Местоимение", "Полная форма", "Краткая форма", "Перевод"],
        "rows": [["I", "I am", "I'm", "Я есть."]],
    }
    possessive = _theory({"table": [{"translation": "мой", "possessive": "my", "pronoun": "I"}]})[0]
    assert possessive["table"]["headers"] == ["Местоимение", "Притяжательная форма", "Перевод"]
