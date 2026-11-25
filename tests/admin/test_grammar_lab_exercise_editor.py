"""Structured edits through the admin and ordinary learner endpoints."""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute
from app.grammar_lab.answer_review import active_lab_override, apply_lab_patch, effective_content
from app.grammar_lab.models import GrammarAttempt
from tests.admin.test_materials import _page
from tests.api.test_grammar_lab_disputes import browser, dispute, exercise, submit


def _form(page: BeautifulSoup) -> tuple[str, dict[str, str]]:
    form = page.select_one('input[name=revision]').find_parent('form')
    fields = {}
    for field in form.select('input[name]:not([type=checkbox]), textarea[name], select[name]'):
        if field.name == 'textarea':
            value = field.get_text()
        elif field.name == 'select':
            value = (field.select_one('option[selected]') or field.select_one('option'))['value']
        else:
            value = field['value']
        fields[field['name']] = value
    return form['action'], fields


def test_real_reorder_from_materials_preserves_approved_order_and_history(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    raw = {
        'words': ['now', 'I', 'wait', 'in the', 'room', 'now'],
        'correct_answer': 'I wait now in the room now.',
        'hint': 'Original synthetic hint.',
        'metadata': {'synthetic': [0, {'leave': True}]},
        'acceptable_answers': ['Ignored by the reorder grader.'],
    }
    item = exercise('reorder', raw)
    reader, headers = browser(app, test_user)
    original_order = [0, 1, 2, 3, 4, 5]
    rejected = submit(reader, headers, item, original_order)
    assert not rejected['is_correct']
    assert dispute(reader, headers, item, rejected['dispute_token'], original_order).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    approved = 'Now I wait in the room now.'
    apply_lab_patch(item, {'alternatives': [approved]})
    case.status = 'applied'
    case.review = {'label': 'valid_variant', 'patch': {'alternatives': [approved]}}
    db_session.commit()
    attempt = GrammarAttempt.query.filter_by(exercise_id=item.id).one()
    review, evidence = deepcopy(case.review), deepcopy(case.evidence)
    previous_override = deepcopy(item.answer_review_override)

    g.pop('_login_user', None)
    index = _page(admin_client.get('/admin/materials', query_string={'kind': 'exercise', 'q': f'#{item.id}'}))
    href = index.select_one('.materials-result a[href*="/exercise"]')['href']
    path, inputs = _form(_page(admin_client.get(href)))
    draft = {**inputs, 'words': 'room\nnow\nin the\nwait\nI\nnow', 'hint': 'Revised synthetic hint.',
             'trial': approved, 'action': 'preview'}
    invalid = admin_client.post(path, data={**draft, 'correct_answer': 'Unreachable fictional key.'})
    assert invalid.status_code == 422
    result = _page(admin_client.post(path, data=draft))
    assert result.select_one('#decision-checked') is None
    assert approved in result.select_one('section[aria-labelledby=exercise-preview-title]').get_text()
    assert 'Ignored by the reorder grader.' not in result.text
    assert item.content == raw and item.answer_review_override == previous_override
    _, submission = _form(result)
    submission['action'] = 'apply'
    assert admin_client.post(path, data={**submission, 'hint': 'Modified after preview.'}).status_code == 409
    saved = admin_client.post(path, data=submission)
    assert saved.status_code == 303
    assert urlsplit(saved.location).path == '/admin/materials'
    assert parse_qs(urlsplit(saved.location).query) == {'q': [f'#{item.id}'], 'kind': ['exercise']}
    assert admin_client.post(path, data=submission).status_code == 409
    assert item.content['metadata'] == raw['metadata'] and item.content['acceptable_answers'] == raw['acceptable_answers']
    assert item.content['words'] == draft['words'].splitlines()
    assert item.answer_review_override['patch'] == previous_override['patch']
    assert item.answer_review_override['source_revision'] != previous_override['source_revision']
    assert case.review == review and case.evidence == evidence and case.status == 'applied'
    assert attempt.exercise_id == item.id and attempt.is_correct is False
    assert GrammarAttempt.query.filter_by(exercise_id=item.id).count() == 1

    g.pop('_login_user', None)
    assert submit(reader, headers, item, [4, 3, 1, 2, 0, 5])['is_correct']
    assert submit(reader, headers, item, [1, 4, 3, 2, 0, 5])['is_correct']
    assert not submit(reader, headers, item, [4, 3, 1, 2, 0, 1])['is_correct']


def test_semantic_correction_from_dispute_requires_explicit_review(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    accepted = 'The jars stay warm.'
    item = exercise('error_correction', {
        'sentence': 'The jars is warm.',
        'error_word': 'is',
        'correct_answer': 'are',
        'correct_sentence': ['The jars are warm.', 'The jars are still warm.'],
        'full_correct': 'The jars are warm today.',
        'alternative_answers': ['They are warm.'],
        'acceptable_answers': ['The glass jars are warm.'],
        'metadata': {'supported': False},
    })
    reader, headers = browser(app, test_user)
    prior = submit(reader, headers, item, accepted)
    assert dispute(reader, headers, item, prior['dispute_token'], accepted).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    apply_lab_patch(item, {'alternatives': [accepted]})
    case.status = 'applied'
    case.review = {'label': 'valid_variant', 'patch': {'alternatives': [accepted]}}
    db_session.commit()
    prior_state = deepcopy(item.content), deepcopy(item.answer_review_override), deepcopy(case.review)

    g.pop('_login_user', None)
    dispute_page = _page(admin_client.get(f'/admin/answer-disputes/{case.id}'))
    href = dispute_page.select_one(f'a[href="/admin/grammar-lab/exercises/{item.id}/edit"]')['href']
    path, fields = _form(_page(admin_client.get(href)))
    body = {**fields, 'sentence': 'These jars is warm.', 'correct_sentence': '',
            'full_correct': 'These jars are warm.', 'trial': accepted, 'action': 'preview'}
    preview = _page(admin_client.post(path, data=body))
    assert preview.select_one('#decision-checked')
    preview_text = preview.select_one('section[aria-labelledby=exercise-preview-title]').get_text()
    assert all(answer in preview_text for answer in ('The jars are still warm.', 'These jars are warm.', accepted))
    assert item.content == prior_state[0] and item.answer_review_override == prior_state[1]
    assert GrammarAttempt.query.filter_by(exercise_id=item.id).count() == 1
    _, payload = _form(preview)
    payload['action'] = 'apply'
    missing_review = admin_client.post(path, data=payload)
    assert missing_review.status_code == 422
    assert BeautifulSoup(missing_review.data, 'html.parser').select_one('#decision-checked')
    assert item.content == prior_state[0]
    assert admin_client.post(path, data={**payload, 'decision_checked': 'yes'}).status_code == 303
    assert admin_client.post(path, data={**payload, 'decision_checked': 'yes'}).status_code == 409
    assert item.content['sentence'] == body['sentence'] and 'correct_sentence' not in item.content
    assert item.content['metadata'] == {'supported': False}
    assert item.content['acceptable_answers'] == prior_state[0]['acceptable_answers']
    assert item.content['alternative_answers'] == prior_state[0]['alternative_answers']
    assert active_lab_override(item) is not None
    assert effective_content(item)['alternatives'] == [accepted]
    assert case.review == prior_state[2]
    assert AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id)).count() == 1

    g.pop('_login_user', None)
    for answer in ('are', 'These jars are warm.', accepted, 'They are warm.', 'The glass jars are warm.'):
        assert submit(reader, headers, item, answer)['is_correct']
    assert not submit(reader, headers, item, 'The jars are still warm.')['is_correct']
    assert not submit(reader, headers, item, 'is')['is_correct']


