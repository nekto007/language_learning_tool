"""Tests for the translation lesson template, route, and grading integration.

Task 17: Translation lesson template.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_translation_lesson(
    db_session,
    *,
    russian: str = "Я люблю кошек",
    english: str = "I love cats",
    hint_words=None,
) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Translation Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    content = {"russian": russian, "english": english}
    if hint_words is not None:
        content["hint_words"] = hint_words
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Translation Test",
        type="translation",
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Template content tests
# ---------------------------------------------------------------------------

def _read_translation_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "translation.html"
    )
    return p.read_text(encoding="utf-8")


class TestTranslationTemplate:
    def test_template_exists(self):
        tpl = _read_translation_template()
        assert len(tpl) > 100

    def test_russian_source_variable_present(self):
        tpl = _read_translation_template()
        assert "{{ russian }}" in tpl

    def test_input_element_present(self):
        tpl = _read_translation_template()
        assert 'id="translation-answer"' in tpl
        assert 'type="text"' in tpl

    def test_submit_button_present(self):
        tpl = _read_translation_template()
        assert "submitTranslation()" in tpl

    def test_hint_words_section_conditionally_rendered(self):
        tpl = _read_translation_template()
        assert "hint_words" in tpl
        assert "translation-chips" in tpl

    def test_correct_answer_reveal_present(self):
        tpl = _read_translation_template()
        assert "correct-answer-reveal" in tpl

    def test_js_show_result_function_present(self):
        tpl = _read_translation_template()
        assert "function showResult(" in tpl

    def test_result_badge_container(self):
        tpl = _read_translation_template()
        assert 'id="result-badge"' in tpl

    def test_next_lesson_area_present(self):
        tpl = _read_translation_template()
        assert "translation-next-area" in tpl

    def test_enter_key_submits(self):
        tpl = _read_translation_template()
        assert "Enter" in tpl

    def test_chip_insert_function(self):
        tpl = _read_translation_template()
        assert "function insertChip(" in tpl


# ---------------------------------------------------------------------------
# CSS tests
# ---------------------------------------------------------------------------

def _read_design_system_css() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "static"
        / "css"
        / "design-system.css"
    )
    return p.read_text(encoding="utf-8")


class TestTranslationCSS:
    def test_translation_input_class_defined(self):
        css = _read_design_system_css()
        assert ".translation-input {" in css or ".translation-input{" in css

    def test_translation_input_correct_defined(self):
        css = _read_design_system_css()
        assert ".translation-input--correct" in css

    def test_translation_input_incorrect_defined(self):
        css = _read_design_system_css()
        assert ".translation-input--incorrect" in css

    def test_translation_chips_class_defined(self):
        css = _read_design_system_css()
        assert ".translation-chips" in css

    def test_translation_chip_class_defined(self):
        css = _read_design_system_css()
        assert ".translation-chip" in css

    def test_translation_badge_correct_defined(self):
        css = _read_design_system_css()
        assert ".translation-badge--correct" in css

    def test_translation_badge_incorrect_defined(self):
        css = _read_design_system_css()
        assert ".translation-badge--incorrect" in css


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestTranslationLessonRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert resp.status_code == 200

    def test_get_contains_russian_text(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session, russian="Я люблю кошек")
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert "Я люблю кошек" in resp.get_data(as_text=True)

    def test_get_redirects_wrong_type(self, app, db_session, test_user, client, test_lesson_vocabulary):
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{test_lesson_vocabulary.id}/translation")
        assert resp.status_code in (302, 400)

    def test_lesson_detail_redirects_to_translation_route(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "translation" in resp.headers.get("Location", "")

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_get_shows_hint_words_when_present(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(
            db_session, hint_words=["I", "love", "cats"]
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        html = resp.get_data(as_text=True)
        assert "translation-chips" in html
        assert "love" in html

    def test_get_no_hint_section_when_no_hint_words(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        html = resp.get_data(as_text=True)
        # chips section only rendered when hint_words is truthy
        assert "translation-chips-section" not in html

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_translation_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert resp.status_code in (302, 401, 403)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestTranslationSubmitRoute:
    def _submit(self, client, lesson_id: int, user_answer: str):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"user_answer": user_answer, "lesson_type": "translation"},
            content_type="application/json",
        )

    def test_correct_answer_returns_is_correct_true(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session, english="I love cats")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = self._submit(client, lesson.id, "I love cats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_correct"] is True

    def test_wrong_answer_returns_is_correct_false(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session, english="I love cats")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = self._submit(client, lesson.id, "She hates dogs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_correct"] is False

    def test_wrong_answer_includes_correct_answer(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session, english="I love cats")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = self._submit(client, lesson.id, "wrong answer here")
        data = resp.get_json()
        assert data.get("correct_answer") == "I love cats"

    def test_correct_answer_marks_progress_completed(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session, english="I love cats")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        self._submit(client, lesson.id, "I love cats")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_wrong_answer_does_not_mark_completed(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session, english="I love cats")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        self._submit(client, lesson.id, "totally wrong")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status != "completed"

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_translation_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "hello", "lesson_type": "translation"},
        )
        assert resp.status_code in (302, 401, 403)
