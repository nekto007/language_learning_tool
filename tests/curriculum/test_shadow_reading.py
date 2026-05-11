"""Tests for the shadow reading lesson type.

Task 54: Shadow reading exercise type — validator, template, route, XP mapping.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_shadow_reading_lesson(db_session) -> Lessons:
    level = CEFRLevel(
        code=_unique_code(), name="Level", description="d", order=1
    )
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Test Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Shadow Reading Test",
        type="shadow_reading",
        content={
            "audio_url": "/static/audio/test.mp3",
            "text": "The quick brown fox jumps over the lazy dog.",
            "translation": "Быстрая коричневая лиса прыгает через ленивую собаку.",
        },
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
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "shadow_reading.html"
    )
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestShadowReadingValidator:
    def test_valid_payload_passes(self):
        ok, err, data = LessonContentValidator.validate(
            'shadow_reading',
            {
                'audio_url': '/audio/test.mp3',
                'text': 'Hello world.',
                'translation': 'Привет мир.',
            },
        )
        assert ok is True
        assert err is None

    def test_missing_audio_url_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'shadow_reading',
                {'text': 'Hello.', 'translation': 'Привет.'},
            )

    def test_missing_text_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'shadow_reading',
                {'audio_url': '/audio/a.mp3', 'translation': 'Привет.'},
            )

    def test_missing_translation_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'shadow_reading',
                {'audio_url': '/audio/a.mp3', 'text': 'Hello.'},
            )

    def test_extra_fields_allowed(self):
        ok, _, _ = LessonContentValidator.validate(
            'shadow_reading',
            {
                'audio_url': '/audio/a.mp3',
                'text': 'Hello.',
                'translation': 'Привет.',
                'some_extra_field': 'ignored',
            },
        )
        assert ok is True


# ---------------------------------------------------------------------------
# XP mapping test
# ---------------------------------------------------------------------------

class TestShadowReadingXPMapping:
    def test_shadow_reading_maps_to_linear_curriculum_use(self):
        assert LESSON_TYPE_TO_SOURCE.get('shadow_reading') == 'linear_curriculum_use'

    def test_linear_curriculum_use_in_linear_xp(self):
        from app.achievements.xp_service import LINEAR_XP
        assert 'linear_curriculum_use' in LINEAR_XP
        assert LINEAR_XP['linear_curriculum_use'] == 25


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestShadowReadingTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 100

    def test_template_has_three_phases(self):
        tpl = _read_template()
        assert 'phase-1' in tpl
        assert 'phase-2' in tpl
        assert 'phase-3' in tpl

    def test_audio_element_present(self):
        tpl = _read_template()
        assert '<audio' in tpl

    def test_self_assess_checkbox_present(self):
        tpl = _read_template()
        assert 'self-assess-checkbox' in tpl
        assert 'type="checkbox"' in tpl

    def test_submit_button_disabled_initially(self):
        tpl = _read_template()
        assert 'disabled' in tpl
        assert 'submitShadowReading()' in tpl

    def test_phase2_starts_locked(self):
        tpl = _read_template()
        assert 'shadow-phase--locked' in tpl

    def test_self_assess_required_before_submit(self):
        tpl = _read_template()
        # JS: btn.disabled = !cb.checked
        assert 'btn.disabled = !cb.checked' in tpl

    def test_template_shows_translation(self):
        tpl = _read_template()
        assert 'translation' in tpl

    def test_phase_transition_js_present(self):
        tpl = _read_template()
        assert 'goToPhase2()' in tpl
        assert 'goToPhase3()' in tpl

    def test_no_recording_js(self):
        tpl = _read_template()
        # No SpeechRecognition API called — honor system only
        assert 'SpeechRecognition' not in tpl
        assert 'mediaDevices' not in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestShadowReadingRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        assert resp.status_code == 200

    def test_get_creates_in_progress_record(self, app, db_session, test_user, client):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_lesson_detail_redirects_to_shadow_reading_route(
        self, app, db_session, test_user, client
    ):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "shadow-reading" in resp.headers.get("Location", "")

    def test_wrong_type_redirects(
        self, app, db_session, test_user, client, test_lesson_vocabulary
    ):
        _login(client, test_user)
        resp = client.get(
            f"/curriculum/lesson/{test_lesson_vocabulary.id}/shadow-reading"
        )
        assert resp.status_code in (302, 400)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestShadowReadingSubmit:
    def _submit(self, client, lesson_id: int, self_assessed: bool):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"self_assessed": self_assessed, "lesson_type": "shadow_reading"},
            content_type="application/json",
        )

    def test_self_assessed_true_returns_completed(
        self, app, db_session, test_user, client
    ):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        resp = self._submit(client, lesson.id, True)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["completed"] is True

    def test_self_assessed_false_not_completed(
        self, app, db_session, test_user, client
    ):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        resp = self._submit(client, lesson.id, False)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completed"] is False

    def test_self_assessed_true_marks_lesson_completed(
        self, app, db_session, test_user, client
    ):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        self._submit(client, lesson.id, True)
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_shadow_reading_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "shadow_reading"},
        )
        assert resp.status_code in (302, 401, 403)
