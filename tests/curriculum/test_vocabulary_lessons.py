"""Tests for collocation display in vocabulary lessons.

Task 30: Collocation display in vocabulary lessons.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import (
    CEFRLevel,
    Lessons,
    Module,
    WordCollocation,
)
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique() -> str:
    return uuid.uuid4().hex[:8]


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


def _make_collection_word(db_session, english: str, russian: str = "слово") -> CollectionWords:
    word = CollectionWords(
        english_word=english,
        russian_word=russian,
        level="B1",
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_vocab_lesson(db_session, module, word_english: str) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Vocab Test",
        type="vocabulary",
        content={"words": [{"english": word_english, "russian": "тест"}]},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _read_vocabulary_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "vocabulary.html"
    )
    return p.read_text(encoding="utf-8")


def _read_design_system_css() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "static"
        / "css"
        / "design-system.css"
    )
    return p.read_text(encoding="utf-8")


class TestVocabularyTemplate:
    def test_collocation_pills_section_in_template(self):
        tpl = _read_vocabulary_template()
        assert "word-collocations" in tpl

    def test_collocation_pill_class_in_template(self):
        tpl = _read_vocabulary_template()
        assert "collocation-pill" in tpl

    def test_collocations_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.collocations" in tpl

    def test_collocation_phrase_rendered(self):
        tpl = _read_vocabulary_template()
        assert "col.phrase" in tpl

    def test_collocation_translation_as_title(self):
        tpl = _read_vocabulary_template()
        assert "col.translation" in tpl


class TestVocabularyCSS:
    def test_collocation_pill_class_defined(self):
        css = _read_design_system_css()
        assert ".collocation-pill" in css

    def test_word_collocations_class_defined(self):
        css = _read_design_system_css()
        assert ".word-collocations" in css


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------

class TestVocabularyLessonRoute:
    def test_route_returns_200(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_vocab_lesson(db_session, module, "hello_" + _unique())
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        assert resp.status_code == 200

    def test_word_with_collocations_shows_pills(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "testword_" + _unique()
        word = _make_collection_word(db_session, english, "тест")
        lesson = _make_vocab_lesson(db_session, module, english)
        collocation = WordCollocation(
            word_id=word.id,
            collocation_phrase="make a " + _unique(),
            translation="сделать тест",
        )
        db_session.add(collocation)
        db_session.commit()

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "collocation-pill" in html
        assert collocation.collocation_phrase in html

    def test_word_without_collocations_no_pill_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "nocolword_" + _unique()
        _make_collection_word(db_session, english, "без коллокаций")
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-collocations" not in html

    def test_word_not_in_db_no_pill_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_vocab_lesson(db_session, module, "unknownword_" + _unique())

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-collocations" not in html

    def test_unauthenticated_redirects(self, app, db_session, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_vocab_lesson(db_session, module, "word_" + _unique())
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        assert resp.status_code in (302, 401, 403)

    def test_word_with_ipa_shows_transcription(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "ipaword_" + _unique()
        word = _make_collection_word(db_session, english, "слово с ипа")
        word.ipa_transcription = "wɜːrd"
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-ipa" in html
        assert "wɜːrd" in html

    def test_word_without_ipa_no_ipa_element(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "noipaword_" + _unique()
        _make_collection_word(db_session, english, "без ипа")
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-ipa" not in html


class TestIPATemplate:
    def test_ipa_element_in_template(self):
        tpl = _read_vocabulary_template()
        assert "word-ipa" in tpl

    def test_ipa_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.ipa_transcription" in tpl

    def test_ipa_wrapped_in_slashes(self):
        tpl = _read_vocabulary_template()
        assert "/{{ word.ipa_transcription }}/" in tpl


class TestIPACSS:
    def test_word_ipa_class_defined(self):
        css = _read_design_system_css()
        assert ".word-ipa" in css

    def test_word_ipa_uses_secondary_color(self):
        css = _read_design_system_css()
        assert "word-ipa" in css and "color-text-secondary" in css

    def test_word_ipa_is_italic(self):
        css = _read_design_system_css()
        ipa_idx = css.find(".word-ipa")
        block_end = css.find("}", ipa_idx)
        block = css[ipa_idx:block_end]
        assert "italic" in block


# ---------------------------------------------------------------------------
# Task 33: Synonym and antonym tests
# ---------------------------------------------------------------------------

class TestSynonymAntonymTemplate:
    def test_synonyms_section_in_template(self):
        tpl = _read_vocabulary_template()
        assert "word-synonyms" in tpl

    def test_antonyms_section_in_template(self):
        tpl = _read_vocabulary_template()
        assert "word-antonyms" in tpl

    def test_synonyms_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.synonyms" in tpl

    def test_antonyms_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.antonyms" in tpl


class TestSynonymAntonymCSS:
    def test_word_synonyms_class_defined(self):
        css = _read_design_system_css()
        assert ".word-synonyms" in css

    def test_word_antonyms_class_defined(self):
        css = _read_design_system_css()
        assert ".word-antonyms" in css


class TestSynonymAntonymRoute:
    def test_word_with_synonyms_shows_them(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "synword_" + _unique()
        word = _make_collection_word(db_session, english, "синоним-слово")
        word.synonyms = ["big", "large"]
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-synonyms" in html
        assert "big" in html
        assert "large" in html

    def test_word_with_antonyms_shows_them(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "antword_" + _unique()
        word = _make_collection_word(db_session, english, "антоним-слово")
        word.antonyms = ["small", "tiny"]
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-antonyms" in html
        assert "small" in html
        assert "tiny" in html

    def test_word_without_synonyms_no_synonyms_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "nosynword_" + _unique()
        word = _make_collection_word(db_session, english, "без синонимов")
        word.synonyms = None
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-synonyms" not in html

    def test_word_without_antonyms_no_antonyms_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "noantword_" + _unique()
        word = _make_collection_word(db_session, english, "без антонимов")
        word.antonyms = None
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-antonyms" not in html

    def test_migration_columns_exist_in_model(self):
        from app.words.models import CollectionWords
        assert hasattr(CollectionWords, 'synonyms')
        assert hasattr(CollectionWords, 'antonyms')


# ---------------------------------------------------------------------------
# Task 34: Word frequency band tests
# ---------------------------------------------------------------------------

class TestFrequencyBandTemplate:
    def test_freq_badge_in_template(self):
        tpl = _read_vocabulary_template()
        assert "freq-badge" in tpl

    def test_freq_badge_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.frequency_band" in tpl

    def test_freq_badge_band1_label(self):
        tpl = _read_vocabulary_template()
        assert "freq-badge--1" in tpl

    def test_freq_badge_band2_label(self):
        tpl = _read_vocabulary_template()
        assert "freq-badge--2" in tpl

    def test_freq_badge_band3_label(self):
        tpl = _read_vocabulary_template()
        assert "freq-badge--3" in tpl


class TestFrequencyBandCSS:
    def test_freq_badge_base_class_defined(self):
        css = _read_design_system_css()
        assert ".freq-badge" in css

    def test_freq_badge_1_green(self):
        css = _read_design_system_css()
        assert ".freq-badge--1" in css

    def test_freq_badge_2_blue(self):
        css = _read_design_system_css()
        assert ".freq-badge--2" in css

    def test_freq_badge_3_gray(self):
        css = _read_design_system_css()
        assert ".freq-badge--3" in css


class TestFrequencyBandRoute:
    def test_word_band1_shows_badge(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "freqword1_" + _unique()
        word = _make_collection_word(db_session, english, "частое слово")
        word.frequency_band = 1
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "freq-badge--1" in html

    def test_word_band2_shows_badge(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "freqword2_" + _unique()
        word = _make_collection_word(db_session, english, "среднее слово")
        word.frequency_band = 2
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "freq-badge--2" in html

    def test_word_band3_shows_badge(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "freqword3_" + _unique()
        word = _make_collection_word(db_session, english, "редкое слово")
        word.frequency_band = 3
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "freq-badge--3" in html

    def test_word_null_band_no_badge(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "freqnull_" + _unique()
        word = _make_collection_word(db_session, english, "неизвестно")
        word.frequency_band = None
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "freq-badge--1" not in html
        assert "freq-badge--2" not in html
        assert "freq-badge--3" not in html

    def test_frequency_band_in_model(self):
        from app.words.models import CollectionWords
        assert hasattr(CollectionWords, 'frequency_band')
