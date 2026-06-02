"""Tests for sentence correction exercise type — Task 18."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.grading import grade_sentence_correction
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sentence_correction_lesson(
    db_session,
    *,
    incorrect_sentence: str = "She go to school every day.",
    correct_sentence: str = "She goes to school every day.",
    error_type: str = "subject-verb agreement",
    explanation: str = "Third-person singular requires -s on the verb.",
    options=None,
) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Correction Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    content = {
        "incorrect_sentence": incorrect_sentence,
        "correct_sentence": correct_sentence,
        "error_type": error_type,
        "explanation": explanation,
    }
    if options is not None:
        content["options"] = options
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Correction Test",
        type="sentence_correction",
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

class TestSentenceCorrectionValidator:
    def test_valid_payload_passes(self):
        ok, err, _ = LessonContentValidator.validate(
            'sentence_correction',
            {
                "incorrect_sentence": "He go to work.",
                "correct_sentence": "He goes to work.",
                "error_type": "subject-verb agreement",
                "explanation": "Use goes with he/she/it.",
            }
        )
        assert ok is True
        assert err is None

    def test_valid_payload_with_options(self):
        ok, err, _ = LessonContentValidator.validate(
            'sentence_correction',
            {
                "incorrect_sentence": "He go to work.",
                "correct_sentence": "He goes to work.",
                "error_type": "subject-verb agreement",
                "explanation": "Use goes with he/she/it.",
                "options": [
                    "He go to work.",
                    "He goes to work.",
                    "He gone to work.",
                    "He going to work.",
                ],
            }
        )
        assert ok is True

    def test_missing_incorrect_sentence_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'sentence_correction',
                {
                    "correct_sentence": "He goes to work.",
                    "error_type": "verb",
                    "explanation": "explanation",
                }
            )

    def test_missing_correct_sentence_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'sentence_correction',
                {
                    "incorrect_sentence": "He go to work.",
                    "error_type": "verb",
                    "explanation": "explanation",
                }
            )

    def test_missing_explanation_passes(self):
        # explanation is now optional at the top level — multi-item flow
        # carries explanation per item, and even single-item lessons may
        # legitimately omit it (the template hides the block when empty).
        is_valid, error_msg, _ = LessonContentValidator.validate(
            'sentence_correction',
            {
                "incorrect_sentence": "He go to work.",
                "correct_sentence": "He goes to work.",
                "error_type": "verb",
            }
        )
        assert is_valid, f"expected valid, got error: {error_msg}"


# ---------------------------------------------------------------------------
# Grader tests
# ---------------------------------------------------------------------------

class TestGradeSentenceCorrection:
    def test_exact_match_correct(self):
        result = grade_sentence_correction(
            "She goes to school every day.",
            "She goes to school every day.",
        )
        assert result['is_correct'] is True

    def test_wrong_answer_incorrect(self):
        result = grade_sentence_correction(
            "She go to school every day.",
            "She goes to school every day.",
        )
        assert result['is_correct'] is False

    def test_punctuation_ignored(self):
        result = grade_sentence_correction(
            "She goes to school every day",
            "She goes to school every day.",
        )
        assert result['is_correct'] is True

    def test_case_insensitive(self):
        result = grade_sentence_correction(
            "she goes to school every day.",
            "She goes to school every day.",
        )
        assert result['is_correct'] is True

    def test_extra_spaces_stripped(self):
        result = grade_sentence_correction(
            "  She goes to school every day.  ",
            "She goes to school every day.",
        )
        assert result['is_correct'] is True

    def test_returns_correct_sentence_in_result(self):
        result = grade_sentence_correction("wrong", "Right answer.")
        assert result['correct_sentence'] == "Right answer."

    def test_returns_user_answer_in_result(self):
        result = grade_sentence_correction("my answer", "Right answer.")
        assert result['user_answer'] == "my answer"

    def test_no_levenshtein_tolerance_for_multiword(self):
        # Sentence correction uses exact match only — no typo tolerance
        result = grade_sentence_correction(
            "She goos to school every day.",
            "She goes to school every day.",
        )
        assert result['is_correct'] is False


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _read_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "sentence_correction.html"
    )
    return p.read_text(encoding="utf-8")


class TestSentenceCorrectionTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 100

    def test_incorrect_sentence_rendered(self):
        tpl = _read_template()
        assert "incorrect-sentence" in tpl

    def test_submit_function_present(self):
        tpl = _read_template()
        assert "submitCorrection()" in tpl

    def test_result_badge_present(self):
        tpl = _read_template()
        assert 'id="result-badge"' in tpl

    def test_explanation_reveal_present(self):
        tpl = _read_template()
        assert "explanation-reveal" in tpl

    def test_correct_answer_reveal_present(self):
        tpl = _read_template()
        assert "correct-answer-reveal" in tpl

    def test_options_conditional_block(self):
        tpl = _read_template()
        assert "{% if options %}" in tpl

    def test_options_button_rendered(self):
        tpl = _read_template()
        assert "sentence-correction-option-btn" in tpl

    def test_next_lesson_area_present(self):
        tpl = _read_template()
        assert "correction-next-area" in tpl

    def test_daily_plan_uses_refreshed_submit_context(self):
        tpl = _read_template()
        assert "const dpSource = (data && data.daily_plan_ctx) ? data.daily_plan_ctx : DAILY_PLAN_CTX;" in tpl
        assert "const dp = (dpSource && dpSource.is_daily_plan) ? dpSource : null;" in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestSentenceCorrectionLessonRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        assert resp.status_code == 200

    def test_get_contains_incorrect_sentence(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, incorrect_sentence="He go to the store."
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        assert "He go to the store." in resp.get_data(as_text=True)

    def test_get_redirects_wrong_type(self, app, db_session, test_user, client, test_lesson_vocabulary):
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{test_lesson_vocabulary.id}/sentence-correction")
        assert resp.status_code in (302, 400)

    def test_lesson_detail_redirects_to_sentence_correction_route(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "sentence-correction" in resp.headers.get("Location", "")

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_get_shows_options_when_present(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session,
            options=["He go.", "He goes.", "He gone.", "He going."],
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        html = resp.get_data(as_text=True)
        assert "sentence-correction-option-btn" in html
        assert "He goes." in html

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_sentence_correction_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        assert resp.status_code in (302, 401, 403)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestSentenceCorrectionSubmitRoute:
    def _submit(self, client, lesson_id: int, user_answer: str):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"user_answer": user_answer, "lesson_type": "sentence_correction"},
            content_type="application/json",
        )

    def test_correct_answer_returns_is_correct_true(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, correct_sentence="She goes to school every day."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = self._submit(client, lesson.id, "She goes to school every day.")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_correct"] is True

    def test_wrong_answer_returns_is_correct_false(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, correct_sentence="She goes to school every day."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = self._submit(client, lesson.id, "She go to school every day.")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_correct"] is False

    def test_wrong_answer_includes_correct_sentence(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, correct_sentence="She goes to school every day."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = self._submit(client, lesson.id, "wrong answer")
        data = resp.get_json()
        assert data.get("correct_sentence") == "She goes to school every day."

    def test_explanation_included_in_response(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, explanation="Use goes with he/she/it."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        resp = self._submit(client, lesson.id, "wrong")
        data = resp.get_json()
        assert data.get("explanation") == "Use goes with he/she/it."

    def test_correct_answer_marks_progress_completed(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, correct_sentence="She goes to school every day."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        self._submit(client, lesson.id, "She goes to school every day.")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_wrong_answer_does_not_mark_completed(self, app, db_session, test_user, client):
        lesson = _make_sentence_correction_lesson(
            db_session, correct_sentence="She goes to school every day."
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-correction")
        self._submit(client, lesson.id, "totally wrong")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status != "completed"

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_sentence_correction_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_answer": "test", "lesson_type": "sentence_correction"},
        )
        assert resp.status_code in (302, 401, 403)
