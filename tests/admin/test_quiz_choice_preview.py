"""The choice preview grades an editor draft without publishing or attempting it."""

from copy import deepcopy
import json
from typing import Any

from bs4 import BeautifulSoup
from flask import Flask, g
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext

from app.achievements.models import StreakEvent, UserStatistics
from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.models import LessonAttempt, LessonProgress
from app.daily_plan.linear.models import QuizErrorLog
from app.notifications.models import Notification
from app.utils.db import db
from tests.api.test_course_receipt_expiry import receipt, sign_in


def _effects(lesson_id: int) -> list[int]:
    return [
        LessonAttempt.query.filter_by(lesson_id=lesson_id).count(),
        LessonProgress.query.filter_by(lesson_id=lesson_id).count(),
        AnswerDispute.query.filter_by(lesson_id=lesson_id).count(),
        UserStatistics.query.count(), StreakEvent.query.count(), QuizErrorLog.query.count(),
        Notification.query.count(), AdminAuditLog.query.filter_by(target_type='lesson', target_id=lesson_id).count(),
    ]


def test_choice_preview_projects_and_rechecks_the_unsaved_revision_without_writes(
    receipt: dict[str, Any], app: Flask, admin_user: User,  # noqa: F811
) -> None:
    lesson = receipt['lesson']
    original, updated = deepcopy(lesson.content), lesson.updated_at
    admin = app.test_client()
    headers = sign_in(admin, app, admin_user)
    found = admin.get('/admin/materials', query_string={'kind': 'lesson', 'level': 'A1', 'q': f'#{lesson.id}'})
    editor = BeautifulSoup(found.data, 'html.parser').select_one(f'a[href*="/lesson/{lesson.id}/edit"]')
    assert found.status_code == 200 and editor is not None
    page = admin.get(editor['href'])
    panel = BeautifulSoup(page.data, 'html.parser').select_one('[data-quiz-choice-preview]')
    assert page.status_code == 200 and panel is not None
    path = panel['data-quiz-choice-preview']
    draft = deepcopy(original)
    draft['questions'][0] = {
        'type': 'multiple_choice', 'question': 'Which tree has white bark?',
        'instruction': 'Select one tree.', 'question_ru': 'Какое дерево имеет белую кору?',
        'options': ['Pine', 'Birch', 'Oak'], 'correct_index': 1,
    }
    data = {'content': json.dumps(draft), 'question_number': 1}
    before = _effects(lesson.id)
    writes = []

    def record(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: ExecutionContext, executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')):
            writes.append(statement.split(maxsplit=1)[0])

    event.listen(db.engine, 'before_cursor_execute', record)
    try:
        displayed = admin.post(path, headers=headers, json=data)
        assert displayed.status_code == 200 and displayed.headers['Cache-Control'] == 'private, no-store'
        assert 'feedback' not in displayed.json
        question = displayed.json['question']
        assert question['instruction'] == 'Select one tree.' and question['prompt'] == draft['questions'][0]['question']
        assert question['translation'] == draft['questions'][0]['question_ru']
        assert question['options'] == [{'value': str(i), 'label': label}
                                       for i, label in enumerate(draft['questions'][0]['options'])]
        assert 'correct_index' not in question
        for answer, correct in [('0', False), ('1', True), ('1', True)]:
            trial = admin.post(path, headers=headers, json={**data, 'answer': answer})
            assert trial.status_code == 200 and trial.json['feedback']['correct'] is correct
        changed = deepcopy(draft)
        changed['questions'][0]['correct_index'] = 2
        result = admin.post(path, headers=headers, json={**data, 'content': json.dumps(changed), 'answer': '1'})
        assert result.status_code == 200 and result.json['feedback']['correct'] is False
        second = deepcopy(draft)
        second['questions'][1] = {**draft['questions'][0], 'instruction': 'Pick the tree again.'}
        result = admin.post(path, headers=headers, json={
            'content': json.dumps(second), 'question_number': 2, 'answer': '1',
        })
        assert result.status_code == 200 and result.json['question']['instruction'] == 'Pick the tree again.'
        assert result.json['question']['id'] == '1' and result.json['feedback']['correct'] is True
        del changed['questions'][0]['options']
        audio = {**draft, 'audio_url': '/static/audio/synthetic.mp3'}
        for invalid in [{'content': '{'}, {'content': json.dumps(changed)}, {'answer': 'unknown'},
                        {'question_number': 2}, {'content': json.dumps(audio)}]:
            result = admin.post(path, headers=headers, json={**data, **invalid})
            assert result.status_code == 422 and result.json['error']
    finally:
        event.remove(db.engine, 'before_cursor_execute', record)
    assert writes == []
    db.session.refresh(lesson)
    assert lesson.content == original and lesson.updated_at == updated
    assert _effects(lesson.id) == before


def test_choice_preview_requires_existing_admin_rights_and_csrf(
    receipt: dict[str, Any], app: Flask, admin_user: User, test_user: User,  # noqa: F811
) -> None:
    path = f'/curriculum/admin/lesson/{receipt["lesson"].id}/preview-choice'
    data = {'content': json.dumps(receipt['lesson'].content), 'question_number': 1}
    admin = app.test_client()
    sign_in(admin, app, admin_user)
    assert admin.post(path, json=data).status_code == 400

    for moderator in (False, True):
        test_user.is_moderator = moderator
        db.session.commit()
        client = app.test_client()
        headers = sign_in(client, app, test_user)
        response = client.post(path, headers=headers, json=data)
        assert response.status_code in (302, 403)
        assert 'Choose a greeting.' not in response.text

    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    guest = app.test_client()
    page = BeautifulSoup(guest.get('/login').data, 'html.parser')
    token = page.select_one('input[name=csrf_token]')['value']
    denied = guest.post(path, headers={'X-CSRFToken': token}, json=data)
    assert denied.status_code in (302, 403)
    assert 'Choose a greeting.' not in denied.text
