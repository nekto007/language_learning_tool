"""Tests for the dedicated listening_immersion lesson template (Task 5)."""
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


def _make_listening_immersion_lesson(db_session, *, content=None) -> Lessons:
    if content is None:
        content = {
            "text": "Hello, how are you?\nI'm fine, thanks.",
            "audio": "lesson_audio.mp3",
            "translation": "Привет, как дела? Я в порядке, спасибо.",
            "title": "Greetings",
        }
    level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Listening Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Listening Immersion",
        type="listening_immersion",
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def _read_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app" / "templates" / "curriculum" / "lessons"
        / "listening_immersion.html"
    )
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Template structure
# ---------------------------------------------------------------------------

class TestListeningImmersionTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 200

    def test_uses_lesson_shell(self):
        tpl = _read_template()
        assert "lesson-shell" in tpl
        assert "lesson-shell__header" in tpl
        assert "lesson-shell__body" in tpl
        assert "lesson-shell__actions" in tpl

    def test_audio_player_present(self):
        tpl = _read_template()
        assert 'id="listening-audio"' in tpl

    def test_audio_speed_controls_present(self):
        tpl = _read_template()
        assert 'id="audio-speed-controls"' in tpl

    def test_transcript_toggle_present(self):
        tpl = _read_template()
        assert 'id="transcript-toggle-btn"' in tpl
        assert 'id="transcript-content"' in tpl

    def test_self_assess_checkbox_present(self):
        tpl = _read_template()
        assert 'id="li-self-cb"' in tpl

    def test_submit_payload_includes_self_assessed(self):
        tpl = _read_template()
        assert "self_assessed: true" in tpl
        assert "lesson_type: 'listening_immersion'" in tpl

    def test_submit_endpoint(self):
        tpl = _read_template()
        assert "/curriculum/api/lesson/" in tpl
        assert "/submit" in tpl

    def test_uses_global_completion_helper(self):
        """Listening immersion uses the shared showLessonCompletion() helper
        from lesson_base_template instead of a custom result region — so the
        completion UI (icon, title, CTAs) is consistent with every other
        lesson type."""
        tpl = _read_template()
        assert "showLessonCompletion(" in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestListeningImmersionRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        assert resp.status_code == 200

    def test_get_includes_audio_url(self, app, db_session, test_user, client):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        body = resp.get_data(as_text=True)
        assert "lesson_audio.mp3" in body

    def test_get_includes_translation(self, app, db_session, test_user, client):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        body = resp.get_data(as_text=True)
        assert "Привет" in body or "Я в порядке" in body

    def test_lesson_detail_redirects_to_listening_immersion_route(
        self, app, db_session, test_user, client
    ):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "listening-immersion" in resp.headers.get("Location", "")

    def test_get_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_listening_immersion_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        assert resp.status_code in (302, 401, 403)


# ---------------------------------------------------------------------------
# Submit tests
# ---------------------------------------------------------------------------

class TestListeningImmersionSubmit:
    def test_submit_self_assessed_completes(self, app, db_session, test_user, client):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "listening_immersion"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("completed") is True

    def test_submit_marks_progress_completed(self, app, db_session, test_user, client):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "listening_immersion"},
        )
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_submit_without_self_assess_does_not_complete(
        self, app, db_session, test_user, client
    ):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": False, "lesson_type": "listening_immersion"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("completed") is False
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        # Still in_progress, not completed
        assert progress.status != "completed"

    def test_submit_logs_listening_attempt(self, app, db_session, test_user, client):
        from app.curriculum.models import ListeningAttempt
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        before = ListeningAttempt.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).count()
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "listening_immersion"},
        )
        after = ListeningAttempt.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).count()
        assert after == before + 1

    def test_resubmit_does_not_duplicate_listening_attempt(
        self, app, db_session, test_user, client
    ):
        """Re-submitting after completion must not log a second ListeningAttempt.

        Verifies the `was_already_completed` idempotency guard in
        _process_listening_immersion_submission.
        """
        from app.curriculum.models import ListeningAttempt
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/listening-immersion")
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "listening_immersion"},
        )
        count_after_first = ListeningAttempt.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).count()
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "listening_immersion"},
        )
        count_after_second = ListeningAttempt.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).count()
        assert count_after_second == count_after_first


# ---------------------------------------------------------------------------
# text_lesson no longer accepts listening_immersion
# ---------------------------------------------------------------------------

class TestTextLessonNoLongerHandlesListeningImmersion:
    def test_text_route_rejects_listening_immersion(
        self, app, db_session, test_user, client
    ):
        lesson = _make_listening_immersion_lesson(db_session)
        _login(client, test_user)
        # Directly hitting the legacy text route with a listening_immersion lesson
        # should now abort 400 (or redirect — anyway not a 200 render).
        resp = client.get(f"/curriculum/lesson/{lesson.id}/text")
        assert resp.status_code in (400, 302, 404)
