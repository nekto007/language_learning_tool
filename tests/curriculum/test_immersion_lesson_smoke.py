"""Smoke tests for all ten immersion lesson types — Task 45.

Covers for each type:
- GET route returns 200 and creates LessonProgress(status=in_progress)
- POST submit with a passing answer passes and marks progress completed
- POST submit with a failing answer (where applicable) does not complete
- next_lesson_url is present in passing response when a follow-on lesson exists
- LESSON_TYPE_TO_SOURCE mapping entry exists for each type (XP source wiring)
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_level(db_session):
    level = CEFRLevel(code=_uid(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level):
    module = Module(
        level_id=level.id,
        number=1,
        title="Smoke Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _add_next_lesson(db_session, module, lesson_number: int = 99) -> Lessons:
    """Add a follow-on vocabulary lesson so next_lesson_url has a target."""
    next_l = Lessons(
        module_id=module.id,
        number=lesson_number,
        title="Next Lesson",
        type="vocabulary",
        content={"words": []},
    )
    db_session.add(next_l)
    db_session.commit()
    return next_l


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def _get_progress(user_id: int, lesson_id: int):
    return LessonProgress.query.filter_by(user_id=user_id, lesson_id=lesson_id).first()


# ---------------------------------------------------------------------------
# XP source mapping — all ten types must be registered
# ---------------------------------------------------------------------------

class TestXPSourceMapping:
    @pytest.mark.parametrize("lesson_type", [
        "dictation", "audio_fill_blank", "translation", "sentence_correction",
        "writing_prompt", "sentence_completion", "collocation_matching",
        "shadow_reading", "pronunciation", "idiom",
    ])
    def test_xp_source_registered(self, lesson_type):
        assert lesson_type in LESSON_TYPE_TO_SOURCE, (
            f"LESSON_TYPE_TO_SOURCE is missing entry for '{lesson_type}'"
        )
        assert LESSON_TYPE_TO_SOURCE[lesson_type], (
            f"LESSON_TYPE_TO_SOURCE['{lesson_type}'] must be a non-empty string"
        )


# ---------------------------------------------------------------------------
# dictation
# ---------------------------------------------------------------------------

def _make_dictation_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Dictation Smoke",
        type="dictation",
        content={"audio_url": "/static/audio/test.mp3", "transcript": "Hello world"},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestDictationSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        assert resp.status_code == 200
        progress = _get_progress(test_user.id, lesson.id)
        assert progress is not None
        assert progress.status == "in_progress"

    def test_passing_answer_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_text": "Hello world", "replay_count": 0, "hint_chars": 0, "lesson_type": "dictation"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert data["score"] == 100
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_failing_answer_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_text": "wrong answer here", "replay_count": 0, "hint_chars": 0, "lesson_type": "dictation"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["passed"] is False
        assert _get_progress(test_user.id, lesson.id).status != "completed"

    def test_passing_response_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_dictation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/dictation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_text": "Hello world", "replay_count": 0, "hint_chars": 0, "lesson_type": "dictation"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# audio_fill_blank
# ---------------------------------------------------------------------------

def _make_audio_fill_blank_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Audio Fill Blank Smoke",
        type="audio_fill_blank",
        content={
            "audio_url": "/static/audio/test.mp3",
            "items": [
                {"text_with_gap": "She ___ happy.", "answer": "is"},
                {"text_with_gap": "They ___ students.", "answer": "are"},
            ],
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestAudioFillBlankSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_audio_fill_blank_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_all_correct_passes_lesson(self, app, db_session, test_user, client):
        lesson = _make_audio_fill_blank_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["is", "are"], "replay_count": 0, "lesson_type": "audio_fill_blank"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_all_wrong_fails_lesson(self, app, db_session, test_user, client):
        lesson = _make_audio_fill_blank_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["nope", "nope"], "replay_count": 0, "lesson_type": "audio_fill_blank"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["passed"] is False

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_audio_fill_blank_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["is", "are"], "lesson_type": "audio_fill_blank"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# translation
# ---------------------------------------------------------------------------

def _make_translation_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Translation Smoke",
        type="translation",
        content={"russian": "Я люблю кошек", "english": "I love cats"},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestTranslationSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_correct_answer_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "I love cats", "lesson_type": "translation"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Translation now uses multi-item contract — see grade_translation_multi.
        assert data["passed"] is True
        assert data["correct_items"] == 1
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_wrong_answer_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "She hates dogs", "lesson_type": "translation"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["passed"] is False
        assert _get_progress(test_user.id, lesson.id).status != "completed"

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_translation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/translation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "I love cats", "lesson_type": "translation"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# sentence_correction
# ---------------------------------------------------------------------------

def _make_sentence_correction_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Sentence Correction Smoke",
        type="sentence_correction",
        content={
            "incorrect_sentence": "She go to school every day.",
            "correct_sentence": "She goes to school every day.",
            "error_type": "verb agreement",
            "explanation": "Third-person singular needs -s.",
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestSentenceCorrectionSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_correct_answer_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "She goes to school every day.", "lesson_type": "sentence_correction"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_correct"] is True
        assert data["passed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_wrong_answer_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "She go to school every day.", "lesson_type": "sentence_correction"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["is_correct"] is False
        assert _get_progress(test_user.id, lesson.id).status != "completed"

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "She goes to school every day.", "lesson_type": "sentence_correction"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# writing_prompt
# ---------------------------------------------------------------------------

_WRITING_SMOKE_CHECKLIST = ["used time markers", "described actions", "checked spelling"]


def _make_writing_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Writing Prompt Smoke",
        type="writing_prompt",
        content={
            "prompt": "Describe your morning routine.",
            "min_words": 3,
            "checklist": _WRITING_SMOKE_CHECKLIST,
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestWritingPromptSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_meets_words_and_checklist_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "I wake up at seven every morning.",
                "checked_items": _WRITING_SMOKE_CHECKLIST[:2],
                "checklist_completed": True,
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_too_short_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "hi",
                "checked_items": ["a", "b"],
                "checklist_completed": True,
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "I wake up early and make coffee.",
                "checked_items": _WRITING_SMOKE_CHECKLIST[:2],
                "checklist_completed": True,
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# sentence_completion
# ---------------------------------------------------------------------------

def _make_sentence_completion_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Sentence Completion Smoke",
        type="sentence_completion",
        content={
            "items": [
                {"prompt": "She is going ___", "answer": "home"},
                {"prompt": "He likes to ___", "answer": "read"},
            ]
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestSentenceCompletionSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_all_correct_passes_lesson(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["home", "read"], "lesson_type": "sentence_completion"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_all_wrong_fails_lesson(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["nope", "wrong"], "lesson_type": "sentence_completion"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["passed"] is False

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["home", "read"], "lesson_type": "sentence_completion"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# collocation_matching
# ---------------------------------------------------------------------------

def _make_collocation_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Collocation Matching Smoke",
        type="collocation_matching",
        content={
            "pairs": [
                {"phrase": "make a decision", "translation": "принять решение"},
                {"phrase": "take a break", "translation": "сделать перерыв"},
            ]
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestCollocationMatchingSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_collocation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_all_correct_passes_lesson(self, app, db_session, test_user, client):
        lesson = _make_collocation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "user_pairs": [
                    {"phrase": "make a decision", "translation": "принять решение"},
                    {"phrase": "take a break", "translation": "сделать перерыв"},
                ],
                "lesson_type": "collocation_matching",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_all_wrong_fails_lesson(self, app, db_session, test_user, client):
        lesson = _make_collocation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "user_pairs": [
                    {"phrase": "make a decision", "translation": "сделать перерыв"},
                    {"phrase": "take a break", "translation": "принять решение"},
                ],
                "lesson_type": "collocation_matching",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["passed"] is False

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_collocation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "user_pairs": [
                    {"phrase": "make a decision", "translation": "принять решение"},
                    {"phrase": "take a break", "translation": "сделать перерыв"},
                ],
                "lesson_type": "collocation_matching",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# shadow_reading
# ---------------------------------------------------------------------------

def _make_shadow_reading_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Shadow Reading Smoke",
        type="shadow_reading",
        content={
            "audio_url": "/static/audio/test.mp3",
            "text": "The sun rises in the east.",
            "translation": "Солнце встаёт на востоке.",
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestShadowReadingSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_self_assessed_true_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_shadow_reading_lesson(db_session)
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
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_self_assessed_false_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": False, "lesson_type": "shadow_reading"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False
        assert _get_progress(test_user.id, lesson.id).status != "completed"

    def test_passing_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_shadow_reading_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/shadow-reading")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"self_assessed": True, "lesson_type": "shadow_reading"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# pronunciation
# ---------------------------------------------------------------------------

def _make_pronunciation_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Pronunciation Smoke",
        type="pronunciation",
        content={
            "items": [
                {"word": "through", "pronunciation_hint": "/θruː/"},
                {"word": "thought", "pronunciation_hint": "/θɔːt/"},
            ]
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestPronunciationSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_finish_true_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"finish": True, "lesson_type": "pronunciation"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_item_attempt_self_assessed_returns_success(self, app, db_session, test_user, client):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"target_word": "through", "self_assessed": True, "lesson_type": "pronunciation"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_finish_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_pronunciation_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/pronunciation")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"finish": True, "lesson_type": "pronunciation"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]


# ---------------------------------------------------------------------------
# idiom
# ---------------------------------------------------------------------------

def _make_idiom_lesson(db_session):
    level = _make_level(db_session)
    module = _make_module(db_session, level)
    _add_next_lesson(db_session, module)
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Idiom Smoke",
        type="idiom",
        content={
            "items": [
                {
                    "phrase": "break the ice",
                    "meaning": "To do something to make people feel more comfortable.",
                    "example": "She told a joke to break the ice.",
                }
            ]
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestIdiomSmoke:
    def test_get_returns_200_and_creates_progress(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/idiom")
        assert resp.status_code == 200
        assert _get_progress(test_user.id, lesson.id).status == "in_progress"

    def test_finish_true_completes_lesson(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/idiom")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"finish": True, "lesson_type": "idiom"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completed"] is True
        assert _get_progress(test_user.id, lesson.id).status == "completed"

    def test_finish_false_does_not_complete(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/idiom")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"finish": False, "lesson_type": "idiom"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False
        assert _get_progress(test_user.id, lesson.id).status != "completed"

    def test_finish_includes_next_lesson_url(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/idiom")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"finish": True, "lesson_type": "idiom"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert "next_lesson_url" in data and data["next_lesson_url"]
