"""Structured edits through the admin and ordinary learner endpoints."""

from copy import deepcopy
from typing import Any
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


@pytest.mark.parametrize('kind', ['error_correction', 'fill_blank', 'translation', 'multiple_choice'])
def test_guided_exercise_still_goes_to_topic_publisher(
    admin_client: FlaskClient, db_session: scoped_session, kind: str,
) -> None:
    row = {'question': 'Fictional exercise.', 'correct_answer': 'Synthetic.'}
    if kind == 'multiple_choice':
        row['options'] = ['Synthetic.', 'Other.']
    item = exercise(kind, row)
    item.topic.content = {'guided_catalog_digest': 'synthetic'}
    db_session.commit()
    path = f'/admin/grammar-lab/exercises/{item.id}/edit'
    for response in (admin_client.get(path), admin_client.post(path, data={'action': 'preview'})):
        assert response.status_code == 303
        assert response.location.endswith(f'/admin/grammar-lab/guided/{item.topic_id}')
    assert item.content['question'] == 'Fictional exercise.'


@pytest.mark.parametrize(('key', 'stored', 'value_after', 'position'), [
    ('correct_answer', '1', '1', 2),
    ('correct_answer', 0, 1, 1),
    ('correct_answer', '0', '1', 1),
    ('correct_index', 0, 1, 1),
    ('correct_index', '0', '1', 1),
])
def test_choice_round_trip_preserves_key_format_and_option_identity(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
    key: str, stored: Any, value_after: Any, position: int,
) -> None:
    raw = {'question': 'Synthetic question?', 'options': ['Amber', '1', 'Violet'], key: stored}
    if stored == '0':
        raw['options'][1] = 'Teal'
    item = exercise('multiple_choice', {**raw, 'correct_answer': stored})
    item.content = raw
    item.order = item.difficulty = None
    db_session.commit()
    path = f'/admin/grammar-lab/exercises/{item.id}/edit'
    _, fields = _form(_page(admin_client.get(path)))
    caption = raw['options'][1 if stored == '1' else 0]
    current = admin_client.post(path, data={**fields, 'action': 'preview', 'trial': '2' if stored == '1' else '1'})
    assert current.status_code == 200
    current_page = _page(current)
    assert caption + ' · верно' in current_page.select_one('[aria-labelledby=exercise-trial-title]').get_text()
    assert not current_page.select_one('[name=preview_token], [value=apply]')
    assert not AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id)).count()
    options = [raw['options'][2], raw['options'][0], raw['options'][1]]
    preview = admin_client.post(path, data={**fields, 'options': '\n'.join(options), 'action': 'preview',
                                            'trial': str(position + 1)})
    assert preview.status_code == 200
    _, draft = _form(_page(preview))
    assert admin_client.post(path, data={**draft, 'action': 'apply'}).status_code == 303
    assert item.content[key] == value_after and type(item.content[key]) is type(stored)
    assert item.content['options'] == options and item.order is None and item.difficulty is None
    g.pop('_login_user', None)
    reader, headers = browser(app, test_user)
    assert submit(reader, headers, item, str(position))['is_correct']
    assert not submit(reader, headers, item, '0')['is_correct']