def test_guided_correction_still_goes_to_topic_publisher(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    item = exercise('error_correction', {'question': 'Fictional exercise.', 'correct_answer': 'Synthetic.'})
    item.topic.content = {'guided_catalog_digest': 'synthetic'}
    db_session.commit()
    path = f'/admin/grammar-lab/exercises/{item.id}/edit'
    for response in (admin_client.get(path), admin_client.post(path, data={'action': 'preview'})):
        assert response.status_code == 303
        assert response.location.endswith(f'/admin/grammar-lab/guided/{item.topic_id}')
    assert item.content['question'] == 'Fictional exercise.'


def test_new_approval_invalidates_an_older_editor_preview(admin_client: FlaskClient, db_session: scoped_session) -> None:
    original = {'question': 'Synthetic correction.', 'correct_answer': 'Synthetic answer.', 'hint': 'Original hint.'}
    item = exercise('error_correction', original)
    apply_lab_patch(item, {'alternatives': ['Earlier answer.']})
    db_session.commit()
    path, fields = _form(_page(admin_client.get(f'/admin/grammar-lab/exercises/{item.id}/edit')))
    _, preview = _form(_page(admin_client.post(path, data={**fields, 'hint': 'Prepared hint.', 'action': 'preview'})))
    apply_lab_patch(item, {'alternatives': ['Earlier answer.', 'Newly approved answer.']})
    db_session.commit()
    assert admin_client.post(path, data={**preview, 'action': 'apply'}).status_code == 409
    assert item.content == original
    assert effective_content(item)['alternatives'] == ['Earlier answer.', 'Newly approved answer.']
    assert AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id)).count() == 0


