"""Render + payload contract tests for the redesigned audio lessons
(shadow_reading, audio_fill_blank, pronunciation).

Task 4 of docs/plans/2026-05-13-modern-lesson-ui-redesign.md:
- Every redesigned template renders with sample content.
- Each template hosts a `.lesson-shell` wrapper plus the shared shell parts.
- The JS payload uses the frozen field names verified against
  docs/design/lesson-frontend-spec.md and the backend submit handlers.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from tests.conftest import unique_level_code


SHELL_CLASSES = (
    "lesson-shell",
    "lesson-shell__header",
    "lesson-shell__body",
    "lesson-shell__actions",
    "lesson-shell__result",
)


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
        title="Audio Module",
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


def _read_template_source(name: str) -> str:
    return (
        Path(__file__).parent.parent.parent
        / "app" / "templates" / "curriculum" / "lessons" / name
    ).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared shell rendering
# ---------------------------------------------------------------------------

class TestSharedShellRendering:
    def test_shadow_reading_uses_shell(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="shadow_reading",
            content={
                "audio_url": "/audio/sr.mp3",
                "text": "Hello world.",
                "translation": "Привет мир.",
            },
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"shadow_reading missing {cls}"

    def test_audio_fill_blank_uses_shell(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="audio_fill_blank",
            content={
                "audio_url": "/audio/afb.mp3",
                "items": [
                    {"text_with_gap": "She ___ to school.", "answer": "goes"},
                    {"text_with_gap": "I ___ books.", "answer": "read",
                     "options": ["read", "reads", "reading"]},
                ],
            },
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"audio_fill_blank missing {cls}"

    def test_pronunciation_uses_shell(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(
            db_session, _module, lesson_type="pronunciation",
            content={"items": [{"word": "hello"}, {"word": "world"}]},
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for cls in SHELL_CLASSES:
            assert cls in html, f"pronunciation missing {cls}"


# ---------------------------------------------------------------------------
# Result badge taxonomy
# ---------------------------------------------------------------------------

class TestResultBadgeTaxonomy:
    def test_shadow_reading_uses_result_badge(self):
        src = _read_template_source("shadow_reading.html")
        assert "result-badge" in src

    def test_audio_fill_blank_uses_result_badge(self):
        src = _read_template_source("audio_fill_blank.html")
        assert "result-badge" in src

    def test_pronunciation_uses_result_badge(self):
        src = _read_template_source("pronunciation.html")
        assert "result-badge" in src


# ---------------------------------------------------------------------------
# Option-btn taxonomy (audio_fill_blank options mode)
# ---------------------------------------------------------------------------

class TestOptionBtnTaxonomy:
    def test_audio_fill_blank_option_btn_present(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(
            db_session, _module, lesson_type="audio_fill_blank",
            content={
                "audio_url": "/audio/afb.mp3",
                "items": [
                    {"text_with_gap": "She ___ to school.", "answer": "goes",
                     "options": ["go", "goes", "going"]},
                ],
            },
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        html = resp.get_data(as_text=True)
        assert "option-btn" in html
        assert 'aria-pressed="false"' in html


# ---------------------------------------------------------------------------
# Frozen JS payload contract — verified against the template source
# (the JS literal is identical regardless of route variables).
# ---------------------------------------------------------------------------

class TestPayloadContracts:
    def test_shadow_reading_payload_fields(self):
        src = _read_template_source("shadow_reading.html")
        assert "self_assessed:" in src
        assert "'shadow_reading'" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src

    def test_audio_fill_blank_payload_fields(self):
        src = _read_template_source("audio_fill_blank.html")
        assert "answers:" in src
        assert "'audio_fill_blank'" in src
        assert "replay_count:" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src

    def test_pronunciation_payload_fields(self):
        src = _read_template_source("pronunciation.html")
        # Per-item attempt
        assert "recognized_text:" in src
        assert "target_word:" in src
        assert "'pronunciation'" in src
        # Finish payload
        assert "finish: true" in src
        # Self-assess
        assert "self_assessed: true" in src
        assert "/curriculum/api/lesson/${lessonId}/submit" in src


# ---------------------------------------------------------------------------
# Submission round-trips
# ---------------------------------------------------------------------------

class TestSubmissionRoundTrips:
    def test_shadow_reading_submit_self_assessed(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(
            db_session, _module, lesson_type="shadow_reading",
            content={"audio_url": "/a.mp3", "text": "x", "translation": "у"},
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "shadow_reading"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completed"] is True

    def test_audio_fill_blank_submit_passes(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(
            db_session, _module, lesson_type="audio_fill_blank",
            content={
                "audio_url": "/a.mp3",
                "items": [{"text_with_gap": "She ___.", "answer": "runs"}],
            },
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "answers": ["runs"],
                "lesson_type": "audio_fill_blank",
                "replay_count": 0,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["passed"] is True

    def test_pronunciation_finish_completes(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(
            db_session, _module, lesson_type="pronunciation",
            content={"items": [{"word": "hello"}]},
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        # Must submit at least one item attempt before finishing
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"lesson_type": "pronunciation", "item_index": 0,
                  "recognized_text": "hello", "target_word": "hello"},
            content_type="application/json",
        )
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"lesson_type": "pronunciation", "finish": True},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completed"] is True

    def test_audio_fill_blank_logs_listening_attempt(
        self, app, db_session, _module, test_user, client
    ):
        """Verify ListeningAttempt rows fire after audio_fill_blank submit
        — XP wiring for the listening slot depends on this row."""
        from app.curriculum.models import ListeningAttempt
        lesson = _make_lesson(
            db_session, _module, lesson_type="audio_fill_blank",
            content={
                "audio_url": "/a.mp3",
                "items": [{"text_with_gap": "She ___.", "answer": "runs"}],
            },
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "answers": ["runs"],
                "lesson_type": "audio_fill_blank",
                "replay_count": 0,
            },
            content_type="application/json",
        )
        attempts = ListeningAttempt.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()
        assert len(attempts) >= 1
