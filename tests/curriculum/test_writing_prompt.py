"""Tests for the writing_prompt lesson type.

Task 19: Writing prompt exercise type.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import (
    CEFRLevel, LessonProgress, Lessons, Module, UserWritingAttempt,
    save_writing_attempt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_writing_lesson(
    db_session,
    *,
    prompt: str = "Describe your daily routine.",
    min_words: int = 30,
    example_response: str | None = None,
    checklist: list[str] | None = None,
) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Writing Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    content: dict = {"prompt": prompt, "min_words": min_words}
    if example_response is not None:
        content["example_response"] = example_response
    if checklist is not None:
        content["checklist"] = checklist
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Writing Prompt Test",
        type="writing_prompt",
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
# Validator tests
# ---------------------------------------------------------------------------

class TestWritingPromptValidator:
    def test_valid_minimal_payload(self):
        from app.curriculum.validators import LessonContentValidator
        ok, err, _ = LessonContentValidator.validate(
            'writing_prompt',
            {'prompt': 'Write about your day.', 'min_words': 50},
        )
        assert ok is True
        assert err is None

    def test_valid_full_payload(self):
        from app.curriculum.validators import LessonContentValidator
        ok, err, _ = LessonContentValidator.validate(
            'writing_prompt',
            {
                'prompt': 'Describe your hobby.',
                'min_words': 80,
                'example_response': 'I enjoy reading books...',
                'checklist': ['Used new words', 'Correct grammar'],
            },
        )
        assert ok is True

    def test_missing_prompt_fails(self):
        from marshmallow import ValidationError
        from app.curriculum.validators import LessonContentValidator
        with pytest.raises(ValidationError):
            LessonContentValidator.validate(
                'writing_prompt',
                {'min_words': 50},
            )

    def test_missing_min_words_fails(self):
        from marshmallow import ValidationError
        from app.curriculum.validators import LessonContentValidator
        with pytest.raises(ValidationError):
            LessonContentValidator.validate(
                'writing_prompt',
                {'prompt': 'Write something.'},
            )

    def test_empty_prompt_fails(self):
        from marshmallow import ValidationError
        from app.curriculum.validators import LessonContentValidator
        with pytest.raises(ValidationError):
            LessonContentValidator.validate(
                'writing_prompt',
                {'prompt': '', 'min_words': 30},
            )


# ---------------------------------------------------------------------------
# Model / save_writing_attempt tests
# ---------------------------------------------------------------------------

class TestUserWritingAttemptModel:
    def test_save_writing_attempt_creates_row(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "Hello world this is my answer.", True, db
        )
        assert attempt.id is not None
        assert attempt.word_count == 6
        assert attempt.checklist_completed is True
        assert attempt.response_text == "Hello world this is my answer."

    def test_word_count_computed_correctly(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "one two three", False, db
        )
        assert attempt.word_count == 3

    def test_empty_text_word_count_zero(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        attempt = save_writing_attempt(test_user.id, lesson.id, "", False, db)
        assert attempt.word_count == 0

    def test_multiple_attempts_per_lesson_allowed(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        attempt1 = save_writing_attempt(test_user.id, lesson.id, "First attempt.", True, db)
        attempt2 = save_writing_attempt(test_user.id, lesson.id, "Second attempt.", True, db)
        db.session.commit()
        rows = db.session.query(UserWritingAttempt).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()
        assert len(rows) == 2
        assert attempt1.id != attempt2.id


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _read_writing_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "writing_prompt.html"
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


class TestWritingPromptTemplate:
    def test_template_exists(self):
        tpl = _read_writing_template()
        assert len(tpl) > 100

    def test_prompt_variable_present(self):
        tpl = _read_writing_template()
        assert "{{ prompt }}" in tpl

    def test_textarea_present(self):
        tpl = _read_writing_template()
        assert "writing-prompt-textarea" in tpl

    def test_checklist_section_present(self):
        tpl = _read_writing_template()
        assert "writing-prompt-checklist" in tpl

    def test_submit_function_present(self):
        tpl = _read_writing_template()
        assert "submitWriting()" in tpl

    def test_word_count_function_present(self):
        tpl = _read_writing_template()
        assert "updateWordCount()" in tpl

    def test_example_response_conditional_block(self):
        tpl = _read_writing_template()
        assert "example_response" in tpl
        assert "example-section" in tpl

    def test_min_words_variable_used(self):
        tpl = _read_writing_template()
        assert "min_words" in tpl

    def test_checklist_loop_present(self):
        tpl = _read_writing_template()
        assert "for item in checklist" in tpl


class TestWritingPromptCSS:
    def test_writing_prompt_lesson_class(self):
        css = _read_design_system_css()
        assert ".writing-prompt-lesson" in css

    def test_writing_prompt_textarea_class(self):
        css = _read_design_system_css()
        assert ".writing-prompt-textarea" in css

    def test_writing_prompt_checklist_class(self):
        css = _read_design_system_css()
        assert ".writing-prompt-checklist" in css

    def test_writing_prompt_checklist_item_class(self):
        css = _read_design_system_css()
        assert ".writing-prompt-checklist-item" in css

    def test_writing_prompt_badge_success_class(self):
        css = _read_design_system_css()
        assert ".writing-prompt-badge--success" in css

    def test_writing_prompt_example_class(self):
        css = _read_design_system_css()
        assert ".writing-prompt-example" in css


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestWritingPromptRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        assert resp.status_code == 200

    def test_get_contains_prompt_text(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, prompt="Talk about your favourite food.")
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        assert "Talk about your favourite food." in resp.get_data(as_text=True)

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_lesson_detail_redirects_to_writing_prompt_route(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "writing-prompt" in resp.headers.get("Location", "")

    def test_example_response_shown_in_template(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(
            db_session, example_response="I usually wake up at 7am..."
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        html = resp.get_data(as_text=True)
        assert "I usually wake up at 7am..." in html

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_writing_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        assert resp.status_code in (302, 401, 403)

    def test_wrong_lesson_type_redirects(self, app, db_session, test_user, client, test_lesson_vocabulary):
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{test_lesson_vocabulary.id}/writing-prompt")
        assert resp.status_code in (302, 400)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestWritingPromptSubmitRoute:
    def _submit(self, client, lesson_id: int, *, response_text: str,
                checklist_completed: bool = True, checked_items: list | None = None):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={
                "response_text": response_text,
                "checklist_completed": checklist_completed,
                "checked_items": checked_items or ["Пункт 1", "Пункт 2"],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )

    def _long_text(self, words: int = 40) -> str:
        return " ".join(["word"] * words)

    def test_submit_saves_writing_attempt(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        self._submit(client, lesson.id, response_text="one two three four five six")
        from app.utils.db import db as _db
        rows = _db.session.query(UserWritingAttempt).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()
        assert len(rows) >= 1

    def test_submit_returns_200(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = self._submit(client, lesson.id, response_text=self._long_text(5))
        assert resp.status_code == 200

    def test_checklist_completion_marks_lesson_done(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        text = " ".join(["word"] * 5)
        self._submit(client, lesson.id, response_text=text, checklist_completed=True)
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_not_enough_words_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=50)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = self._submit(client, lesson.id, response_text="too short", checklist_completed=True)
        data = resp.get_json()
        assert data["completed"] is False
        assert data["meets_min_words"] is False

    def test_checklist_not_completed_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        text = " ".join(["word"] * 5)
        resp = self._submit(client, lesson.id, response_text=text, checklist_completed=False)
        data = resp.get_json()
        assert data["completed"] is False

    def test_example_shown_in_response_on_completion(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(
            db_session, min_words=3, example_response="Sample example here."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = self._submit(
            client, lesson.id,
            response_text="one two three four",
            checklist_completed=True,
        )
        data = resp.get_json()
        assert data["completed"] is True
        assert data.get("example_response") == "Sample example here."

    def test_word_count_returned_in_response(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=3)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = self._submit(client, lesson.id, response_text="one two three four five")
        data = resp.get_json()
        assert data["word_count"] == 5

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_writing_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"response_text": "test", "lesson_type": "writing_prompt"},
        )
        assert resp.status_code in (302, 401, 403)
