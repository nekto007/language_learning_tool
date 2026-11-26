"""Choice edits keep the published quiz usable by the learner."""

import json
from copy import deepcopy
from typing import Any

import pytest
from bs4 import BeautifulSoup
from flask import Flask
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from tests.api.test_course_receipt_expiry import receipt, sign_in


@pytest.mark.parametrize('options', [None, [], ['Oak'], ['Oak', '<b></b>']])
def test_choice_editor_rejects_unplayable_options_and_accepts_repair(
    receipt: dict[str, Any], app: Flask, admin_user: User, db_session: scoped_session,  # noqa: F811
    options: list[str] | None,
) -> None:
    lesson = receipt['lesson']
    lesson_id = lesson.id
    original = deepcopy(lesson.content)
    updated_at = lesson.updated_at
    edit_url = f'/curriculum/admin/lesson/{lesson_id}/edit'
    admin = app.test_client()
    sign_in(admin, app, admin_user)
    materials = admin.get('/admin/materials', query_string={'kind': 'lesson', 'level': 'A1', 'q': f'#{lesson_id}'})
    assert materials.status_code == 200
    link = BeautifulSoup(materials.data, 'html.parser').select_one(f'a[href^="{edit_url}"]')
    assert link is not None
    edit_url = str(link['href'])
    page = admin.get(edit_url)
    fields = BeautifulSoup(page.data, 'html.parser').select('#contentForm input[type=hidden]')
    form = {field['name']: field['value'] for field in fields}
    assert page.status_code == 200 and form['csrf_token'] and form['content_revision']

    candidate = deepcopy(original)
    row = {'type': 'multiple_choice', 'question': 'Which one is a tree?', 'correct_index': 0}
    if options is not None:
        row['options'] = options
    candidate['questions'][0] = row
    attempted_json = json.dumps(candidate)
    rejected = admin.post(edit_url, data={**form, 'content': attempted_json})
    assert rejected.status_code == 422
    assert 'Вопрос №1' in rejected.text and 'непустых вариантов' in rejected.text
    submitted = BeautifulSoup(rejected.data, 'html.parser').select_one('#contentForm textarea[name=content]')
    assert submitted is not None and submitted.text.removeprefix('\n') == attempted_json
    db_session.refresh(lesson)
    assert lesson.content == original and lesson.updated_at == updated_at
    audit = AdminAuditLog.query.filter_by(action='curriculum.lesson.update_content', target_id=lesson_id)
    assert audit.count() == 0

    row['options'] = ['Oak', 'Rose']
    saved = admin.post(edit_url, data={**form, 'content': json.dumps(candidate)})
    assert saved.status_code == 302 and '/admin/materials?' in saved.location
    db_session.refresh(lesson)
    assert lesson.content == candidate and audit.count() == 1

    learner, endpoint = receipt['client'], receipt['endpoint']
    headers = sign_in(learner, app, receipt['user'])
    screen = learner.get(f'/learn/{lesson_id}/')
    assert screen.status_code == 200 and endpoint in screen.text
    opened = learner.get(endpoint)
    assert opened.status_code == 200
    doc = opened.json['lesson']
    assert doc['questions'][0]['prompt'] == row['question']
    assert doc['questions'][0]['options'] == [{'label': 'Oak', 'value': '0'}, {'label': 'Rose', 'value': '1'}]
    assert doc['questions'][1]['input'] == 'text'
    for answer, expected in [('0', True), ('1', False)]:
        checked = learner.post(endpoint + '/check', headers=headers, json={
            'session_token': doc['session_token'], 'question_id': '0', 'answer': answer,
        })
        assert checked.status_code == 200 and checked.json['feedback']['correct'] is expected
