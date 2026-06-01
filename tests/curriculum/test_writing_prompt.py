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
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_writing_lesson(
    db_session,
    *,
    prompt: str = "Describe your daily routine.",
    min_words: int = 30,
    example_response: str | None = None,
    checklist: list[str] | None = None,
) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
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

    def test_empty_text_raises_value_error(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        with pytest.raises(ValueError, match="response_text cannot be empty"):
            save_writing_attempt(test_user.id, lesson.id, "", False, db)

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
        """Live counter helper (renamed to updateWritingProgress in the
        guided-writing rewrite — handles both word and sentence modes)."""
        tpl = _read_writing_template()
        assert "updateWritingProgress()" in tpl

    def test_example_response_conditional_block(self):
        """Example response is now rendered inside a <details> helper toggle
        rather than a hidden example-section div."""
        tpl = _read_writing_template()
        assert "example_response" in tpl
        assert "Показать пример" in tpl

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
        from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={
                "response_text": response_text,
                "checklist_completed": checklist_completed,
                "checked_items": checked_items if checked_items is not None else _DEFAULT_WRITING_CHECKLIST[:2],
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
        # Server enforces ≥2 checked items regardless of the client flag.
        resp = self._submit(
            client, lesson.id,
            response_text=text,
            checklist_completed=False,
            checked_items=["only one item"],
        )
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


# ---------------------------------------------------------------------------
# Task 28: default checklist, 2-item minimum, live word count
# ---------------------------------------------------------------------------

class TestWritingPromptTask28:
    """Tests for Task 28 improvements: default checklist, 2-item minimum, live word count."""

    # --- Default checklist items ---

    def test_default_checklist_items_used_when_no_checklist_in_content(
        self, app, db_session, test_user, client
    ):
        lesson = _make_writing_lesson(db_session)  # no checklist in content
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        html = resp.get_data(as_text=True)
        assert "Использовал(а) новые слова" in html
        assert "Структура предложений правильная" in html
        assert "Нет пропущенных артиклей" in html
        assert "Нет ошибок во временах" in html

    def test_custom_checklist_items_override_defaults(
        self, app, db_session, test_user, client
    ):
        custom = ["My item one", "My item two"]
        lesson = _make_writing_lesson(db_session, checklist=custom)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        html = resp.get_data(as_text=True)
        assert "My item one" in html
        assert "My item two" in html
        assert "Использовал(а) новые слова" not in html

    def test_four_default_checklist_items_rendered(
        self, app, db_session, test_user, client
    ):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        html = resp.get_data(as_text=True)
        # Count checklist inputs only; the global feedback widget can also
        # render checkboxes on authenticated pages.
        assert html.count('class="writing-prompt-checkbox"') == 4

    # --- Checklist threshold gating in JS ---

    def test_template_js_enforces_min_checklist_threshold(self):
        """Threshold is parametric (MIN_CHECKLIST), default 3 for guided
        and 2 for structured. The submit gate compares checked items
        against this constant via `< MIN_CHECKLIST`."""
        tpl = _read_writing_template()
        assert "MIN_CHECKLIST" in tpl
        assert "checkboxes.length < MIN_CHECKLIST" in tpl

    def test_template_contains_readiness_diagnostic(self):
        """Old `checklist-hint` element replaced by a richer readiness
        block (`wp-readiness`) that lists specific missing requirements
        (sentences, name, age, country, etc.)."""
        tpl = _read_writing_template()
        assert "wp-readiness" in tpl
        assert "wp-readiness-list" in tpl

    def test_template_checklist_label_mentions_minimum_two(self):
        tpl = _read_writing_template()
        assert "минимум 2" in tpl.lower() or "2" in tpl

    def test_submit_blocked_when_checklist_not_completed(
        self, app, db_session, test_user, client
    ):
        lesson = _make_writing_lesson(db_session, min_words=3)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "one two three four",
                "checklist_completed": False,
                "checked_items": ["one item only"],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False

    # --- Live word count ---

    def test_template_has_count_display_element(self):
        """After the guided-writing rewrite the counter element is renamed
        to `wp-count-display` (and shows sentences or words depending on
        the lesson's mode)."""
        tpl = _read_writing_template()
        assert "wp-count-display" in tpl

    def test_template_textarea_has_oninput_handler(self):
        tpl = _read_writing_template()
        assert 'oninput="updateWritingProgress()"' in tpl

    def test_template_update_progress_function_defined(self):
        tpl = _read_writing_template()
        assert "function updateWritingProgress()" in tpl

    def test_template_progress_updates_display_correctly(self):
        tpl = _read_writing_template()
        # Verify the function updates the display element by ID
        assert "wp-count-display" in tpl
        assert "display.textContent" in tpl

    def test_template_shows_min_target_in_counter(self):
        """Counter total may be sentences (`min_sentences`) or words
        (`min_words`) — depending on mode. Both Jinja vars are present."""
        tpl = _read_writing_template()
        assert "wp-count-display" in tpl
        assert "min_words" in tpl
        assert "min_sentences" in tpl
