"""Tests for collocation display in vocabulary lessons.

Task 30: Collocation display in vocabulary lessons.
Task 44: Verify optional vocabulary UI sections.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import (
    CEFRLevel,
    CulturalNote,
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


# ---------------------------------------------------------------------------
# Task 35: Example sentence carousel tests
# ---------------------------------------------------------------------------

class TestExampleCarouselTemplate:
    def test_carousel_class_in_template(self):
        tpl = _read_vocabulary_template()
        assert "example-carousel" in tpl

    def test_carousel_rendered_for_3_plus_examples(self):
        tpl = _read_vocabulary_template()
        assert "word.examples|length > 2" in tpl

    def test_static_list_for_1_2_examples(self):
        tpl = _read_vocabulary_template()
        assert "word-examples-static" in tpl

    def test_single_example_fallback(self):
        tpl = _read_vocabulary_template()
        assert "word.example" in tpl

    def test_reduced_motion_check_in_js(self):
        tpl = _read_vocabulary_template()
        assert "prefers-reduced-motion" in tpl

    def test_auto_advance_disabled_on_reduced_motion(self):
        tpl = _read_vocabulary_template()
        assert "noMotion" in tpl

    def test_prev_next_buttons_in_template(self):
        tpl = _read_vocabulary_template()
        assert "example-carousel__btn--prev" in tpl
        assert "example-carousel__btn--next" in tpl

    def test_dot_indicators_in_template(self):
        tpl = _read_vocabulary_template()
        assert "example-carousel__dot" in tpl


class TestExampleCarouselCSS:
    def test_example_carousel_class_defined(self):
        css = _read_design_system_css()
        assert ".example-carousel" in css

    def test_example_slide_class_defined(self):
        css = _read_design_system_css()
        assert ".example-slide" in css

    def test_example_slide_active_class_defined(self):
        css = _read_design_system_css()
        assert ".example-slide--active" in css

    def test_carousel_fade_animation_defined(self):
        css = _read_design_system_css()
        assert "carousel-fade" in css

    def test_carousel_dot_active_class_defined(self):
        css = _read_design_system_css()
        assert ".example-carousel__dot--active" in css

    def test_word_examples_static_class_defined(self):
        css = _read_design_system_css()
        assert ".word-examples-static" in css


class TestExampleCarouselRoute:
    def _make_lesson_with_examples(self, db_session, module, count: int) -> "Lessons":
        examples = [
            {"english": f"Example sentence {i}.", "russian": f"Пример {i}."}
            for i in range(1, count + 1)
        ]
        lesson = Lessons(
            module_id=module.id,
            number=99,
            title="Carousel Test",
            type="vocabulary",
            content={
                "words": [
                    {
                        "english": "carousel_test_" + _unique(),
                        "russian": "тест",
                        "examples": examples,
                    }
                ]
            },
        )
        db_session.add(lesson)
        db_session.commit()
        return lesson

    def test_3_examples_shows_carousel(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = self._make_lesson_with_examples(db_session, module, 3)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert 'class="example-carousel' in html
        assert "example-slide" in html

    def test_2_examples_shows_static_list(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = self._make_lesson_with_examples(db_session, module, 2)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-examples-static" in html
        assert 'class="example-carousel' not in html

    def test_1_example_shows_static_list(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = self._make_lesson_with_examples(db_session, module, 1)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-examples-static" in html
        assert 'class="example-carousel' not in html

    def test_carousel_contains_correct_example_count(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = self._make_lesson_with_examples(db_session, module, 4)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        # Each example creates one .example-slide element
        assert html.count("example-slide") >= 4

    def test_no_examples_shows_legacy_example(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "legacyex_" + _unique()
        lesson = Lessons(
            module_id=module.id,
            number=98,
            title="Legacy Example Test",
            type="vocabulary",
            content={
                "words": [
                    {
                        "english": english,
                        "russian": "тест",
                        "example": "She is happy.",
                    }
                ]
            },
        )
        db_session.add(lesson)
        db_session.commit()
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "She is happy." in html
        assert 'class="example-carousel' not in html


# ---------------------------------------------------------------------------
# Task 40: Word etymology tests
# ---------------------------------------------------------------------------

class TestEtymologyTemplate:
    def test_etymology_section_in_template(self):
        tpl = _read_vocabulary_template()
        assert "word-etymology" in tpl

    def test_etymology_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.etymology" in tpl

    def test_etymology_collapsible_details_element(self):
        tpl = _read_vocabulary_template()
        assert "<details" in tpl
        assert "Происхождение слова" in tpl


class TestEtymologyCSS:
    def test_word_etymology_class_defined(self):
        css = _read_design_system_css()
        assert ".word-etymology" in css

    def test_word_etymology_summary_class_defined(self):
        css = _read_design_system_css()
        assert ".word-etymology__summary" in css

    def test_word_etymology_text_class_defined(self):
        css = _read_design_system_css()
        assert ".word-etymology__text" in css


class TestEtymologyRoute:
    def test_word_with_etymology_shows_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "etymword_" + _unique()
        word = _make_collection_word(db_session, english, "этимология-слово")
        word.etymology = "From Latin 'verbum', meaning 'word'."
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-etymology" in html
        assert "From Latin" in html
        assert "Происхождение слова" in html

    def test_word_without_etymology_no_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "noetymword_" + _unique()
        word = _make_collection_word(db_session, english, "без этимологии")
        word.etymology = None
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-etymology" not in html
        assert "Происхождение слова" not in html

    def test_etymology_field_in_model(self):
        from app.words.models import CollectionWords
        assert hasattr(CollectionWords, 'etymology')


# ---------------------------------------------------------------------------
# Task 69: Add words from vocabulary lessons to custom list
# ---------------------------------------------------------------------------

class TestAddToCustomListTemplate:
    def test_add_to_list_button_in_template(self):
        tpl = _read_vocabulary_template()
        assert 'word-add-to-list' in tpl

    def test_add_to_list_dropdown_in_template(self):
        tpl = _read_vocabulary_template()
        assert 'word-add-to-list__dropdown' in tpl

    def test_add_to_list_js_fetch_in_template(self):
        tpl = _read_vocabulary_template()
        assert '/study/api/custom-lists/' in tpl


class TestAddToCustomListAPI:
    def test_word_added_to_list(self, app, db_session, test_user, client):
        from app.study.models import CustomWordList, CustomWordListEntry
        lst = CustomWordList(user_id=test_user.id, name='My List')
        db_session.add(lst)
        db_session.commit()

        _login(client, test_user)
        resp = client.post(
            f'/study/api/custom-lists/{lst.id}/words',
            json={'word': 'river', 'translation': 'река'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['already_existed'] is False
        entry = CustomWordListEntry.query.filter_by(list_id=lst.id, word='river').first()
        assert entry is not None
        assert entry.translation == 'река'

    def test_duplicate_add_is_idempotent(self, app, db_session, test_user, client):
        from app.study.models import CustomWordList, CustomWordListEntry
        lst = CustomWordList(user_id=test_user.id, name='My List')
        db_session.add(lst)
        db_session.commit()
        entry = CustomWordListEntry(list_id=lst.id, word='stone', translation='камень')
        db_session.add(entry)
        db_session.commit()

        _login(client, test_user)
        resp = client.post(
            f'/study/api/custom-lists/{lst.id}/words',
            json={'word': 'stone', 'translation': 'камень'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['already_existed'] is True
        count = CustomWordListEntry.query.filter_by(list_id=lst.id, word='stone').count()
        assert count == 1

    def test_403_for_other_user_list(self, app, db_session, test_user, client):
        from app.auth.models import User
        from app.study.models import CustomWordList
        other = User(
            email=f'other_{_unique()}@test.com',
            username=f'other_{_unique()}',
            onboarding_completed=True,
        )
        other.set_password('pass123')
        db_session.add(other)
        db_session.commit()
        lst = CustomWordList(user_id=other.id, name='Other List')
        db_session.add(lst)
        db_session.commit()

        _login(client, test_user)
        resp = client.post(
            f'/study/api/custom-lists/{lst.id}/words',
            json={'word': 'cat', 'translation': 'кошка'},
        )
        assert resp.status_code == 403

    def test_vocabulary_route_passes_user_lists(self, app, db_session, test_user, client):
        from app.study.models import CustomWordList
        lst = CustomWordList(user_id=test_user.id, name='Interesting Words')
        db_session.add(lst)
        db_session.commit()

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = 'listtest_' + _unique()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f'/curriculum/lesson/{lesson.id}/vocabulary')
        html = resp.get_data(as_text=True)
        assert 'Interesting Words' in html
        assert 'word-add-to-list' in html

    def test_list_selector_shows_user_lists_only(self, app, db_session, test_user, client):
        from app.auth.models import User
        from app.study.models import CustomWordList
        other = User(
            email=f'other_{_unique()}@test.com',
            username=f'other_{_unique()}',
            onboarding_completed=True,
        )
        other.set_password('pass123')
        db_session.add(other)
        db_session.commit()
        other_lst = CustomWordList(user_id=other.id, name='Secret Other List')
        db_session.add(other_lst)
        my_lst = CustomWordList(user_id=test_user.id, name='My Own List')
        db_session.add(my_lst)
        db_session.commit()

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = 'listtest2_' + _unique()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f'/curriculum/lesson/{lesson.id}/vocabulary')
        html = resp.get_data(as_text=True)
        assert 'My Own List' in html
        assert 'Secret Other List' not in html


# ---------------------------------------------------------------------------
# Task 44: Cultural note section tests
# ---------------------------------------------------------------------------

class TestCulturalNoteTemplate:
    def test_cultural_note_section_in_template(self):
        tpl = _read_vocabulary_template()
        assert "word-cultural-note" in tpl

    def test_cultural_note_conditionally_rendered(self):
        tpl = _read_vocabulary_template()
        assert "word.cultural_notes" in tpl

    def test_cultural_note_collapsible_details(self):
        tpl = _read_vocabulary_template()
        assert "Культурный контекст" in tpl


class TestCulturalNoteCSS:
    def test_word_cultural_note_class_defined(self):
        css = _read_design_system_css()
        assert ".word-cultural-note" in css


class TestCulturalNoteRoute:
    def test_word_with_cultural_note_shows_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "cultword_" + _unique()
        word = _make_collection_word(db_session, english, "культурное-слово")
        note = CulturalNote(word_id=word.id, note="Used in formal British contexts.", context="formal")
        db_session.add(note)
        db_session.commit()
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-cultural-note" in html
        assert "Used in formal British contexts." in html
        assert "Культурный контекст" in html

    def test_word_without_cultural_note_no_section(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "nocultword_" + _unique()
        _make_collection_word(db_session, english, "без культурной заметки")
        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert "word-cultural-note" not in html
        assert "Культурный контекст" not in html


# ---------------------------------------------------------------------------
# Task 44: All optional sections shown for fully enriched word
# ---------------------------------------------------------------------------

class TestAllOptionalSections:
    def test_fully_enriched_word_shows_all_optional_sections(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "enriched_" + _unique()
        word = _make_collection_word(db_session, english, "обогащённое слово")
        word.ipa_transcription = "ɪnˈrɪtʃt"
        word.synonyms = ["enhanced", "augmented"]
        word.antonyms = ["plain", "bare"]
        word.etymology = "From Latin 'enrichire'."
        word.frequency_band = 1
        db_session.commit()

        collocation = WordCollocation(
            word_id=word.id,
            collocation_phrase="enriched " + _unique(),
            translation="обогащённый",
        )
        db_session.add(collocation)

        cultural = CulturalNote(
            word_id=word.id,
            note="Used in scientific writing.",
            context="academic",
        )
        db_session.add(cultural)
        db_session.commit()

        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200

        assert "word-ipa" in html
        assert "ɪnˈrɪtʃt" in html
        assert "freq-badge--1" in html
        assert "word-synonyms" in html
        assert "enhanced" in html
        assert "word-antonyms" in html
        assert "plain" in html
        assert "word-etymology" in html
        assert "Latin" in html
        assert "word-cultural-note" in html
        assert "Used in scientific writing." in html
        assert "word-collocations" in html
        assert collocation.collocation_phrase in html


# ---------------------------------------------------------------------------
# Task 44: No empty labels when metadata is missing
# ---------------------------------------------------------------------------

class TestNoEmptyLabels:
    def test_word_with_no_optional_metadata_has_no_optional_sections(
        self, app, db_session, test_user, client
    ):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "bare_" + _unique()
        word = _make_collection_word(db_session, english, "простое слово")
        word.ipa_transcription = None
        word.synonyms = None
        word.antonyms = None
        word.etymology = None
        word.frequency_band = None
        db_session.commit()

        lesson = _make_vocab_lesson(db_session, module, english)

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200

        assert "word-ipa" not in html
        assert "freq-badge--1" not in html
        assert "freq-badge--2" not in html
        assert "freq-badge--3" not in html
        assert "word-synonyms" not in html
        assert "word-antonyms" not in html
        assert "word-etymology" not in html
        assert "word-cultural-note" not in html
        assert "word-collocations" not in html
        assert "Синонимы:" not in html
        assert "Антонимы:" not in html


# ---------------------------------------------------------------------------
# Task 44: Flashcard lesson type receives frequency data
# ---------------------------------------------------------------------------

class TestFlashcardFrequency:
    def test_flashcard_lesson_shows_frequency_badge(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "flashfreq_" + _unique()
        word = _make_collection_word(db_session, english, "флэшкарта")
        word.frequency_band = 2
        db_session.commit()

        lesson = Lessons(
            module_id=module.id,
            number=2,
            title="Flashcard Freq Test",
            type="flashcards",
            content={"words": [{"english": english, "russian": "флэшкарта"}]},
        )
        db_session.add(lesson)
        db_session.commit()

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "freq-badge--2" in html

    def test_flashcard_lesson_no_badge_without_frequency(self, app, db_session, test_user, client):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        english = "flashnofreq_" + _unique()
        word = _make_collection_word(db_session, english, "без частоты")
        word.frequency_band = None
        db_session.commit()

        lesson = Lessons(
            module_id=module.id,
            number=3,
            title="Flashcard No Freq Test",
            type="flashcards",
            content={"words": [{"english": english, "russian": "без частоты"}]},
        )
        db_session.add(lesson)
        db_session.commit()

        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/vocabulary")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "freq-badge--1" not in html
        assert "freq-badge--2" not in html
        assert "freq-badge--3" not in html