def test_choice_decision_from_dispute_is_rebased_and_stale_tab_keeps_draft(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    raw = {'source': 'json_import', 'question': 'Original question?', 'options': ['Amber', '1', 'Violet'],
           'correct_answer': 'Amber', 'alternatives': ['Retained A.'], 'alternative_answers': ['Retained B.'],
           'acceptable_answers': ['Retained C.'], 'meta': {'keep': True}}
    item = exercise('multiple_choice', raw)
    reader, headers = browser(app, test_user)
    rejected = submit(reader, headers, item, '1')
    assert dispute(reader, headers, item, rejected['dispute_token'], '1').status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    case.status = 'applied'
    case.review = {'label': 'wrong_key', 'patch': {'correct_answer': '1'}}
    apply_lab_patch(item, {'correct_answer': '1', 'alternatives': ['Approved metadata.']})
    db_session.commit()
    prior = deepcopy(case.review), deepcopy(case.evidence), deepcopy(item.answer_review_override)

    g.pop('_login_user', None)
    dispute_page = _page(admin_client.get(f'/admin/answer-disputes/{case.id}'))
    href = dispute_page.select_one(f'a[href="/admin/grammar-lab/exercises/{item.id}/edit"]')['href']
    path, fields = _form(_page(admin_client.get(href)))
    tab, tab_headers = browser(app, admin_user)
    _, tab_fields = _form(_page(tab.get(path)))
    g.pop('_login_user', None)
    assert admin_client.post(path, data={'content': '{}', 'exercise_type': 'multiple_choice'}).status_code == 409
    assert admin_client.post(path, data={**fields, 'options': 'Amber\nAmber', 'action': 'preview'}).status_code == 422
    draft = {**fields, 'question': 'Updated question?', 'instruction': 'Choose one.', 'action': 'preview'}
    preview = _page(admin_client.post(path, data=draft))
    assert preview.select_one('#decision-checked')
    for side in preview.select('[aria-labelledby=exercise-preview-title] h4 + ul'):
        assert [entry.get_text() for entry in side.select('li')] == ['1']
    _, ready = _form(preview)
    g.pop('_login_user', None)
    old_preview = _page(tab.post(path, headers=tab_headers, data={
        **tab_fields, 'question': 'Other tab draft?', 'choice_key': '3', 'trial': '3', 'action': 'preview',
    }))
    sides = old_preview.select('[aria-labelledby=exercise-preview-title] .col-md-6')
    assert '» · неверно' in sides[0].get_text()
    assert '» · верно' in sides[1].get_text()
    _, old_ready = _form(old_preview)
    g.pop('_login_user', None)
    assert item.content == raw and item.answer_review_override == prior[2]
    assert GrammarAttempt.query.filter_by(exercise_id=item.id).count() == 1
    assert not AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id)).count()
    assert admin_client.post(path, data={**ready, 'action': 'apply'}).status_code == 422
    assert admin_client.post(path, data={**ready, 'action': 'apply', 'decision_checked': 'yes'}).status_code == 303
    assert admin_client.post(path, data={**ready, 'action': 'apply', 'decision_checked': 'yes'}).status_code == 409
    g.pop('_login_user', None)
    conflict = tab.post(path, headers=tab_headers, data={**old_ready, 'action': 'apply', 'decision_checked': 'yes'})
    assert conflict.status_code == 409
    _, restored = _form(BeautifulSoup(conflict.data, 'html.parser'))
    assert restored['question'] == 'Other tab draft?' and restored['choice_key'] == restored['trial'] == '3'
    assert 'preview_token' not in restored and restored['revision'] != old_ready['revision']
    rebased = tab.post(path, headers=tab_headers, data={**restored, 'action': 'preview'})
    assert rebased.status_code == 200 and _page(rebased).select_one('[name=preview_token]')
    assert item.content == {**raw, 'question': 'Updated question?', 'instruction': 'Choose one.'}
    assert active_lab_override(item)['patch'] == prior[2]['patch']
    assert active_lab_override(item)['source_revision'] != prior[2]['source_revision']
    assert (case.review, case.evidence) == prior[:2]
    assert AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id)).count() == 1

    g.pop('_login_user', None)
    assert submit(reader, headers, item, '1')['is_correct']
    assert not submit(reader, headers, item, '0')['is_correct']
    g.pop('_login_user', None)
    _, reviewed = _form(_page(rebased))
    assert tab.post(path, headers=tab_headers, data={**reviewed, 'action': 'apply',
                                                   'decision_checked': 'yes'}).status_code == 303
    assert item.content['correct_answer'] == raw['correct_answer']
    assert active_lab_override(item)['patch'] == {**prior[2]['patch'], 'correct_answer': 'Violet'}
    assert (case.review, case.evidence) == prior[:2]
    g.pop('_login_user', None)
    assert submit(reader, headers, item, '2')['is_correct']
    assert not submit(reader, headers, item, '1')['is_correct']


