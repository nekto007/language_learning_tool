"""Tests for the dictation lesson template, route, and grading integration.

Task 5: Dictation lesson template and route handler.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.routes.lessons import _build_hint_text, _DICTATION_MAX_REPLAYS
from app.curriculum.grading import grade_dictation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_dictation_lesson(db_session, *, transcript: str = "Hello world", hint_chars: int = 0) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
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
        title="Dictation Test",
        type="dictation",
        content={
            "audio_url": "/static/audio/test.mp3",
            "transcript": transcript,
            "hint_chars": hint_chars,
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Unit tests — _build_hint_text
# ---------------------------------------------------------------------------

class TestBuildHintText:
    def test_zero_hint_chars_returns_empty(self):
        assert _build_hint_text("Hello world", 0) == ""

    def test_hint_chars_prefills_first_n(self):
        result = _build_hint_text("Hello world", 2)
        words = result.split()
        assert words[0].startswith("He")
        assert words[1].startswith("wo")

    def test_hint_chars_preserves_word_count(self):
        result = _build_hint_text("The quick brown fox", 1)
        assert len(result.split()) == 4

    def test_hint_chars_longer_than_word(self):
        result = _build_hint_text("Hi", 10)
        assert result == "Hi"

    def test_empty_transcript(self):
        assert _build_hint_text("", 3) == ""

    def test_hint_text_pads_with_underscores(self):
        result = _build_hint_text("Hello", 2)
        assert result == "He___"


# ---------------------------------------------------------------------------
# Unit tests — max_replays constant
# ---------------------------------------------------------------------------

def test_max_replays_is_3():
    assert _DICTATION_MAX_REPLAYS == 3


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _read_dictation_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "dictation.html"
    )
    return p.read_text(encoding="utf-8")


class TestDictationTemplate:
    def test_template_exists(self):
        tpl = _read_dictation_template()
        assert len(tpl) > 100

    def test_audio_element_present(self):
        tpl = _read_dictation_template()
        assert "<audio" in tpl
        assert 'id="dictation-audio"' in tpl

    def test_replay_button_present(self):
        tpl = _read_dictation_template()
        assert "replay-btn" in tpl
        assert "replayAudio()" in tpl

    def test_max_replays_used_in_template(self):
        tpl = _read_dictation_template()
        assert "max_replays" in tpl

    def test_interactive_gap_inputs_present(self):
        tpl = _read_dictation_template()
        assert "dictation-gap-input" in tpl
        assert "checkDictationWord" in tpl
        assert "<textarea" not in tpl

    def test_no_manual_submit_button_present(self):
        tpl = _read_dictation_template()
        assert 'id="submit-btn"' not in tpl
        assert "submissionStarted" in tpl
        assert "lockedCount === wordCount" in tpl

    def test_hint_chars_condition_present(self):
        tpl = _read_dictation_template()
        assert "hint_chars" in tpl

    def test_results_div_present(self):
        tpl = _read_dictation_template()
        assert 'id="dictation-results"' in tpl

    def test_word_results_container(self):
        tpl = _read_dictation_template()
        assert "dictation-word-results" in tpl

    def test_transcript_reveal_on_fail(self):
        tpl = _read_dictation_template()
        assert "dictation-transcript-reveal" in tpl

    def test_js_submit_function_present(self):
        tpl = _read_dictation_template()
        assert "async function submitDictation()" in tpl

    def test_js_uses_curriculum_submit_endpoint(self):
        tpl = _read_dictation_template()
        assert "/curriculum/api/lesson/" in tpl
        assert "/learn/api/lesson/" not in tpl

    def test_js_uses_dictation_word_endpoint(self):
        tpl = _read_dictation_template()
        assert "/dictation-word" in tpl

    def test_js_show_results_function_present(self):
        tpl = _read_dictation_template()
        assert "function showResults(" in tpl

    def test_replay_count_tracked_in_js(self):
        tpl = _read_dictation_template()
        assert "replayCount" in tpl

    def test_replays_left_counter_present(self):
        tpl = _read_dictation_template()
        assert "replays-left" in tpl

    def test_correct_transcript_shown_when_not_passed(self):
        tpl = _read_dictation_template()
        # JS block checks data.transcript and renders it
        assert "data.transcript" in tpl


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


class TestDictationCSS:
    def test_dictation_input_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-input {" in css or ".dictation-input{" in css

    def test_dictation_word_result_correct_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-word-result--correct" in css

    def test_dictation_word_result_wrong_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-word-result--wrong" in css

    def test_dictation_replay_btn_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-replay-btn" in css

    def test_dictation_score_badge_pass_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-score-badge--pass" in css

    def test_dictation_score_badge_fail_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-score-badge--fail" in css

    def test_dictation_transcript_reveal_class_defined(self):
        css = _read_design_system_css()
        assert ".dictation-transcript-reveal" in css


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestDictationLessonRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        assert resp.status_code == 200

    def test_get_redirects_non_dictation_lesson(self, app, db_session, test_user, client, test_lesson_vocabulary):
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{test_lesson_vocabulary.id}/dictation")
        # Either 302 redirect or 400 — route rejects non-dictation
        assert resp.status_code in (302, 400)

    def test_lesson_detail_redirects_to_dictation_route(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "dictation" in resp.headers.get("Location", "")

    def test_short_learn_url_redirects_to_canonical_dictation_route(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/learn/{lesson.id}/", follow_redirects=False)
        assert resp.status_code == 302
        assert f"/curriculum/lesson/{lesson.id}" in resp.headers.get("Location", "")

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_completed_lesson_get_restores_checked_gaps(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "user_text": "Hello world",
                "replay_count": 0,
                "hint_chars": 0,
                "lesson_type": "dictation",
            },
            content_type="application/json",
        )

        resp = client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert 'value="Hello"' in html
        assert 'value="world"' in html
        assert 'data-status="correct"' in html
        assert "initialDictationResult" in html


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestDictationSubmitRoute:
    def _submit(self, client, lesson_id: int, user_text: str, replay_count: int = 0):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={
                "user_text": user_text,
                "replay_count": replay_count,
                "hint_chars": 0,
                "lesson_type": "dictation",
            },
            content_type="application/json",
        )

    def test_correct_answer_returns_passed_true(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        # GET first to create progress
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        resp = self._submit(client, lesson.id, "Hello world")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert data["score"] == 100

    def test_inserted_dictation_next_url_uses_next_lesson_number_in_same_module(
        self, app, db_session, test_user, client
    ):
        level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
        db_session.add(level)
        db_session.commit()
        first_module = Module(
            level_id=level.id,
            number=1,
            title="Module 1",
            description="d",
            raw_content={"module": {"id": 1}},
        )
        second_module = Module(
            level_id=level.id,
            number=2,
            title="Module 2",
            description="d",
            raw_content={"module": {"id": 2}},
        )
        db_session.add_all([first_module, second_module])
        db_session.commit()

        current = Lessons(
            module_id=first_module.id,
            number=10,
            title="Dictation One",
            type="dictation",
            content={
                "audio_url": "/static/audio/one.mp3",
                "transcript": "Hello world",
                "external_key": "immersion:dictation:A1:01:one",
            },
        )
        regular_same_module = Lessons(
            module_id=first_module.id,
            number=11,
            title="Regular Lesson",
            type="vocabulary",
            content={},
        )
        next_dictation = Lessons(
            module_id=second_module.id,
            number=10,
            title="Dictation Two",
            type="dictation",
            content={
                "audio_url": "/static/audio/two.mp3",
                "transcript": "Good morning",
                "external_key": "immersion:dictation:A1:02:two",
            },
        )
        db_session.add_all([current, regular_same_module, next_dictation])
        db_session.commit()

        _login(client, test_user)
        client.get(f"/curriculum/lesson/{current.id}/dictation")
        resp = self._submit(client, current.id, "Hello world")
        data = resp.get_json()

        assert data["passed"] is True
        assert data["next_lesson_url"].endswith(f"/learn/{regular_same_module.id}/")
        assert f"/learn/{next_dictation.id}/" not in data["next_lesson_url"]

    def test_wrong_answer_returns_passed_false_with_transcript(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        resp = self._submit(client, lesson.id, "Goodbye earth")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is False
        assert data["transcript"] == "Hello world"

    def test_partial_score_40_percent_fails(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="one two three four five")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        # 2 out of 5 correct → 40%
        resp = self._submit(client, lesson.id, "one two wrong wrong wrong")
        data = resp.get_json()
        assert data["score"] == 40
        assert data["passed"] is False

    def test_word_results_returned(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        resp = self._submit(client, lesson.id, "Hello world")
        data = resp.get_json()
        assert "word_results" in data
        assert len(data["word_results"]) == 2
        assert all(wr["correct"] for wr in data["word_results"])

    def test_replay_count_submitted_in_payload(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        # replay_count is submitted but not validated server-side — just ensure no crash
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "user_text": "Hello world",
                "replay_count": 2,
                "hint_chars": 0,
                "lesson_type": "dictation",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_word_check_correct_does_not_expose_answer(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/dictation-word",
            json={"index": 0, "answer": "Hello", "attempt": 1},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["correct"] is True
        assert "correct_word" not in data

    def test_word_check_third_wrong_reveals_answer_and_tracks_failed_index(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/dictation-word",
            json={"index": 0, "answer": "Nope", "attempt": 3},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["correct"] is False
        assert data["exhausted"] is True
        assert data["correct_word"] == "Hello"
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress.data["dictation_failed_indices"] == [0]

    def test_submit_after_exhausted_gap_does_not_complete_lesson(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.post(
            f"/curriculum/api/lesson/{lesson.id}/dictation-word",
            json={"index": 0, "answer": "Nope", "attempt": 3},
            content_type="application/json",
        )
        resp = self._submit(client, lesson.id, "Hello world")
        data = resp.get_json()
        assert data["passed"] is False
        assert data["failed_by_attempt_limit"] is True
        assert data["score"] == 79
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress.status != "completed"

    def test_passed_lesson_marks_progress_completed(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        self._submit(client, lesson.id, "Hello world")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_failed_lesson_does_not_mark_completed(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session, transcript="Hello world")
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        self._submit(client, lesson.id, "Goodbye earth")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status != "completed"

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_dictation_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_text": "hello", "lesson_type": "dictation"},
        )
        # Redirect to login
        assert resp.status_code in (302, 401, 403)
