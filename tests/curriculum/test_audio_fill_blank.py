"""Tests for the audio_fill_blank exercise type.

Task 6: Audio fill-in-blank exercise type — validator, grader, template, route.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from marshmallow import ValidationError

from app.curriculum.grading import grade_audio_fill_blank
from app.curriculum.validators import LessonContentValidator
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestAudioFillBlankValidator:
    VALID_CONTENT = {
        'audio_url': '/static/audio/lesson.mp3',
        'items': [
            {'text_with_gap': 'She ___ to school.', 'answer': 'goes'},
            {'text_with_gap': 'I ___ reading.', 'answer': 'like',
             'options': ['like', 'likes', 'liked', 'liking']},
        ],
    }

    def test_valid_content_passes(self):
        ok, err, _ = LessonContentValidator.validate('audio_fill_blank', self.VALID_CONTENT)
        assert ok is True
        assert err is None

    def test_missing_audio_url_fails(self):
        content = {'items': [{'text_with_gap': 'x', 'answer': 'y'}]}
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('audio_fill_blank', content)

    def test_missing_items_fails(self):
        content = {'audio_url': '/audio.mp3'}
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('audio_fill_blank', content)

    def test_empty_items_list_fails(self):
        content = {'audio_url': '/audio.mp3', 'items': []}
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('audio_fill_blank', content)

    def test_item_missing_answer_fails(self):
        content = {
            'audio_url': '/audio.mp3',
            'items': [{'text_with_gap': 'She ___ happy.'}],
        }
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('audio_fill_blank', content)

    def test_item_missing_text_with_gap_fails(self):
        content = {
            'audio_url': '/audio.mp3',
            'items': [{'answer': 'goes'}],
        }
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('audio_fill_blank', content)

    def test_optional_audio_clip_url_allowed(self):
        content = {
            'audio_url': '/audio.mp3',
            'items': [
                {'text_with_gap': 'x', 'answer': 'y', 'audio_clip_url': '/clip.mp3'}
            ],
        }
        ok, _, _ = LessonContentValidator.validate('audio_fill_blank', content)
        assert ok is True

    def test_options_field_optional(self):
        content = {
            'audio_url': '/audio.mp3',
            'items': [
                {'text_with_gap': 'x', 'answer': 'y'},
            ],
        }
        ok, _, _ = LessonContentValidator.validate('audio_fill_blank', content)
        assert ok is True


# ---------------------------------------------------------------------------
# Grader tests
# ---------------------------------------------------------------------------

class TestGradeAudioFillBlank:
    def _items(self):
        return [
            {'text_with_gap': 'She ___ to school.', 'answer': 'goes'},
            {'text_with_gap': 'I ___ reading.', 'answer': 'like'},
            {'text_with_gap': 'They ___ happy.', 'answer': 'are'},
            {'text_with_gap': 'We ___ friends.', 'answer': 'are'},
            {'text_with_gap': 'He ___ a dog.', 'answer': 'has'},
        ]

    def test_all_correct_returns_100(self):
        items = self._items()
        result = grade_audio_fill_blank(
            ['goes', 'like', 'are', 'are', 'has'], items
        )
        assert result['score'] == 100
        assert result['passed'] is True
        assert result['correct_items'] == 5

    def test_no_correct_returns_0(self):
        items = self._items()
        result = grade_audio_fill_blank(
            ['wrong', 'wrong', 'wrong', 'wrong', 'wrong'], items
        )
        assert result['score'] == 0
        assert result['passed'] is False
        assert result['correct_items'] == 0

    def test_typo_tolerance_single_word(self):
        # 'goas' vs 'goes': replace 'a' with 'e' = 1 edit, passes tolerance
        items = [{'text_with_gap': 'She ___.', 'answer': 'goes'}]
        result = grade_audio_fill_blank(['goas'], items)
        assert result['correct_items'] == 1
        assert result['passed'] is True

    def test_typo_not_tolerated_for_short_word(self):
        items = [{'text_with_gap': '___ up.', 'answer': 'get'}]
        result = grade_audio_fill_blank(['got'], items)
        assert result['correct_items'] == 0

    def test_partial_score_calculated_correctly(self):
        items = self._items()
        result = grade_audio_fill_blank(
            ['goes', 'wrong', 'wrong', 'wrong', 'wrong'], items
        )
        assert result['score'] == 20
        assert result['passed'] is False
        assert result['correct_items'] == 1

    def test_multi_item_scoring_3_of_5_passes(self):
        items = self._items()
        result = grade_audio_fill_blank(
            ['goes', 'like', 'are', 'wrong', 'wrong'], items
        )
        assert result['score'] == 60
        assert result['passed'] is False

    def test_4_of_5_passes_threshold(self):
        items = self._items()
        result = grade_audio_fill_blank(
            ['goes', 'like', 'are', 'are', 'wrong'], items
        )
        assert result['score'] == 80
        assert result['passed'] is True

    def test_options_mode_exact_match_required(self):
        items = [
            {
                'text_with_gap': 'She ___ to school.',
                'answer': 'goes',
                'options': ['go', 'goes', 'going', 'gone'],
            }
        ]
        result = grade_audio_fill_blank(['gose'], items)
        assert result['correct_items'] == 0

    def test_options_mode_correct_option_passes(self):
        items = [
            {
                'text_with_gap': 'She ___ to school.',
                'answer': 'goes',
                'options': ['go', 'goes', 'going', 'gone'],
            }
        ]
        result = grade_audio_fill_blank(['goes'], items)
        assert result['correct_items'] == 1
        assert result['passed'] is True

    def test_empty_user_answers_returns_zero(self):
        items = self._items()
        result = grade_audio_fill_blank([], items)
        assert result['score'] == 0
        assert result['correct_items'] == 0

    def test_empty_items_returns_zero(self):
        result = grade_audio_fill_blank(['ans'], [])
        assert result['score'] == 0
        assert result['total_items'] == 0

    def test_item_results_have_correct_structure(self):
        items = [{'text_with_gap': 'x', 'answer': 'y'}]
        result = grade_audio_fill_blank(['y'], items)
        assert len(result['item_results']) == 1
        ir = result['item_results'][0]
        assert 'answer' in ir
        assert 'user_answer' in ir
        assert 'correct' in ir

    def test_punctuation_stripped_in_answer(self):
        items = [{'text_with_gap': 'She ___ happy.', 'answer': 'is'}]
        result = grade_audio_fill_blank(['is.'], items)
        assert result['correct_items'] == 1

    def test_case_insensitive_match(self):
        items = [{'text_with_gap': '___ a book.', 'answer': 'Read'}]
        result = grade_audio_fill_blank(['read'], items)
        assert result['correct_items'] == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _make_afb_lesson(db_session, *, items=None) -> Lessons:
    if items is None:
        items = [
            {'text_with_gap': 'She ___ to school.', 'answer': 'goes'},
            {'text_with_gap': 'I ___ reading.', 'answer': 'like'},
        ]
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
        title="AFB Test",
        type="audio_fill_blank",
        content={
            "audio_url": "/static/audio/test.mp3",
            "items": items,
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
# LESSON_TYPE_TO_SOURCE mapping test
# ---------------------------------------------------------------------------

def test_audio_fill_blank_mapped_to_audio_fill_blank_source():
    from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE
    assert LESSON_TYPE_TO_SOURCE.get('audio_fill_blank') == 'linear_curriculum_audio_fill_blank'


# ---------------------------------------------------------------------------
# Route GET tests
# ---------------------------------------------------------------------------

class TestAudioFillBlankRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        assert resp.status_code == 200

    def test_lesson_detail_redirects_to_afb_route(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "audio-fill-blank" in resp.headers.get("Location", "")

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"


# ---------------------------------------------------------------------------
# Route POST submit tests
# ---------------------------------------------------------------------------

class TestAudioFillBlankSubmit:
    def _submit(self, client, lesson_id: int, answers: list):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"answers": answers, "lesson_type": "audio_fill_blank"},
            content_type="application/json",
        )

    def test_all_correct_returns_passed_true(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = self._submit(client, lesson.id, ["goes", "like"])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is True
        assert data["score"] == 100

    def test_all_wrong_returns_passed_false(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = self._submit(client, lesson.id, ["wrong", "wrong"])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["passed"] is False
        assert data["score"] == 0

    def test_response_includes_item_results(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = self._submit(client, lesson.id, ["goes", "like"])
        data = resp.get_json()
        assert "item_results" in data
        assert len(data["item_results"]) == 2

    def test_response_hides_answers_on_failure(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        # Failed submission should NOT reveal correct answers in item_results
        fail_resp = self._submit(client, lesson.id, ["wrong", "wrong"])
        fail_data = fail_resp.get_json()
        assert fail_data["passed"] is False
        for item in fail_data["item_results"]:
            assert "answer" not in item
        # Passed submission SHOULD include the canonical answers
        pass_resp = self._submit(client, lesson.id, ["goes", "like"])
        pass_data = pass_resp.get_json()
        assert pass_data["passed"] is True
        assert len(pass_data["item_results"]) == 2
        for item in pass_data["item_results"]:
            assert "answer" in item

    def test_passed_marks_progress_completed(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        self._submit(client, lesson.id, ["goes", "like"])
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_options_mode_correct_answer(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(
            db_session,
            items=[{
                'text_with_gap': 'She ___ to school.',
                'answer': 'goes',
                'options': ['go', 'goes', 'going', 'gone'],
            }],
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = self._submit(client, lesson.id, ["goes"])
        data = resp.get_json()
        assert data["passed"] is True

    def test_options_mode_wrong_answer(self, app, db_session, test_user, client):
        lesson = _make_afb_lesson(
            db_session,
            items=[{
                'text_with_gap': 'She ___ to school.',
                'answer': 'goes',
                'options': ['go', 'goes', 'going', 'gone'],
            }],
        )
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/audio-fill-blank")
        resp = self._submit(client, lesson.id, ["go"])
        data = resp.get_json()
        assert data["passed"] is False


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _read_afb_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "audio_fill_blank.html"
    )
    return p.read_text(encoding="utf-8")


class TestAudioFillBlankTemplate:
    def test_template_exists(self):
        tpl = _read_afb_template()
        assert len(tpl) > 100

    def test_audio_element_present(self):
        tpl = _read_afb_template()
        assert "<audio" in tpl

    def test_live_grading_submits_to_api(self):
        """Audio fill-blank uses live per-item grading; the final canonical
        submit fires automatically once every item is in a terminal state.
        We just assert the submit endpoint is hit from the template."""
        tpl = _read_afb_template()
        assert "/curriculum/api/lesson/" in tpl
        assert "/submit" in tpl

    def test_afb_item_class_present(self):
        tpl = _read_afb_template()
        assert 'afb-item' in tpl

    def test_options_rendering_condition_present(self):
        tpl = _read_afb_template()
        assert 'item.options' in tpl

    def test_free_text_input_present(self):
        tpl = _read_afb_template()
        assert 'afb-input' in tpl

    def test_reveal_area_present(self):
        tpl = _read_afb_template()
        assert 'afb-reveal' in tpl

    def test_show_results_function_present(self):
        tpl = _read_afb_template()
        assert 'function showResults(' in tpl

    def test_item_iteration_present(self):
        tpl = _read_afb_template()
        assert 'for item in items' in tpl


# ---------------------------------------------------------------------------
# CSS tests
# ---------------------------------------------------------------------------

def _read_css() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "static"
        / "css"
        / "design-system.css"
    )
    return p.read_text(encoding="utf-8")


class TestAudioFillBlankCSS:
    def test_afb_item_class_defined(self):
        css = _read_css()
        assert '.afb-item {' in css or '.afb-item{' in css

    def test_afb_input_class_defined(self):
        css = _read_css()
        assert '.afb-input {' in css or '.afb-input{' in css

    def test_afb_correct_state_defined(self):
        css = _read_css()
        assert '.afb-item--correct' in css

    def test_afb_wrong_state_defined(self):
        css = _read_css()
        assert '.afb-item--wrong' in css

    def test_afb_option_btn_defined(self):
        css = _read_css()
        assert '.afb-option-btn' in css