def test_unconverted_grammar_exercise_still_saves_with_json(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    item = exercise('transformation', {'question': 'Synthetic original.', 'correct_answer': 'Sample.'})
    path = f'/admin/grammar-lab/exercises/{item.id}/edit'
    page = _page(admin_client.get(path))
    assert page.select_one('textarea[name=content]')
    response = admin_client.post(path, data={
        'content': '{"question":"Synthetic edit.","correct_answer":"Sample."}',
        'difficulty': '2', 'order': '4', 'exercise_type': 'transformation',
    })
    assert response.status_code == 302
    assert item.content['question'] == 'Synthetic edit.' and item.order == 4


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


@pytest.mark.parametrize('target_type', ['error_correction', 'translation', 'fill_blank', 'transformation'])
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

    if target_type == 'transformation':
        legacy = _page(admin_client.get(path))
        assert legacy.select_one('textarea[name=content]') and legacy.select_one('input[name=revision]') is None
        response = admin_client.post(path, data={
            'exercise_type': target_type, 'order': '1', 'difficulty': '1',
            'content': '{"question":"Synthetic legacy edit.","correct_answer":"rest"}',
        })
        assert response.status_code == 302
        assert item.content['question'] == 'Synthetic legacy edit.'


def test_translation_from_materials_keeps_legacy_phrase_and_supports_both_directions(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    original_phrase = 'Шарф лежит на скамейке.'
    original = {
        'question': original_phrase, 'correct_answer': 'The scarf is on the bench.',
        'source': 'json_import', 'key_grammar': 'Synthetic grammar note.',
        'metadata': {'keep': [0, False]},
    }
    item = exercise('translation', original)
    item.topic.slug = 'synthetic-translation-topic'
    db_session.commit()
    item_id, topic_id = item.id, item.topic_id
    reader, headers = browser(app, test_user)
    approved = 'The scarf lies on the bench.'
    wrong = submit(reader, headers, item, approved)
    assert not wrong['is_correct']
    assert dispute(reader, headers, item, wrong['dispute_token'], approved).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item_id).one()
    patch = {'alternatives': [approved]}
    apply_lab_patch(item, patch)
    case.status = 'applied'
    case.review = {'label': 'valid_variant', 'patch': patch}
    db_session.commit()
    g.pop('_login_user', None)
    index = _page(admin_client.get('/admin/materials', query_string={'kind': 'exercise', 'q': f'#{item.id}'}))
    href = index.select_one('.materials-result a[href*="/exercise"]')['href']
    form = _page(admin_client.get(href))
    assert 'synthetic-translation-topic' in form.get_text() and 'Импорт JSON' in form.get_text()
    assert 'Повторный импорт' in form.get_text()
    path, fields = _form(form)
    assert fields['direction'] == 'ru-en' and fields['sentence'] == ''

    before = {**fields, 'action': 'preview', 'instruction': 'Переведите фразу.', 'source': 'module_import', 'topic_id': '0'}
    preview = _page(admin_client.post(path, data=before))
    sides = preview.select_one('#exercise-preview-title').parent.select('.row > div')
    assert [side.select_one('p[lang=ru]').get_text() for side in sides] == [original_phrase] * 2
    assert all(approved in side.get_text() for side in sides)
    _, payload = _form(preview)
    saved = admin_client.post(path, data={**payload, 'action': 'apply', 'decision_checked': 'yes'})
    assert saved.status_code == 303
    assert parse_qs(urlsplit(saved.location).query) == {'q': [f'#{item.id}'], 'kind': ['exercise']}
    assert item.content == {**original, 'instruction': 'Переведите фразу.'}
    assert (item.id, item.topic_id) == (item_id, topic_id)
    assert effective_content(item)['alternatives'] == [approved] and case.status == 'applied'
    assert GrammarAttempt.query.filter_by(exercise_id=item_id).count() == 1

    g.pop('_login_user', None)
    assert submit(reader, headers, item, original['correct_answer'])['is_correct']
    assert submit(reader, headers, item, approved)['is_correct']
    assert not submit(reader, headers, item, original_phrase)['is_correct']

    g.pop('_login_user', None)
    _, fields = _form(_page(admin_client.get(path)))
    alias = 'Шарф на скамейке.'
    draft = {**fields, 'direction': 'en-ru', 'question': 'Что означает эта фраза?', 'instruction': '',
             'sentence': 'The scarf is on the bench.', 'correct_answer': original_phrase,
             'alternatives': alias, 'action': 'preview'}
    preview = _page(admin_client.post(path, data=draft))
    panel = preview.select_one('#exercise-preview-title').parent
    assert panel.select_one('p[lang=en]').get_text() == draft['sentence']
    assert panel.select_one('li[lang=ru]').get_text() == original_phrase
    _, payload = _form(preview)
    assert admin_client.post(path, data={**payload, 'action': 'apply'}).status_code == 422
    assert admin_client.post(path, data={**payload, 'action': 'apply', 'decision_checked': 'yes'}).status_code == 303
    assert item.content['target_lang'] == 'ru' and item.content['source_lang'] == 'en'
    assert item.content['metadata'] == original['metadata'] and item.content['key_grammar'] == original['key_grammar']
    assert item.content['source'] == original['source'] and item.id == item_id
    g.pop('_login_user', None)
    for answer, correct in ((original_phrase, True), (alias, True), (draft['sentence'], False), ('Шарф', False),
                            (approved, False)):
        assert submit(reader, headers, item, answer)['is_correct'] is correct


def test_blank_from_dispute_keeps_decision_and_uses_existing_grading_contract(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    prompt = 'Is the lamp on? — Yes, it ___.'
    raw = {'question': prompt, 'correct_answer': 'is', 'source': 'module_import',
           'alternative_answers': ['It is on.'], 'metadata': {'untouched': True}}
    item = exercise('fill_blank', raw)
    reader, headers = browser(app, test_user)
    approved = 'Yes, the lamp is on.'
    rejected = submit(reader, headers, item, approved)
    assert not rejected['is_correct']
    assert dispute(reader, headers, item, rejected['dispute_token'], approved).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    patch = {'acceptable_answers': [approved]}
    apply_lab_patch(item, patch)
    case.status = 'applied'
    case.review = {'label': 'valid_variant', 'patch': patch}
    db_session.commit()
    attempt = GrammarAttempt.query.filter_by(exercise_id=item.id).one()
    audit = AdminAuditLog.query.filter_by(action='grammar_exercise.update', target_id=str(item.id))
    item_id, topic_id, evidence = item.id, item.topic_id, deepcopy(case.evidence)

    g.pop('_login_user', None)
    page = _page(admin_client.get(f'/admin/answer-disputes/{case.id}'))
    href = page.select_one(f'a[href="/admin/grammar-lab/exercises/{item_id}/edit"]')['href']
    form = _page(admin_client.get(href))
    path, fields = _form(form)
    assert 'Импорт из модуля' in form.get_text()
    assert fields['acceptable_answers'] == approved and fields['alternative_answers'] == 'It is on.'
    for answer, expected in ((approved, 'верно'), ('Yes, it is.', 'верно'), ("Yes, it's.", 'неверно'),
                             ('No, it is.', 'неверно'), ('Yes, she is.', 'неверно'), ('Yes, it is now.', 'неверно')):
        checked = _page(admin_client.post(path, data={**fields, 'action': 'preview', 'trial': answer}))
        assert f'{answer} · {expected}' in checked.select_one('#exercise-trial-title').parent.get_text()
        assert checked.select_one('button[value=apply], input[name=preview_token]') is None
    assert item.content == raw and audit.count() == 0
    assert GrammarAttempt.query.filter_by(exercise_id=item_id).one().id == attempt.id
    preview = _page(admin_client.post(path, data={**fields, 'action': 'preview', 'instruction': 'Впиши одно слово.'}))
    assert preview.select_one('#decision-checked')
    text = preview.select_one('#exercise-preview-title').parent.get_text()
    assert prompt in text and approved in text and 'Для краткого ответа' in text
    _, payload = _form(preview)
    payload['action'] = 'apply'
    assert admin_client.post(path, data=payload).status_code == 422
    assert admin_client.post(path, data={**payload, 'decision_checked': 'yes'}).status_code == 303
    assert admin_client.post(path, data={**payload, 'decision_checked': 'yes'}).status_code == 409
    assert item.content == {**raw, 'instruction': 'Впиши одно слово.'}
    assert effective_content(item)['acceptable_answers'] == [approved]
    assert case.evidence == evidence and case.status == 'applied'
    assert (item.id, item.topic_id) == (item_id, topic_id) and audit.count() == 1
    assert GrammarAttempt.query.filter_by(exercise_id=item_id).one().id == attempt.id
    g.pop('_login_user', None)
    for answer, correct in (('is', True), ('Yes, it is.', True), (approved, True), ('No, it is.', False)):
        assert submit(reader, headers, item, answer)['is_correct'] is correct


@pytest.mark.parametrize('legacy', [{'options': ['are', 'is']}, {'sentence': 'The window ___ open.'}])
def test_blank_form_does_not_expand_legacy_grading_or_overwrite_hidden_fields(
    admin_client: FlaskClient, db_session: scoped_session, legacy: dict,
) -> None:
    raw = {'question': 'The gates ___ shut.', 'correct_answer': ['are'], **legacy}
    item = exercise('fill_blank', raw)
    path, fields = _form(_page(admin_client.get(f'/admin/grammar-lab/exercises/{item.id}/edit')))
    data = {**fields, 'hint': 'Synthetic hint.', 'trial': 'The gates are shut.', 'action': 'preview'}
    preview = _page(admin_client.post(path, data=data))
    panel = preview.select_one('#exercise-preview-title').parent
    assert panel.get_text().count('неверно') == 2
    assert 'Можно также написать' not in panel.get_text()
    _, payload = _form(preview)
    assert admin_client.post(path, data={**payload, 'action': 'apply'}).status_code == 303
    db_session.refresh(item)
    assert item.content == {**raw, 'hint': 'Synthetic hint.'}


def test_blank_form_preserves_two_underscore_gap_and_rejects_its_removal(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    raw = {'question': 'The vents __ open.', 'correct_answer': 'are'}
    item = exercise('fill_blank', raw)
    reader, headers = browser(app, test_user)
    assert submit(reader, headers, item, 'The vents are open.')['is_correct']

    g.pop('_login_user', None)
    form = _page(admin_client.get(f'/admin/grammar-lab/exercises/{item.id}/edit'))
    assert 'двумя или более подчёркиваниями' in form.select_one('#exercise-question-help').get_text()
    path, fields = _form(form)
    draft = {**fields, 'hint': 'Synthetic hint.', 'trial': 'The vents are open.', 'action': 'preview'}
    for question in ('The vents _ open.', 'The vents open.'):
        rejected = admin_client.post(path, data={**draft, 'question': question})
        assert rejected.status_code == 422
        assert BeautifulSoup(rejected.data, 'html.parser').select_one('input[name=preview_token]') is None
    assert item.content == raw

    preview = _page(admin_client.post(path, data=draft))
    panel = preview.select_one('#exercise-preview-title').parent
    assert panel.get_text().count('The vents are open.» · верно') == 2
    _, payload = _form(preview)
    assert admin_client.post(path, data={**payload, 'action': 'apply'}).status_code == 303
    db_session.refresh(item)
    assert item.content == {**raw, 'hint': 'Synthetic hint.'}


@pytest.mark.parametrize('kind', ['translation', 'fill_blank'])
def test_written_form_groups_existing_aliases_and_preserves_their_keys(
    admin_client: FlaskClient, db_session: scoped_session, kind: str,
) -> None:
    question = 'Где лежат ключи?' if kind == 'translation' else 'The spare keys __ in the drawer.'
    key = 'Where are the keys?' if kind == 'translation' else 'are'
    raw = {'question': question, 'correct_answer': key, 'acceptable_answers': [], 'metadata': ['keep']}
    item = exercise(kind, raw)
    href = f'/admin/grammar-lab/exercises/{item.id}/edit'
    form = _page(admin_client.get(href))
    assert form.select_one('label[for=alternatives]').get_text() == 'Допустимые варианты'
    assert form.select_one('#saved-aliases, #alternative_answers, #acceptable_answers') is None
    saved = {
        'alternative_answers': ['The keys are in the drawer.', 'The keys are put away.'],
        'acceptable_answers': ['The keys are stored.'],
    }
    item.content = {**raw, 'alternative_answers': saved['alternative_answers']}
    apply_lab_patch(item, {'acceptable_answers': saved['acceptable_answers']})
    db_session.commit()
    form = _page(admin_client.get(href))
    group = form.select_one('#saved-aliases')
    assert group.select_one('summary').get_text(strip=True) == 'Другие сохранённые варианты (3)'
    assert [field['name'] for field in group.select('textarea')] == list(saved)
    assert form.select_one('#alternatives').find_parent('details') is None

    path, fields = _form(form)
    draft = _page(admin_client.post(path, data={
        **fields, 'action': 'preview', 'hint': 'Synthetic hint.', 'trial': saved['acceptable_answers'][0],
    }))
    panel = draft.select_one('#exercise-preview-title').parent
    assert panel.get_text().count('The keys are stored.» · верно') == 2
    assert draft.select_one('#decision-checked') is None
    _, payload = _form(draft)
    assert admin_client.post(path, data={**payload, 'action': 'apply'}).status_code == 303
    assert item.content == {**raw, 'alternative_answers': saved['alternative_answers'], 'hint': 'Synthetic hint.'}
    assert all(effective_content(item)[field] == answers for field, answers in saved.items())

    _, fields = _form(_page(admin_client.get(path)))
    changed = _page(admin_client.post(path, data={**fields, 'action': 'preview', 'acceptable_answers': ''}))
    assert changed.select_one('#saved-aliases #acceptable_answers').get_text() == ''
    assert changed.select_one('#decision-checked')
    _, payload = _form(changed)
    assert admin_client.post(path, data={**payload, 'action': 'apply'}).status_code == 422
    assert admin_client.post(path, data={**payload, 'action': 'apply', 'decision_checked': 'yes'}).status_code == 303
    assert item.content['acceptable_answers'] == [] and effective_content(item)['acceptable_answers'] == []
    assert effective_content(item)['alternative_answers'] == saved['alternative_answers']
