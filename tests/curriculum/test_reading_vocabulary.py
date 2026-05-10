"""Tests for click-to-define vocabulary in reading/text lessons.

Task 36: Click-to-define vocabulary in reading passages.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique() -> str:
    return uuid.uuid4().hex[:8]


def _read_text_template() -> str:
    p = Path(__file__).parent.parent.parent / "app" / "templates" / "curriculum" / "lessons" / "text.html"
    return p.read_text(encoding="utf-8")


def _read_design_system_css() -> str:
    p = Path(__file__).parent.parent.parent / "app" / "static" / "css" / "design-system.css"
    return p.read_text(encoding="utf-8")


def _make_level(db_session) -> CEFRLevel:
    level = CEFRLevel(
        code=uuid.uuid4().hex[:2].upper(),
        name="TestLevel",
        description="d",
        order=1,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level) -> Module:
    module = Module(
        level_id=level.id,
        number=1,
        title="Test Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_word(db_session, english: str, russian: str = "слово") -> CollectionWords:
    word = CollectionWords(
        english_word=english,
        russian_word=russian,
        level="B1",
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_text_lesson(db_session, module, vocabulary=None) -> Lessons:
    content = {
        "text": "The quick brown fox jumps over the lazy dog.",
        "type": "text",
    }
    if vocabulary:
        content["vocabulary"] = vocabulary
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Reading Test",
        type="text",
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, test_user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(test_user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestReadingVocabularyTemplate:
    """Tests that verify the template has vocab tooltip markup."""

    def test_vocab_tooltip_div_present(self):
        html = _read_text_template()
        assert 'id="vocabTooltip"' in html

    def test_vocab_tooltip_word_span_present(self):
        html = _read_text_template()
        assert 'id="vocabTooltipWord"' in html

    def test_vocab_tooltip_translation_div_present(self):
        html = _read_text_template()
        assert 'id="vocabTooltipTranslation"' in html

    def test_vocab_tooltip_close_button_present(self):
        html = _read_text_template()
        assert 'id="vocabTooltipClose"' in html

    def test_lesson_vocab_data_script_present(self):
        html = _read_text_template()
        assert 'id="lessonVocabData"' in html

    def test_vocab_js_data_tojson_in_template(self):
        html = _read_text_template()
        assert 'vocab_js_data' in html

    def test_vocab_word_wrapping_js_present(self):
        html = _read_text_template()
        assert 'vocab-word' in html
        assert '_wrapVocabInNode' in html

    def test_track_vocab_lookup_function_present(self):
        html = _read_text_template()
        assert '_trackVocabLookup' in html

    def test_vocab_lookup_event_type_in_js(self):
        html = _read_text_template()
        assert "vocab_lookup" in html


# ---------------------------------------------------------------------------
# CSS tests
# ---------------------------------------------------------------------------

class TestReadingVocabularyCSS:
    """Tests that verify CSS classes for vocab word and tooltip are defined."""

    def test_vocab_word_span_selector_in_css(self):
        css = _read_design_system_css()
        assert 'span.vocab-word' in css

    def test_vocab_word_dotted_underline_in_css(self):
        css = _read_design_system_css()
        assert 'underline dotted' in css

    def test_vocab_tooltip_class_in_css(self):
        css = _read_design_system_css()
        assert '.vocab-tooltip' in css

    def test_vocab_tooltip_visible_class_in_css(self):
        css = _read_design_system_css()
        assert '.vocab-tooltip--visible' in css

    def test_vocab_tooltip_has_z_index(self):
        css = _read_design_system_css()
        assert 'z-index' in css

    def test_vocab_word_active_class_in_css(self):
        css = _read_design_system_css()
        assert '.vocab-word--active' in css


# ---------------------------------------------------------------------------
# Route + service tests
# ---------------------------------------------------------------------------

class TestBuildVocabJsData:
    """Unit tests for _build_vocab_js_data helper."""

    def test_empty_vocabulary_returns_empty(self, db_session):
        from app.curriculum.routes.vocabulary_lessons import _build_vocab_js_data
        result = _build_vocab_js_data([])
        assert result == []

    def test_vocab_with_known_word_returns_word_id(self, db_session):
        from app.curriculum.routes.vocabulary_lessons import _build_vocab_js_data
        word = _make_word(db_session, f"hello_{_unique()}", "привет")
        vocabulary = [{"word": word.english_word, "translation": "привет"}]
        result = _build_vocab_js_data(vocabulary)
        assert len(result) == 1
        assert result[0]["word"] == word.english_word
        assert result[0]["word_id"] == word.id
        assert result[0]["translation"] == "привет"

    def test_vocab_with_unknown_word_has_none_word_id(self, db_session):
        from app.curriculum.routes.vocabulary_lessons import _build_vocab_js_data
        vocabulary = [{"word": f"nonexistent_{_unique()}", "translation": "неизвестно"}]
        result = _build_vocab_js_data(vocabulary)
        assert len(result) == 1
        assert result[0]["word_id"] is None

    def test_multiple_vocab_items(self, db_session):
        from app.curriculum.routes.vocabulary_lessons import _build_vocab_js_data
        w1 = _make_word(db_session, f"apple_{_unique()}", "яблоко")
        w2 = _make_word(db_session, f"book_{_unique()}", "книга")
        vocabulary = [
            {"word": w1.english_word, "translation": "яблоко"},
            {"word": w2.english_word, "translation": "книга"},
        ]
        result = _build_vocab_js_data(vocabulary)
        assert len(result) == 2
        ids = {r["word_id"] for r in result}
        assert w1.id in ids
        assert w2.id in ids

    def test_vocab_item_without_word_key_handled(self, db_session):
        from app.curriculum.routes.vocabulary_lessons import _build_vocab_js_data
        vocabulary = [{"translation": "что-то"}]  # no "word" key
        result = _build_vocab_js_data(vocabulary)
        assert len(result) == 1
        assert result[0]["word"] == ""
        assert result[0]["word_id"] is None


class TestTextLessonVocabData:
    """Integration tests: route passes vocab_js_data to template."""

    def test_text_lesson_with_vocab_renders_lesson_vocab_data_script(
        self, client, db_session, test_user
    ):
        _login(client, test_user)
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        word = _make_word(db_session, f"freedom_{_unique()}", "свобода")
        lesson = _make_text_lesson(
            db_session,
            module,
            vocabulary=[{"word": word.english_word, "translation": "свобода"}],
        )

        resp = client.get(f"/curriculum/lesson/{lesson.id}/text")
        assert resp.status_code == 200
        data = resp.data.decode("utf-8")
        assert "lessonVocabData" in data
        # The word should be in the JSON
        assert word.english_word in data

    def test_text_lesson_without_vocab_does_not_render_vocab_script(
        self, client, db_session, test_user
    ):
        _login(client, test_user)
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_text_lesson(db_session, module, vocabulary=None)

        resp = client.get(f"/curriculum/lesson/{lesson.id}/text")
        assert resp.status_code == 200
        data = resp.data.decode("utf-8")
        # With no vocabulary, the data JSON element is not rendered (the JS tag is always present)
        assert 'id="lessonVocabData"' not in data

    def test_text_lesson_vocab_data_contains_word_id(
        self, client, db_session, test_user
    ):
        _login(client, test_user)
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        word = _make_word(db_session, f"justice_{_unique()}", "справедливость")
        lesson = _make_text_lesson(
            db_session,
            module,
            vocabulary=[{"word": word.english_word, "translation": "справедливость"}],
        )

        resp = client.get(f"/curriculum/lesson/{lesson.id}/text")
        assert resp.status_code == 200
        data = resp.data.decode("utf-8")
        # Extract the JSON from the script tag
        start = data.find('<script type="application/json" id="lessonVocabData">')
        assert start != -1
        start = data.find('>', start) + 1
        end = data.find('</script>', start)
        vocab_json = json.loads(data[start:end])
        assert len(vocab_json) == 1
        assert vocab_json[0]["word_id"] == word.id


# ---------------------------------------------------------------------------
# Events endpoint: vocab_lookup accepted
# ---------------------------------------------------------------------------

class TestVocabLookupEvent:
    """Tests that vocab_lookup event is accepted by /api/daily-plan/events."""

    def test_vocab_lookup_event_accepted(self, client, test_user):
        _login(client, test_user)
        resp = client.post(
            "/api/daily-plan/events",
            json={"event_type": "vocab_lookup"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["event_type"] == "vocab_lookup"

    def test_vocab_lookup_event_with_word_id_accepted(self, client, test_user):
        _login(client, test_user)
        resp = client.post(
            "/api/daily-plan/events",
            json={"event_type": "vocab_lookup", "step_kind": "42"},
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_unknown_event_type_rejected(self, client, test_user):
        _login(client, test_user)
        resp = client.post(
            "/api/daily-plan/events",
            json={"event_type": "not_a_real_event"},
            content_type="application/json",
        )
        assert resp.status_code == 400
