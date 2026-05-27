"""Render + payload contract tests for the redesigned text-input lessons
(writing_prompt, translation, sentence_completion, sentence_correction).

Task 3 of docs/plans/2026-05-13-modern-lesson-ui-redesign.md:
- Every redesigned template renders with sample content.
- Each template hosts a `.lesson-shell` wrapper plus the shared shell parts.
- The JS payload uses the frozen field names verified against
  docs/design/lesson-frontend-spec.md and the backend submit handlers.
"""
from __future__ import annotations

import uuid

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from tests.conftest import unique_level_code


@pytest.fixture()
def _level(db_session):
    code = unique_level_code()
    level = CEFRLevel(code=code, name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    return level


@pytest.fixture()
def _module(db_session, _level):
    module = Module(
        level_id=_level.id,
        number=1,
        title="Text Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def _make_lesson(db_session, module, *, lesson_type: str, content: dict) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title=f"{lesson_type} test",
        type=lesson_type,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ---------------------------------------------------------------------------
# Shared shell smoke — each lesson template must include the shell taxonomy.
# ---------------------------------------------------------------------------

SHELL_CLASSES = (
    "lesson-shell",
    "lesson-shell__header",
    "lesson-shell__body",
    "lesson-shell__actions",
    "lesson-shell__result",
)


class TestSharedShellRendering:
    def test_writing_prompt_uses_shell(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="writing_prompt",
            content={"prompt": "Describe your day.", "min_words": 5},
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"writing_prompt missing {cls}"

    def test_translation_uses_shell(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="translation",
            content={"russian": "Я люблю кошек", "english": "I love cats"},
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"translation missing {cls}"

    def test_sentence_completion_uses_shell(self, app, db_session, _module, test_user, client):
        items = [{"prompt": "She is...", "answer": "happy"}]
        lesson = _make_lesson(
            db_session, _module, lesson_type="sentence_completion",
            content={"items": items},
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"sentence_completion missing {cls}"

    def test_sentence_correction_uses_shell(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="sentence_correction",
            content={
                "incorrect_sentence": "He go to the store.",
                "correct_sentence": "He goes to the store.",
                "error_type": "verb",
                "explanation": "Subject-verb agreement.",
            },
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"sentence_correction missing {cls}"


# ---------------------------------------------------------------------------
# Payload contract — the JS body must serialise the frozen keys verbatim.
# We assert this against the template source (Jinja-rendered output stays
# tied to the route's variables; the JS literal is identical there).
# ---------------------------------------------------------------------------

def _read_template_source(name: str) -> str:
    from pathlib import Path
    return (
        Path(__file__).parent.parent.parent
        / "app" / "templates" / "curriculum" / "lessons" / name
    ).read_text(encoding="utf-8")


class TestPayloadContracts:
    def test_writing_prompt_payload_fields(self):
        src = _read_template_source("writing_prompt.html")
        assert "response_text:" in src
        assert "checklist_completed:" in src
        assert "checked_items:" in src
        assert "'writing_prompt'" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src

    def test_translation_payload_fields(self):
        """Translation is now a multi-item guided flow with auto-finalize —
        same payload shape as audio_fill_blank / sentence_completion."""
        src = _read_template_source("translation.html")
        assert "answers:" in src
        assert "'translation'" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src

    def test_sentence_completion_payload_fields(self):
        src = _read_template_source("sentence_completion.html")
        assert "answers:" in src
        assert "'sentence_completion'" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src

    def test_sentence_correction_payload_fields(self):
        src = _read_template_source("sentence_correction.html")
        assert "user_answer:" in src
        assert "'sentence_correction'" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src


# ---------------------------------------------------------------------------
# Submission round-trips — verify the backend still accepts the redesigned
# payload shape end-to-end.
# ---------------------------------------------------------------------------

class TestSubmissionRoundTrips:
    def test_writing_prompt_submit_completes(self, app, db_session, _module, test_user, client):
        checklist = ["used new words", "checked tense", "added details"]
        lesson = _make_lesson(
            db_session, _module, lesson_type="writing_prompt",
            content={"prompt": "Describe your day.", "min_words": 3, "checklist": checklist},
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "one two three four five",
                "checklist_completed": True,
                "checked_items": [checklist[0], checklist[1]],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["completed"] is True

    def test_writing_prompt_rejects_invalid_checklist_items(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="writing_prompt",
            content={"prompt": "Describe your day.", "min_words": 3, "checklist": ["a", "b", "c"]},
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "one two three four five",
                "checklist_completed": True,
                "checked_items": ["fake", "values"],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["completed"] is False

    def test_translation_submit_correct(self, app, db_session, _module, test_user, client):
        """Legacy single-item content still accepted; response uses the new
        multi-item contract (passed / correct_items / total_items)."""
        lesson = _make_lesson(
            db_session, _module, lesson_type="translation",
            content={"russian": "Я люблю кошек", "english": "I love cats"},
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "I love cats", "lesson_type": "translation"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert data["correct_items"] == 1

    def test_sentence_completion_submit(self, app, db_session, _module, test_user, client):
        items = [{"prompt": "She is", "answer": "happy"}]
        lesson = _make_lesson(
            db_session, _module, lesson_type="sentence_completion",
            content={"items": items},
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["happy"], "lesson_type": "sentence_completion"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "item_results" in body
        assert body["item_results"][0]["correct"] is True

    def test_sentence_correction_submit(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="sentence_correction",
            content={
                "incorrect_sentence": "He go to school.",
                "correct_sentence": "He goes to school.",
                "error_type": "verb",
                "explanation": "Third-person -s.",
            },
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "user_answer": "He goes to school.",
                "lesson_type": "sentence_correction",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["is_correct"] is True


# ---------------------------------------------------------------------------
# Result badge taxonomy — each template uses the shared `.result-badge`
# classes (or renders them via JS).
# ---------------------------------------------------------------------------

class TestResultBadgeTaxonomy:
    def test_writing_prompt_uses_result_badge(self):
        src = _read_template_source("writing_prompt.html")
        assert "result-badge" in src
        assert "result-badge--correct" in src or "'correct'" in src

    def test_translation_uses_result_badge(self):
        src = _read_template_source("translation.html")
        assert "result-badge" in src

    def test_sentence_completion_uses_result_badge(self):
        src = _read_template_source("sentence_completion.html")
        assert "result-badge" in src

    def test_sentence_correction_uses_result_badge(self):
        src = _read_template_source("sentence_correction.html")
        assert "result-badge" in src


# ---------------------------------------------------------------------------
# Translation hint chips taxonomy — uses `.chip.chip--clickable`.
# ---------------------------------------------------------------------------

class TestTranslationChipTaxonomy:
    def test_chip_classes_present_when_hints(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="translation",
            content={
                "russian": "Я люблю кошек",
                "english": "I love cats",
                "hint_words": ["I", "love", "cats"],
            },
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "chip--clickable" in html
        assert 'aria-pressed="false"' in html


# ---------------------------------------------------------------------------
# Sentence correction option button taxonomy — uses `.option-btn`.
# ---------------------------------------------------------------------------

class TestSentenceCorrectionOptionTaxonomy:
    def test_option_btn_classes_present(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="sentence_correction",
            content={
                "incorrect_sentence": "He go to school.",
                "correct_sentence": "He goes to school.",
                "error_type": "verb",
                "explanation": "Third-person -s.",
                "options": ["He go.", "He goes.", "He gone.", "He going."],
            },
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "option-btn" in html
        assert 'aria-pressed="false"' in html
