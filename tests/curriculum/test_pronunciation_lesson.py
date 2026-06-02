"""Tests for the pronunciation lesson type.

Task 55: Pronunciation exercise type (with Web Speech API).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.grading import grade_pronunciation_match
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pronunciation_lesson(db_session) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
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
        title="Pronunciation Test",
        type="pronunciation",
        content={
            "items": [
                {"word": "hello", "pronunciation_hint": "həˈloʊ", "audio_url": "/audio/hello.mp3"},
                {"word": "world"},
            ]
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
        / "pronunciation.html"
    )
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestPronunciationValidator:
    def test_valid_payload_passes(self):
        ok, err, data = LessonContentValidator.validate(
            'pronunciation',
            {'items': [{'word': 'hello'}]},
        )
        assert ok is True
        assert err is None

    def test_valid_with_all_fields(self):
        ok, err, data = LessonContentValidator.validate(
            'pronunciation',
            {
                'items': [
                    {
                        'word': 'beautiful',
                        'pronunciation_hint': 'ˈbjuːtɪfəl',
                        'audio_url': '/audio/beautiful.mp3',
                    }
                ]
            },
        )
        assert ok is True

    def test_missing_items_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate('pronunciation', {})

    def test_empty_items_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate('pronunciation', {'items': []})

    def test_item_missing_word_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'pronunciation',
                {'items': [{'pronunciation_hint': '/test/'}]},
            )

    def test_optional_fields_absent_ok(self):
        ok, _, _ = LessonContentValidator.validate(
            'pronunciation',
            {'items': [{'word': 'test'}]},
        )
        assert ok is True

    def test_extra_fields_allowed(self):
        ok, _, _ = LessonContentValidator.validate(
            'pronunciation',
            {'items': [{'word': 'test', 'extra': 'ignored'}]},
        )
        assert ok is True


# ---------------------------------------------------------------------------
# Word-match grader tests
# ---------------------------------------------------------------------------

class TestGradePronunciationMatch:
    def test_exact_match(self):
        result = grade_pronunciation_match('hello', 'hello')
        assert result['matched'] is True

    def test_case_insensitive_match(self):
        result = grade_pronunciation_match('Hello', 'hello')
        assert result['matched'] is True

    def test_typo_single_char_matches(self):
        # Levenshtein ≤1 for single-word targets ≥4 chars
        result = grade_pronunciation_match('helo', 'hello')
        assert result['matched'] is True

    def test_completely_wrong_word_no_match(self):
        result = grade_pronunciation_match('goodbye', 'hello')
        assert result['matched'] is False

    def test_empty_recognized_no_match(self):
        result = grade_pronunciation_match('', 'hello')
        assert result['matched'] is False

    def test_result_contains_recognized_and_target(self):
        result = grade_pronunciation_match('world', 'world')
        assert result['recognized'] == 'world'
        assert result['target'] == 'world'

    def test_punctuation_stripped(self):
        result = grade_pronunciation_match('hello!', 'hello')
        assert result['matched'] is True

    def test_short_word_no_typo_tolerance(self):
        # Words < 4 chars: exact match only
        result = grade_pronunciation_match('an', 'at')
        assert result['matched'] is False

    def test_multi_word_exact_only(self):
        # Multi-word targets: exact normalized match only
        result = grade_pronunciation_match('good morning', 'good morning')
        assert result['matched'] is True

    def test_multi_word_typo_no_match(self):
        result = grade_pronunciation_match('good morningg', 'good morning')
        assert result['matched'] is False


# ---------------------------------------------------------------------------
# XP mapping test
# ---------------------------------------------------------------------------

class TestPronunciationXPMapping:
    def test_pronunciation_maps_to_linear_curriculum_use(self):
        assert LESSON_TYPE_TO_SOURCE.get('pronunciation') == 'linear_curriculum_use'

    def test_linear_curriculum_use_in_linear_xp(self):
        from app.achievements.xp_service import LINEAR_XP
        assert 'linear_curriculum_use' in LINEAR_XP
        assert LINEAR_XP['linear_curriculum_use'] > 0


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestPronunciationTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 100

    def test_template_has_speech_btn(self):
        tpl = _read_template()
        assert 'speech-btn' in tpl

    def test_template_has_fallback_btn(self):
        tpl = _read_template()
        assert 'fallback-btn' in tpl

    def test_no_speech_api_path_shows_self_assess(self):
        tpl = _read_template()
        # The self-assess checkbox is rendered for every item
        assert 'self-cb-' in tpl
        assert 'type="checkbox"' in tpl

    def test_speech_api_detection_js_present(self):
        tpl = _read_template()
        assert 'SpeechRecognition' in tpl
        assert 'webkitSpeechRecognition' in tpl

    def test_recognition_lang_set_to_en_us(self):
        tpl = _read_template()
        assert "recognition.lang = 'en-US'" in tpl

    def test_speech_api_unsupported_shows_fallback(self):
        tpl = _read_template()
        # When speechSupported=false, fallback buttons are shown
        assert 'fallbackBtns.forEach' in tpl
        assert 'speechBtns.forEach' in tpl

    def test_finish_button_present(self):
        tpl = _read_template()
        assert 'finish-btn' in tpl
        assert 'finishLesson()' in tpl

    def test_похоже_and_retry_texts(self):
        tpl = _read_template()
        # These strings appear in JS after recognition result
        assert 'Похоже' in tpl or 'matched' in tpl

    def test_audio_player_present(self):
        tpl = _read_template()
        assert '<audio' in tpl

    def test_prefers_reduced_motion_check_present(self):
        tpl = _read_template()
        assert 'prefers-reduced-motion' in tpl

    def test_prefers_reduced_motion_disables_speech_recognition(self):
        tpl = _read_template()
        assert 'prefersReducedMotion' in tpl
        assert '!prefersReducedMotion' in tpl

    def test_prefers_reduced_motion_guard_in_start_recognition(self):
        tpl = _read_template()
        assert 'prefers-reduced-motion' in tpl
        # startRecognition must bail out when reduced-motion is active
        assert 'showSelfAssess' in tpl

    def test_permission_denied_shows_fallback_not_blank(self):
        tpl = _read_template()
        # onerror handler must catch 'not-allowed' and show self-assess
        assert "event.error === 'not-allowed'" in tpl
        # and it must call showSelfAssess (not just render badge)
        lines = tpl.splitlines()
        not_allowed_idx = next(
            i for i, l in enumerate(lines) if "not-allowed" in l
        )
        nearby = '\n'.join(lines[not_allowed_idx:not_allowed_idx + 5])
        assert 'showSelfAssess' in nearby

    def test_fallback_button_onclick_triggers_self_assess(self):
        tpl = _read_template()
        assert 'showSelfAssess(' in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestPronunciationRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        assert resp.status_code == 200

    def test_get_creates_in_progress_record(self, app, db_session, test_user, client):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_lesson_detail_redirects_to_pronunciation_route(
        self, app, db_session, test_user, client
    ):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "pronunciation" in resp.headers.get("Location", "")

    def test_wrong_type_redirects(
        self, app, db_session, test_user, client, test_lesson_vocabulary
    ):
        _login(client, test_user)
        resp = client.get(
            f"/curriculum/lesson/{test_lesson_vocabulary.id}/pronunciation"
        )
        assert resp.status_code in (302, 400)

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_pronunciation_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        assert resp.status_code in (302, 401, 403)


# ---------------------------------------------------------------------------
# Route tests — POST submit (item attempt)
# ---------------------------------------------------------------------------

class TestPronunciationSubmit:
    def _submit_item(self, client, lesson_id: int, recognized: str, target: str):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={
                "lesson_type": "pronunciation",
                "item_index": 0,
                "recognized_text": recognized,
                "target_word": target,
            },
            content_type="application/json",
        )

    def _submit_finish(self, client, lesson_id: int):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"lesson_type": "pronunciation", "finish": True},
            content_type="application/json",
        )

    def test_item_exact_match_returns_matched_true(
        self, app, db_session, test_user, client
    ):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        resp = self._submit_item(client, lesson.id, "hello", "hello")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["matched"] is True

    def test_item_wrong_word_returns_matched_false(
        self, app, db_session, test_user, client
    ):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        resp = self._submit_item(client, lesson.id, "goodbye", "hello")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["matched"] is False

    def test_finish_marks_lesson_completed(
        self, app, db_session, test_user, client
    ):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        # Must submit at least one item attempt before finishing
        self._submit_item(client, lesson.id, "hello", "hello")
        resp = self._submit_finish(client, lesson.id)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["completed"] is True
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_self_assessed_item_returns_success(
        self, app, db_session, test_user, client
    ):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "lesson_type": "pronunciation",
                "item_index": 0,
                "target_word": "hello",
                "self_assessed": True,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_self_assessed_records_pronunciation_attempt(
        self, app, db_session, test_user, client
    ):
        from app.curriculum.models import PronunciationAttempt
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "lesson_type": "pronunciation",
                "item_index": 0,
                "target_word": "hello",
                "self_assessed": True,
            },
            content_type="application/json",
        )
        db_session.expire_all()
        attempts = (
            db_session.query(PronunciationAttempt)
            .filter_by(user_id=test_user.id, word="hello")
            .all()
        )
        assert len(attempts) >= 1

    def test_speech_recognition_item_records_pronunciation_attempt(
        self, app, db_session, test_user, client
    ):
        from app.curriculum.models import PronunciationAttempt
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        self._submit_item(client, lesson.id, "hello", "hello")
        db_session.expire_all()
        attempts = (
            db_session.query(PronunciationAttempt)
            .filter_by(user_id=test_user.id, word="hello")
            .all()
        )
        assert len(attempts) >= 1
        assert any(a.matched for a in attempts)

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_pronunciation_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"lesson_type": "pronunciation", "finish": True},
        )
        assert resp.status_code in (302, 401, 403)