def test_trial_from_dispute_checks_current_answer_without_saving(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    raw = {'sentence': 'The crates is dry.', 'correct_answer': 'are', 'hint': 'Synthetic hint.'}
    approved = 'The crates stay dry.'
    item = exercise('error_correction', raw)
    reader, headers = browser(app, test_user)
    rejected = submit(reader, headers, item, approved)
    assert not rejected['is_correct']
    assert dispute(reader, headers, item, rejected['dispute_token'], approved).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    patch = {'alternatives': [approved]}
    apply_lab_patch(item, patch)
    case.status = 'applied'
    case.review = {'label': 'valid_variant', 'patch': patch}
    item.difficulty = item.order = None
    db_session.commit()
    attempt = GrammarAttempt.query.filter_by(exercise_id=item.id).one()
    review, decision = deepcopy(case.review), deepcopy(item.answer_review_override)
    audits = AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id))

    g.pop('_login_user', None)
    detail = _page(admin_client.get(f'/admin/answer-disputes/{case.id}'))
    href = detail.select_one(f'a[href="/admin/grammar-lab/exercises/{item.id}/edit"]')['href']
    form = _page(admin_client.get(href))
    path, fields = _form(form)
    assert fields['difficulty'] == fields['order'] == ''
    assert form.select_one('label[for=question]').get_text(strip=True) == 'Запасная фраза с ошибкой'  # noqa: RUF001 -- Russian form label.
    for answer, result in ((approved, 'верно'), ('is', 'неверно')):
        payload = {**fields, 'action': 'preview', 'trial': answer}
        checked = _page(admin_client.post(path, data=payload))
        assert f'{answer} · {result}' in checked.select_one('#exercise-trial-title').parent.get_text()
        assert checked.select_one('button[value=apply], input[name=preview_token]') is None
        assert admin_client.post(path, data={**payload, 'action': 'apply'}).status_code == 409

    assert audits.count() == 0
    assert GrammarAttempt.query.filter_by(exercise_id=item.id).one().id == attempt.id
    assert case.review == review and item.answer_review_override == decision
    assert item.content == raw and item.difficulty is None and item.order is None

    draft = _page(admin_client.post(path, data={**fields, 'action': 'preview', 'hint': 'Revised synthetic hint.'}))
    _, submission = _form(draft)
    assert submission['preview_token']
    assert admin_client.post(path, data={**submission, 'action': 'apply'}).status_code == 303
    assert item.content == {**raw, 'hint': 'Revised synthetic hint.'}
    assert item.difficulty is None and item.order is None
    assert GrammarAttempt.query.filter_by(exercise_id=item.id).one().id == attempt.id
    assert effective_content(item)['alternatives'] == [approved] and case.review == review
    assert audits.count() == 1


@pytest.mark.parametrize('target_type', ['error_correction', 'fill_blank'])
def test_stale_structured_post_cannot_edit_exercise_after_type_change(
    admin_client: FlaskClient, db_session: scoped_session, target_type: str,
) -> None:
    item = exercise('reorder', {'words': ['Owls', 'rest'], 'correct_answer': 'Owls rest.'})
    form = _page(admin_client.get(f'/admin/grammar-lab/exercises/{item.id}/edit'))
    path, fields = _form(form)
    assert form.select_one('label[for=words]').get_text(strip=True) == 'Слова и выражения'
    assert 'В практике плитки перемешиваются.' in form.select_one('#tiles-help').get_text()  # noqa: RUF001 -- Russian form help.
    draft = _page(admin_client.post(path, data={**fields, 'hint': 'Prepared hint.', 'action': 'preview'}))
    _, submission = _form(draft)
    fresh_content = {'question': 'Synthetic prompt.', 'correct_answer': 'rest', 'metadata': ['keep']}
    item.exercise_type, item.content = target_type, fresh_content
    db_session.commit()
    for action in ('preview', 'apply'):
        assert admin_client.post(path, data={**submission, 'action': action}).status_code == 409
    # A structured form opened before the editor_type marker still carries the stale revision.
    submission.pop('editor_type')
    assert admin_client.post(path, data={**submission, 'action': 'apply'}).status_code == 409
    assert item.exercise_type == target_type and item.content == fresh_content
    assert AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id)).count() == 0

    if target_type == 'fill_blank':
        legacy = _page(admin_client.get(path))
        assert legacy.select_one('textarea[name=content]') and legacy.select_one('input[name=revision]') is None
        response = admin_client.post(path, data={
            'exercise_type': target_type, 'order': '1', 'difficulty': '1',
            'content': '{"question":"Synthetic legacy edit.","correct_answer":"rest"}',
        })
        assert response.status_code == 302
        assert item.content['question'] == 'Synthetic legacy edit.'
