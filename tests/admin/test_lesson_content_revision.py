"""Verify that stale lesson JSON cannot replace a newer saved revision."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.utils.db import db
from tests.api.test_course_receipt_expiry import sign_in


def _form(response: TestResponse) -> tuple[BeautifulSoup, dict[str, str]]:
    page = BeautifulSoup(response.data, 'html.parser')
    fields = page.select('#contentForm input[type=hidden]')
    return page, {field['name']: field['value'] for field in fields}


def _body(page: BeautifulSoup, selector: str = '#content') -> str:
    textarea = page.select_one(selector)
    assert textarea is not None
    return textarea.text.removeprefix('\n')


def _audit(lesson_id: int) -> Any:
    return AdminAuditLog.query.filter_by(action='curriculum.lesson.update_content', target_id=lesson_id)


def _content() -> dict[str, Any]:
    return {'questions': [
        {'type': 'multiple_choice', 'question': 'Choose a tree.', 'options': ['Oak', 'Rose'], 'correct_index': 0},
        {'type': 'multiple_choice', 'question': 'Choose another tree.', 'options': ['Birch', 'Tulip'], 'correct_index': 0},
    ]}


def test_two_sessions_require_review_and_keep_both_edits(
    app: Flask, admin_user: User, test_module: Module, db_session: scoped_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    lesson = Lessons(module_id=test_module.id, number=91, order=91, title='Synthetic concurrent edits',
                     type='quiz', content=_content())
    db_session.add(lesson)
    db_session.commit()
    path = f'/curriculum/admin/lesson/{lesson.id}/edit'
    first, second = app.test_client(), app.test_client()
    sign_in(first, app, admin_user)
    _, first_fields = _form(first.get(path))
    sign_in(second, app, admin_user)
    _, second_fields = _form(second.get(path))
    assert first_fields['content_revision'] == second_fields['content_revision']

    first_edit, second_edit = deepcopy(lesson.content), deepcopy(lesson.content)
    first_edit['questions'][1]['options'][0] = 'Maple'
    second_edit['questions'][0]['question'] = 'Which one is a tree?'
    draft = '\n' + json.dumps(second_edit, indent=2) + '\n'
    g.pop('csrf_token', None)
    posted = first.post(path, data={**first_fields, 'content': json.dumps(first_edit)})
    assert posted.status_code == 302
    db_session.refresh(lesson)
    first_saved_at = lesson.updated_at
    first_audit, = _audit(lesson.id).all()
    first_audit_id = first_audit.id

    g.pop('csrf_token', None)
    conflicted = second.post(path, data={**second_fields, 'content': draft})
    assert conflicted.status_code == 409
    review, review_fields = _form(conflicted)
    assert _body(review) == draft
    assert json.loads(_body(review, '#published-content')) == first_edit
    assert review.select_one('#published-content[readonly]')
    assert review.select_one('input[name=reviewed_content_conflict][required]')
    assert review_fields['content_revision'] != second_fields['content_revision']
    assert second.post(path, data={**review_fields, 'content': draft}).status_code == 409
    assert second.post(path, data={'csrf_token': second_fields['csrf_token'], 'content': draft}).status_code == 409
    db_session.refresh(lesson)
    assert lesson.content == first_edit and lesson.updated_at == first_saved_at
    assert [row.id for row in _audit(lesson.id)] == [first_audit_id]

    merged = deepcopy(first_edit)
    merged['questions'][0] = second_edit['questions'][0]
    confirmation = {**review_fields, 'reviewed_content_conflict': '1'}
    broken = deepcopy(merged)
    del broken['questions'][0]['options']
    refused = second.post(path, data={**confirmation, 'content': json.dumps(broken)})
    assert refused.status_code == 422 and 'Вопрос №1' in refused.text
    assert _audit(lesson.id).count() == 1
    _, repaired_fields = _form(refused)
    assert second.post(path, data={**repaired_fields, 'content': json.dumps(merged)}).status_code == 302
    db_session.refresh(lesson)
    assert lesson.content == merged
    history = _audit(lesson.id).order_by(AdminAuditLog.id).all()
    assert len(history) == 2 and history[0].id == first_audit_id
    assert second.post(path, data={**confirmation, 'content': json.dumps(merged)}).status_code == 409


def test_concurrent_posts_cannot_both_publish_the_same_revision(app: Flask) -> None:
    engine = db.engine
    if engine.dialect.name != 'postgresql':
        pytest.skip('Needs separate transactions and PostgreSQL row locks')
    suffix = uuid4().hex
    level = CEFRLevel(code='Y9', name='Synthetic lesson revision race')
    module = Module(level=level, number=1, title='Synthetic revision module')
    lesson = Lessons(module=module, number=1, order=1, title='Synthetic lesson revision race', type='quiz',
                     content=_content())
    user = User(username=f'lesson_revision_{suffix}', email=f'{suffix}@example.invalid',
                is_admin=True, active=True, onboarding_completed=True)
    user.set_password('synthetic-local-test')
    db.session.add_all([lesson, user])
    db.session.commit()
    lesson_id, level_id, user_id, login_id = lesson.id, level.id, user.id, user.get_id()
    path = f'/curriculum/admin/lesson/{lesson_id}/edit'
    ready = Barrier(2)

    def synchronize(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: ExecutionContext,
        executemany: bool,
    ) -> None:
        if 'FROM lessons' in statement and 'FOR UPDATE' in statement:
            ready.wait(timeout=8)

    def submit(key: str) -> tuple[int, str]:
        with app.app_context():
            client = app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = login_id
                session['_fresh'] = True
            _, form = _form(client.get(path))
            document = _content()
            document['questions'][0]['question'] = key
            return client.post(path, data={**form, 'content': json.dumps(document)}).status_code, key

    event.listen(engine, 'before_cursor_execute', synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(submit, key) for key in ('First concurrent edit?', 'Second concurrent edit?')]
            outcomes = [attempt.result(timeout=12) for attempt in attempts]
        assert sorted(status for status, _ in outcomes) == [302, 409]
        winner, = [key for status, key in outcomes if status == 302]
        db.session.expire_all()
        assert db.session.get(Lessons, lesson_id).content['questions'][0]['question'] == winner
        assert _audit(lesson_id).count() == 1
    finally:
        event.remove(engine, 'before_cursor_execute', synchronize)
        db.session.rollback()
        _audit(lesson_id).delete()
        db.session.delete(db.session.get(CEFRLevel, level_id))
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()
