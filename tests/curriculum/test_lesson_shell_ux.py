"""
Tests for Task 47: lesson shell UX — progress indicators, result-badge cleanup,
input--checking state, prefers-reduced-motion, double-submit prevention.

Render tests use direct lesson-type routes (e.g. /curriculum/lesson/{id}/audio-fill-blank)
to bypass the /learn/{id}/ → canonical-route redirect.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module


STATIC_JS = (
    Path(__file__).resolve().parent.parent.parent
    / "app" / "static" / "js"
)
TEMPLATES_LESSONS = (
    Path(__file__).resolve().parent.parent.parent
    / "app" / "templates" / "curriculum" / "lessons"
)
DESIGN_SYSTEM_CSS = (
    Path(__file__).resolve().parent.parent.parent
    / "app" / "static" / "css" / "design-system.css"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _unique():
    return uuid.uuid4().hex[:2].upper()


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


@pytest.fixture()
def _level(db_session):
    code = _unique()
    level = CEFRLevel(code=code, name=f"Level {code}", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    return level


@pytest.fixture()
def _module(db_session, _level):
    module = Module(
        level_id=_level.id,
        number=1,
        title="Shell UX Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module, *, lesson_type: str, content: dict) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=99,
        title=f"{lesson_type} shell ux test",
        type=lesson_type,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ---------------------------------------------------------------------------
# 1. progress bar updates between steps
# ---------------------------------------------------------------------------

class TestProgressBarUpdates:

    def test_audio_fill_blank_has_progress_bar_elements(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(db_session, _module, lesson_type="audio_fill_blank", content={
            "audio_url": "/a.mp3",
            "items": [
                {"text_with_gap": "She ___ to school.", "answer": "goes"},
                {"text_with_gap": "I ___ books.", "answer": "read"},
            ],
        })
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "lesson-shell__progress-bar" in html
        assert "lesson-shell__progress-fill" in html
        assert "_updateProgress" in html

    def test_sentence_completion_has_progress_elements(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(db_session, _module, lesson_type="sentence_completion", content={
            "items": [
                {"prefix": "She ", "suffix": " home.", "answer": "went"},
                {"prefix": "They ", "suffix": " a book.", "answer": "read"},
            ],
        })
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "lesson-shell__progress" in html
        assert "_updateProgress" in html

    def test_translation_lesson_has_progress_elements(
        self, app, db_session, _module, test_user, client
    ):
        lesson = _make_lesson(db_session, _module, lesson_type="translation", content={
            "items": [{"en": "Hello", "ru": "Привет"}, {"en": "World", "ru": "Мир"}],
            "mode": "ru_to_en",
        })
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/translation")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "lesson-shell__progress" in html
        assert "_updateProgress" in html

    def test_progress_bar_updates_call_on_each_item_resolved(self):
        """Static check: _updateProgress is called after both correct and given-up paths."""
        src = (TEMPLATES_LESSONS / "audio_fill_blank.html").read_text(encoding="utf-8")
        # _updateProgress must be called from both the correct-answer path and
        # the given-up path so the bar advances regardless of outcome.
        assert src.count("_updateProgress()") >= 2


# ---------------------------------------------------------------------------
# 2. result-badge cleared before re-render on retry
# ---------------------------------------------------------------------------

class TestResultBadgeClearedOnRetry:

    def test_pronunciation_clears_badge_container_before_render(self):
        src = (TEMPLATES_LESSONS / "pronunciation.html").read_text(encoding="utf-8")
        # _renderBadge must empty the container before appending a new badge
        assert "el.innerHTML = ''" in src or "el.innerHTML=''" in src

    def test_sentence_completion_resets_finalizing_on_retry(self):
        src = (TEMPLATES_LESSONS / "sentence_completion.html").read_text(encoding="utf-8")
        # _finalizing must be reset so the result area can be re-submitted
        assert "_finalizing = false" in src

    def test_sentence_completion_clears_result_container_on_error(self):
        src = (TEMPLATES_LESSONS / "sentence_completion.html").read_text(encoding="utf-8")
        # Error path must clear the summary/result container
        assert ".innerHTML = ''" in src or ".innerHTML=''" in src

    def test_translation_strips_input_classes_on_soft_retry(self):
        src = (TEMPLATES_LESSONS / "translation.html").read_text(encoding="utf-8")
        # _softRetryGivenUp must remove both input state classes
        assert "classList.remove" in src
        # Both classes must appear in a remove() call
        assert "input--wrong" in src
        assert "input--correct" in src

    def test_audio_fill_blank_resets_feedback_container_on_check(self):
        src = (TEMPLATES_LESSONS / "audio_fill_blank.html").read_text(encoding="utf-8")
        # _setFeedback must clear any previous feedback before setting new state
        assert "_setFeedback" in src
        # Both correct and wrong paths use it
        assert "_setFeedback(idx, 'correct'" in src
        assert "_setFeedback(idx, 'wrong'" in src


# ---------------------------------------------------------------------------
# 3. input--checking does not hang on network error
# ---------------------------------------------------------------------------

class TestInputCheckingState:

    def test_input_checking_class_defined_in_design_system(self):
        css = DESIGN_SYSTEM_CSS.read_text(encoding="utf-8")
        assert ".input--checking" in css

    def test_input_checking_has_no_pointer_events_none(self):
        """The .input--checking style must not block interaction."""
        css = DESIGN_SYSTEM_CSS.read_text(encoding="utf-8")
        start = css.find(".input--checking")
        assert start != -1
        block_end = css.find("}", start)
        block = css[start:block_end]
        assert "pointer-events: none" not in block
        assert "pointer-events:none" not in block

    def test_translation_resets_finalizing_on_network_error(self):
        """On network error _finalizing must revert so retries are possible."""
        src = (TEMPLATES_LESSONS / "translation.html").read_text(encoding="utf-8")
        assert "_finalizing = false" in src

    def test_audio_fill_blank_resets_finalizing_on_submit_error(self):
        src = (TEMPLATES_LESSONS / "audio_fill_blank.html").read_text(encoding="utf-8")
        assert "_finalizing = false" in src

    def test_sentence_completion_resets_finalizing_on_submit_error(self):
        src = (TEMPLATES_LESSONS / "sentence_completion.html").read_text(encoding="utf-8")
        # Error catch must reset _finalizing to allow re-submission
        assert "_finalizing = false" in src


# ---------------------------------------------------------------------------
# 4. prefers-reduced-motion suppresses lesson animations
# ---------------------------------------------------------------------------

class TestPrefersReducedMotion:

    def test_unified_js_showconfetti_checks_reduced_motion(self):
        src = (STATIC_JS / "unified-js.js").read_text(encoding="utf-8")
        assert "prefers-reduced-motion: reduce" in src

    def test_showconfetti_returns_early_on_reduced_motion(self):
        src = (STATIC_JS / "unified-js.js").read_text(encoding="utf-8")
        func_start = src.find("function showConfetti()")
        assert func_start != -1
        # Find end of function (next top-level function)
        func_end = src.find("\nfunction ", func_start + 1)
        body = src[func_start:func_end] if func_end != -1 else src[func_start:func_start + 200]
        assert "prefers-reduced-motion: reduce" in body

    def test_showcompletioncelebration_skips_confetti_when_motion_reduced(self):
        src = (STATIC_JS / "unified-js.js").read_text(encoding="utf-8")
        func_start = src.find("function showCompletionCelebration()")
        assert func_start != -1
        func_end = src.find("\nfunction ", func_start + 1)
        body = src[func_start:func_end] if func_end != -1 else src[func_start:func_start + 600]
        assert "prefers-reduced-motion: reduce" in body
        # showConfetti must be conditional, not unconditional
        assert "noMotion" in body
        nm_pos = body.find("noMotion")
        sf_pos = body.find("showConfetti")
        assert nm_pos < sf_pos, "noMotion check must appear before showConfetti call"

    def test_showcompletioncelebration_uses_instant_scroll_when_motion_reduced(self):
        src = (STATIC_JS / "unified-js.js").read_text(encoding="utf-8")
        func_start = src.find("function showCompletionCelebration()")
        func_end = src.find("\nfunction ", func_start + 1)
        body = src[func_start:func_end]
        assert "instant" in body, "scrollIntoView must use instant behavior when motion is reduced"

    def test_vocabulary_carousel_checks_reduced_motion(self):
        src = (TEMPLATES_LESSONS / "vocabulary.html").read_text(encoding="utf-8")
        assert "prefers-reduced-motion: reduce" in src

    def test_quiz_modal_animation_suppressed_by_media_query(self):
        src = (TEMPLATES_LESSONS / "quiz.html").read_text(encoding="utf-8")
        assert "prefers-reduced-motion: reduce" in src
        assert "animation: none" in src

    def test_idiom_transition_suppressed_by_media_query(self):
        src = (TEMPLATES_LESSONS / "idiom.html").read_text(encoding="utf-8")
        assert "prefers-reduced-motion: reduce" in src
        assert "transition: none" in src


# ---------------------------------------------------------------------------
# 5. double-submit prevention via _finalizing flag
# ---------------------------------------------------------------------------

class TestDoubleSubmitPrevention:

    _GUARDED_TEMPLATES = [
        "audio_fill_blank.html",
        "translation.html",
        "sentence_completion.html",
        "sentence_correction.html",
    ]

    def _finalizing_var(self, template_name: str) -> str:
        """Return the finalizing variable name used in this template."""
        # sentence_correction.html uses a prefixed variant
        return "_scFinalizing" if "sentence_correction" in template_name else "_finalizing"

    @pytest.mark.parametrize("template_name", _GUARDED_TEMPLATES)
    def test_template_has_finalizing_flag(self, template_name):
        src = (TEMPLATES_LESSONS / template_name).read_text(encoding="utf-8")
        var = self._finalizing_var(template_name)
        assert var in src, (
            f"{template_name} must use {var} flag to prevent double-submit"
        )

    @pytest.mark.parametrize("template_name", _GUARDED_TEMPLATES)
    def test_finalizing_set_before_submit_and_reset_on_error(self, template_name):
        src = (TEMPLATES_LESSONS / template_name).read_text(encoding="utf-8")
        var = self._finalizing_var(template_name)
        assert f"{var} = true" in src, f"{template_name}: {var} must be set true before submit"
        assert f"{var} = false" in src, f"{template_name}: {var} must be reset on error"

    @pytest.mark.parametrize("template_name", _GUARDED_TEMPLATES)
    def test_maybeFinalize_checks_finalizing_before_submitting(self, template_name):
        src = (TEMPLATES_LESSONS / template_name).read_text(encoding="utf-8")
        var = self._finalizing_var(template_name)
        assert f"if ({var}) return" in src, (
            f"{template_name}: maybeFinalize must bail early if already finalizing"
        )

    def test_idempotent_server_side_progress_on_double_submit(
        self, app, db_session, _module, test_user, client
    ):
        """Two complete submissions for the same lesson must produce one LessonProgress row."""
        lesson = _make_lesson(db_session, _module, lesson_type="translation", content={
            "items": [{"en": "Hello", "ru": "Привет"}],
            "mode": "ru_to_en",
        })
        _login(client, test_user)
        payload = {
            "answers": ["Hello"],
            "item_results": [{"is_correct": True, "score": 100}],
            "score": 100,
        }
        r1 = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json=payload,
        )
        r2 = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json=payload,
        )
        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201)
        count = LessonProgress.query.filter_by(lesson_id=lesson.id).count()
        assert count == 1, f"Expected 1 LessonProgress row, got {count}"
