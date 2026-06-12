"""Tests for module test-out (сдача модуля экстерном)."""
from __future__ import annotations

import pytest

from app.curriculum.models import (
    CEFRLevel, LessonProgress, Lessons, Module, ModuleTestOut,
)
from app.curriculum.services.test_out import (
    TEST_OUT_MAX_ATTEMPTS_PER_DAY,
    apply_test_out_pass,
    collect_module_questions,
    get_test_out_state,
    grade_test_out,
    record_test_out_attempt,
)
from tests.conftest import unique_level_code


def _mc_question(i: int, correct_index: int = 0) -> dict:
    return {
        'type': 'multiple_choice',
        'question': f'Question {i}?',
        'options': ['alpha', 'beta', 'gamma'],
        'correct_index': correct_index,
    }


@pytest.fixture
def quiz_module(db_session):
    """Модуль №1 уровня с quiz-уроком (8 MC вопросов) и vocabulary-уроком."""
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M1', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    quiz = Lessons(
        module_id=module.id, number=1, title='Quiz', type='quiz',
        content={'questions': [_mc_question(i) for i in range(8)]},
    )
    vocab = Lessons(
        module_id=module.id, number=2, title='Vocab', type='vocabulary',
        content={'words': []},
    )
    db_session.add_all([quiz, vocab])
    db_session.commit()
    return module


@pytest.mark.smoke
class TestTestOutService:
    def test_collect_normalizes_questions(self, db_session, quiz_module):
        questions = collect_module_questions(quiz_module)
        assert len(questions) == 8
        assert all(q['type'] == 'multiple_choice' for q in questions)
        assert all(q['answer'] == 0 for q in questions)

    def test_state_available(self, db_session, test_user, quiz_module):
        state = get_test_out_state(test_user.id, quiz_module)
        assert state['available'] is True

    def test_state_attempts_exhausted(self, db_session, test_user, quiz_module):
        from app.utils.db import db
        for _ in range(TEST_OUT_MAX_ATTEMPTS_PER_DAY):
            record_test_out_attempt(test_user.id, quiz_module.id, 40, False, db)
        db_session.commit()
        state = get_test_out_state(test_user.id, quiz_module)
        assert state['available'] is False
        assert state['reason'] == 'attempts_exhausted'

    def test_state_already_passed(self, db_session, test_user, quiz_module):
        from app.utils.db import db
        record_test_out_attempt(test_user.id, quiz_module.id, 90, True, db)
        db_session.commit()
        state = get_test_out_state(test_user.id, quiz_module)
        assert state['available'] is False
        assert state['reason'] == 'already_passed'

    def test_grade_and_apply_pass(self, db_session, test_user, quiz_module):
        from app.utils.db import db
        questions = collect_module_questions(quiz_module)
        answers = {str(i): 0 for i in range(len(questions))}
        result = grade_test_out(questions, answers)
        assert result['passed'] is True
        touched = apply_test_out_pass(test_user.id, quiz_module, result['score'], db)
        db_session.commit()
        assert touched == 2  # quiz + vocabulary
        rows = (
            db_session.query(LessonProgress)
            .join(Lessons, LessonProgress.lesson_id == Lessons.id)
            .filter(
                LessonProgress.user_id == test_user.id,
                Lessons.module_id == quiz_module.id,
            )
            .all()
        )
        assert len(rows) == 2
        assert all(r.status == 'completed' for r in rows)
        assert all((r.data or {}).get('test_out') is True for r in rows)

    def test_grade_below_threshold_fails(self, db_session, quiz_module):
        questions = collect_module_questions(quiz_module)
        answers = {str(i): 1 for i in range(len(questions))}  # все неверные
        result = grade_test_out(questions, answers)
        assert result['passed'] is False


@pytest.mark.smoke
class TestTestOutRoutes:
    def test_page_renders(self, authenticated_client, db_session, quiz_module):
        resp = authenticated_client.get(f'/curriculum/module/{quiz_module.id}/test-out')
        assert resp.status_code == 200
        assert b'mto-form-area' in resp.data

    def test_submit_without_get_409(self, authenticated_client, db_session, quiz_module):
        resp = authenticated_client.post(
            f'/curriculum/api/module/{quiz_module.id}/test-out',
            json={'answers': {}},
        )
        assert resp.status_code == 409

    def test_full_pass_flow(self, authenticated_client, db_session, test_user, quiz_module):
        resp = authenticated_client.get(f'/curriculum/module/{quiz_module.id}/test-out')
        assert resp.status_code == 200
        answers = {str(i): 0 for i in range(8)}
        resp = authenticated_client.post(
            f'/curriculum/api/module/{quiz_module.id}/test-out',
            json={'answers': answers},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['passed'] is True
        assert data['completed_lessons'] == 2

        attempt = (
            db_session.query(ModuleTestOut)
            .filter_by(user_id=test_user.id, module_id=quiz_module.id)
            .first()
        )
        assert attempt is not None and attempt.passed is True

        # Повторный заход — экстерн больше не доступен
        resp = authenticated_client.get(f'/curriculum/module/{quiz_module.id}/test-out')
        assert resp.status_code == 302
