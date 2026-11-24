"""PostgreSQL row locking when two administrators press the same approval."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

from flask import Flask
import pytest

from app.curriculum import answer_review as worker
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.answer_review_editor import editor_decide, editor_preview, editor_version
from app.utils.db import db
from tests.answer_review_fixtures import telegram_admin


def test_concurrent_admin_decisions_apply_once_in_postgres(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.native_lessons import project_questions
    from app.curriculum.answer_disputes import record_rejected_answer
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from tests.conftest import unique_level_code

    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Independent row locks require PostgreSQL')
    level = CEFRLevel(code=unique_level_code(), name='Dispute concurrency')
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title='Concurrent decisions')
    db.session.add(module)
    db.session.flush()
    answer = 'I go to work on foot.'
    lesson = Lessons(module_id=module.id, number=1, title='Travel', type='quiz', content={'questions': [
        {'type': 'translation', 'question': 'Я хожу на работу пешком.', 'correct_answer': 'I walk to work.'},
    ]})
    db.session.add(lesson)
    db.session.flush()
    record_rejected_answer(db.session, lesson, project_questions(lesson)[0], answer)
    case = AnswerDispute.query.filter_by(lesson_id=lesson.id).one()
    monkeypatch.setattr(ai, 'classify', Mock(return_value={'label': 'valid_variant', 'reason': 'Перевод верен.'}))
    worker.review_case(case, key='test-key', model='test-model')
    case.status = 'notified'
    assert editor_preview(case, 'add', answer)['accepts_report']
    version, case_id = editor_version(case), case.id
    db.session.commit()
    barrier = Barrier(2)

    def approve(user_id: int) -> str:
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                return editor_decide(case_id, user_id, version, 'add', answer)
            except ValueError as error:
                assert 'Спор изменился' in str(error)
                db.session.rollback()
                return 'outdated'

    try:
        with telegram_admin() as first, telegram_admin() as second:
            editor_ids = (first.user_id, second.user_id)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(approve, recipient) for recipient in editor_ids]
                outcomes = [future.result(timeout=15) for future in futures]
            assert sorted(outcomes) == sorted(['Правка сохранена.', 'outdated'])
            winner = editor_ids[outcomes.index('Правка сохранена.')]
            db.session.refresh(lesson)
            db.session.refresh(case)
            assert case.review['decided_by_user_id'] == winner
            assert case.status == 'applied' and lesson.content['questions'][0]['alternative_answers'] == [answer]
    finally:
        db.session.rollback()
        db.session.delete(case)
        db.session.delete(lesson)
        db.session.flush()
        db.session.delete(module)
        db.session.flush()
        db.session.delete(level)
        db.session.commit()
