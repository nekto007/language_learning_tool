"""Tests for sentence completion exercise type — Task 25."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.grading import grade_sentence_completion
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sentence_completion_lesson(db_session, *, items=None) -> Lessons:
    if items is None:
        items = [
            {'prompt': 'The cat sat on the', 'answer': 'mat'},
            {'prompt': 'She loves to read', 'answer': 'books'},
            {'prompt': 'He went to the', 'answer': 'store'},
        ]
    level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Completion Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Sentence Completion Test",
        type="sentence_completion",
        content={'items': items},
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

class TestSentenceCompletionValidator:
    def test_valid_payload_passes(self):
        ok, err, _ = LessonContentValidator.validate(
            'sentence_completion',
            {
                'items': [
                    {'prompt': 'The cat sat on the', 'answer': 'mat'},
                ]
            }
        )
        assert ok is True
        assert err is None

    def test_valid_payload_with_context(self):
        ok, err, _ = LessonContentValidator.validate(
            'sentence_completion',
            {
                'items': [
                    {
                        'prompt': 'She goes to',
                        'answer': 'school',
                        'context': 'Daily routine',
                    }
                ]
            }
        )
        assert ok is True

    def test_missing_items_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'sentence_completion',
                {'prompt': 'test', 'answer': 'test'}
            )

    def test_item_missing_prompt_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'sentence_completion',
                {'items': [{'answer': 'mat'}]}
            )

    def test_item_missing_answer_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'sentence_completion',
                {'items': [{'prompt': 'The cat sat on the'}]}
            )

    def test_empty_items_list_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'sentence_completion',
                {'items': []}
            )


# ---------------------------------------------------------------------------
# Grader tests
# ---------------------------------------------------------------------------

class TestGradeSentenceCompletion:
    def test_all_correct_score_100(self):
        items = [
            {'prompt': 'The cat sat on the', 'answer': 'mat'},
            {'prompt': 'She loves', 'answer': 'books'},
        ]
        result = grade_sentence_completion(['mat', 'books'], items)
        assert result['score'] == 100
        assert result['passed'] is True
        assert result['correct_items'] == 2
        assert result['total_items'] == 2

    def test_exact_match_passes(self):
        items = [{'prompt': 'She loves', 'answer': 'books'}]
        result = grade_sentence_completion(['books'], items)
        assert result['item_results'][0]['correct'] is True

    def test_typo_levenshtein_1_passes_single_word(self):
        items = [{'prompt': 'She loves', 'answer': 'books'}]
        result = grade_sentence_completion(['books'], items)
        assert result['item_results'][0]['correct'] is True

    def test_wrong_answer_fails(self):
        items = [{'prompt': 'She loves', 'answer': 'books'}]
        result = grade_sentence_completion(['cats'], items)
        assert result['item_results'][0]['correct'] is False

    def test_partial_score_calculated(self):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
            {'prompt': 'She', 'answer': 'sings'},
            {'prompt': 'He likes', 'answer': 'pizza'},
        ]
        result = grade_sentence_completion(['runs', 'wrong', 'pizza'], items)
        assert result['correct_items'] == 2
        assert result['total_items'] == 3
        assert result['score'] == 67

    def test_all_wrong_score_zero(self):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
            {'prompt': 'She', 'answer': 'sings'},
        ]
        result = grade_sentence_completion(['xyz', 'abc'], items)
        assert result['score'] == 0
        assert result['passed'] is False
        assert result['correct_items'] == 0

    def test_empty_items_returns_zero(self):
        result = grade_sentence_completion([], [])
        assert result['score'] == 0
        assert result['passed'] is False
        assert result['total_items'] == 0

    def test_fewer_answers_than_items_marks_missing_wrong(self):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
            {'prompt': 'She', 'answer': 'sings'},
        ]
        result = grade_sentence_completion(['runs'], items)
        assert result['item_results'][0]['correct'] is True
        assert result['item_results'][1]['correct'] is False

    def test_item_results_include_prompt_and_answer(self):
        items = [{'prompt': 'The cat', 'answer': 'runs', 'context': 'speed'}]
        result = grade_sentence_completion(['runs'], items)
        assert result['item_results'][0]['prompt'] == 'The cat'
        assert result['item_results'][0]['answer'] == 'runs'

    def test_normalization_case_insensitive(self):
        items = [{'prompt': 'She loves', 'answer': 'books'}]
        result = grade_sentence_completion(['BOOKS'], items)
        assert result['item_results'][0]['correct'] is True

    def test_normalization_strips_punctuation(self):
        items = [{'prompt': 'She loves', 'answer': 'books'}]
        result = grade_sentence_completion(['books!'], items)
        assert result['item_results'][0]['correct'] is True

    def test_multiword_answer_requires_exact_match(self):
        items = [{'prompt': 'She loves to read', 'answer': 'many books'}]
        result = grade_sentence_completion(['manny books'], items)
        assert result['item_results'][0]['correct'] is False

    def test_passing_threshold_70_percent(self):
        items = [{'prompt': str(i), 'answer': 'x'} for i in range(10)]
        answers = ['x'] * 7 + ['wrong'] * 3
        result = grade_sentence_completion(answers, items)
        assert result['score'] == 70
        assert result['passed'] is True

    def test_below_threshold_fails(self):
        items = [{'prompt': str(i), 'answer': 'x'} for i in range(10)]
        answers = ['x'] * 6 + ['wrong'] * 4
        result = grade_sentence_completion(answers, items)
        assert result['score'] == 60
        assert result['passed'] is False


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
        / "sentence_completion.html"
    )
    return p.read_text(encoding="utf-8")


class TestSentenceCompletionTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 100

    def test_completion_items_list_rendered(self):
        tpl = _read_template()
        assert "completion-items-list" in tpl

    def test_input_field_per_item(self):
        tpl = _read_template()
        assert "sentence-completion-input" in tpl

    def test_submit_function_present(self):
        tpl = _read_template()
        assert "submitCompletion()" in tpl

    def test_feedback_per_item_rendered(self):
        tpl = _read_template()
        assert 'sentence-completion-item-feedback' in tpl

    def test_given_up_state_present(self):
        # Live-flow given-up surface: the learner's last wrong value stays
        # in the input (red --given class), the correction block below
        # shows "Ваш ответ / Правильно", and the action row offers
        # _retryGivenUp to unlock items for another try.
        tpl = _read_template()
        assert 'sentence-completion-input--given' in tpl
        assert 'sentence-completion-correction' in tpl
        assert '_retryGivenUp' in tpl
        assert 'MAX_ATTEMPTS' in tpl

    def test_score_card_present(self):
        tpl = _read_template()
        assert 'sentence-completion-score-card' in tpl

    def test_next_lesson_area_present(self):
        tpl = _read_template()
        assert 'completion-next-area' in tpl

    def test_context_conditional_block(self):
        tpl = _read_template()
        assert 'item.context' in tpl

    def test_correct_badge_present(self):
        tpl = _read_template()
        assert 'sentence-completion-badge--correct' in tpl

    def test_incorrect_badge_present(self):
        tpl = _read_template()
        assert 'sentence-completion-badge--incorrect' in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestSentenceCompletionLessonRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        assert resp.status_code == 200

    def test_get_contains_prompt_text(self, app, db_session, test_user, client):
        items = [{'prompt': 'The quick brown fox', 'answer': 'jumps'}]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        assert "The quick brown fox" in resp.get_data(as_text=True)

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_lesson_detail_redirects_to_completion_route(self, app, db_session, test_user, client):
        lesson = _make_sentence_completion_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "sentence-completion" in resp.headers.get("Location", "")

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_sentence_completion_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        assert resp.status_code in (302, 401, 403)

    def test_wrong_lesson_type_redirects(self, app, db_session, test_user, client, test_lesson_vocabulary):
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{test_lesson_vocabulary.id}/sentence-completion")
        assert resp.status_code in (302, 400)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestSentenceCompletionSubmitRoute:
    def _submit(self, client, lesson_id: int, answers: list):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"answers": answers, "lesson_type": "sentence_completion"},
            content_type="application/json",
        )

    def test_all_correct_returns_passed_true(self, app, db_session, test_user, client):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
            {'prompt': 'She', 'answer': 'sings'},
        ]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = self._submit(client, lesson.id, ['runs', 'sings'])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['passed'] is True
        assert data['score'] == 100

    def test_partial_score_returned(self, app, db_session, test_user, client):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
            {'prompt': 'She', 'answer': 'sings'},
            {'prompt': 'He', 'answer': 'walks'},
        ]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = self._submit(client, lesson.id, ['runs', 'wrong', 'wrong'])
        data = resp.get_json()
        assert data['score'] == 33
        assert data['passed'] is False

    def test_all_wrong_score_zero(self, app, db_session, test_user, client):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
        ]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = self._submit(client, lesson.id, ['xyz'])
        data = resp.get_json()
        assert data['score'] == 0
        assert data['passed'] is False

    def test_correct_answers_mark_progress_completed(self, app, db_session, test_user, client):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
            {'prompt': 'She', 'answer': 'sings'},
        ]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        self._submit(client, lesson.id, ['runs', 'sings'])
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_wrong_answers_do_not_mark_completed(self, app, db_session, test_user, client):
        items = [
            {'prompt': 'The cat', 'answer': 'runs'},
        ]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        self._submit(client, lesson.id, ['xyz'])
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status != "completed"

    def test_item_results_in_response(self, app, db_session, test_user, client):
        items = [{'prompt': 'The cat', 'answer': 'runs'}]
        lesson = _make_sentence_completion_lesson(db_session, items=items)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/sentence-completion")
        resp = self._submit(client, lesson.id, ['runs'])
        data = resp.get_json()
        assert 'item_results' in data
        assert len(data['item_results']) == 1
        assert data['item_results'][0]['correct'] is True

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_sentence_completion_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"answers": ["test"], "lesson_type": "sentence_completion"},
        )
        assert resp.status_code in (302, 401, 403)
