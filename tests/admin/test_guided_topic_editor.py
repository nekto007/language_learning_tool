"""Shared-database checks for publishing one synthetic guided topic."""
# ruff: noqa: RUF001 -- assertions inspect Russian form copy.
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
import pytest
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse

from app.admin.audit import AdminAuditLog
from app.admin.utils import import_helpers
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.answer_review_editor import editor_decide, editor_version
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.grammar_lab.content_catalog import compile_topic, content_digest, load_catalog
from app.grammar_lab.content_install import install_catalog
from app.grammar_lab.guided_authoring import recover_document
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic
from app.grammar_lab.answer_review import lab_revision
from app.utils.db import db
from tests.api.test_grammar_lab_disputes import browser, dispute, submit

INDEX = '/admin/grammar-lab/guided'
OLD = 'I ride the bus to work.'
APPROVED = 'I walk to work.'


def sample_document() -> dict:
    return {'topic_slug': 'a1-6', 'version': 1, 'title': 'Synthetic travel', 'goal': 'Practise a short phrase.',
            'steps': [
                {'id': 'walk', 'title': 'Go to work', 'body': 'First synthetic rule.',
                 'exercises': [{'type': 'translation', 'question': 'Translate the synthetic travel example.',
                                'instruction': 'Write the full phrase in English.', 'correct_answer': OLD,
                                'explanation': 'Synthetic answer for the regression.'}]},
                {'id': 'wait', 'title': 'Wait outside', 'body': 'Second synthetic rule.',
                 'exercises': [{'type': 'translation', 'question': 'Translate the synthetic waiting example.',
                                'instruction': 'Write the full phrase in English.', 'correct_answer': 'I wait outside.',
                                'explanation': 'Another synthetic answer.'}]},
            ], 'reference_sections': [{'title': 'Reference', 'body': 'Synthetic reference.'}]}


@pytest.fixture
def installed_topic(app: Flask, db_session: scoped_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
                    ) -> tuple[GrammarTopic, Lessons, Lessons, dict]:
    monkeypatch.setattr(import_helpers, 'IMPORT_TEMP_DIR', str(tmp_path))
    monkeypatch.setattr(app, 'instance_path', str(tmp_path))
    topic = GrammarTopic(slug='a1-6', title='Seed', title_ru='Seed', level='A1', content={})
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Beginner', order=1)
        db.session.add(level)
    db.session.add(topic)
    db.session.flush()
    module = Module(level_id=level.id, number=996, title='Synthetic module')
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(module_id=module.id, number=1, title='Guided seed', type='grammar', grammar_topic_id=topic.id,
                     content={'external_key': 'synthetic-guided'})
    final = Lessons(module_id=module.id, number=2, title='Reference to guided topic', type='final_test',
                    grammar_topic_id=topic.id, content={'description': 'Synthetic final'})
    db.session.add_all([lesson, final])
    db.session.commit()
    doc = sample_document()
    install_catalog(documents={topic.slug: doc}, apply=True)
    return topic, lesson, final, doc


def _page(response: TestResponse, status: int = 200) -> BeautifulSoup:
    assert response.status_code == status, response.text[:400]
    return BeautifulSoup(response.data, 'html.parser')


def _field(page: BeautifulSoup, name: str) -> str:
    return str(page.select_one(f'input[name="{name}"]')['value'])


def _fields(topic: GrammarTopic, document: dict, **extra: str) -> dict:
    return {'mode': 'fields', 'base_digest': topic.content['guided_catalog_digest'],
            'title': document['title'], 'goal': document['goal'], 'body': [step['body'] for step in document['steps']],
            **extra}


def _source(topic: GrammarTopic, document: dict, **extra: str) -> dict:
    return {'mode': 'source', 'base_digest': topic.content['guided_catalog_digest'],
            'document': json.dumps(document), **extra}


def _approve(app: Flask, admin: User, learner: User, exercise: GrammarExercise) -> AnswerDispute:
    client, headers = browser(app, learner)
    rejected = submit(client, headers, exercise, APPROVED)
    assert rejected['is_correct'] is False
    assert dispute(client, headers, exercise, rejected['dispute_token'], APPROVED).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=exercise.id).one()
    editor_decide(case.id, admin.id, editor_version(case), 'replace', APPROVED)
    g.pop('_login_user', None)
    return case


def test_recovery_matches_each_reviewed_document_without_fallback_file() -> None:
    for slug, authored in load_catalog().items():
        compiled = compile_topic(authored)
        topic = SimpleNamespace(slug=slug, content={
            **compiled, 'guided_display_title': authored['title'], 'guided_catalog_digest': content_digest(authored),
        })
        assert recover_document(topic) == authored


def test_cli_dry_run_keeps_database_unchanged(app: Flask, tmp_path: Path, installed_topic: tuple) -> None:
    topic, lesson, _, authored = installed_topic
    path = tmp_path / 'topics' / f'{topic.slug}.json'
    path.parent.mkdir()
    snapshot, version = deepcopy(topic.content), lesson.content_version
    authored['goal'] = 'Different goal for the CLI dry run.'
    path.write_text(json.dumps(authored))
    result = app.test_cli_runner().invoke(args=[
        'grammar-guided-install', '--topic', topic.slug, '--content-dir', str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    assert '"applied": false' in result.output
    assert topic.content == snapshot and lesson.content_version == version


def test_fields_round_trip_publish_preserves_same_step_approval_and_learner_serialization(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User, installed_topic: tuple,
) -> None:
    topic, lesson, final, doc = installed_topic
    topic.content = {key: value for key, value in topic.content.items() if key != 'guided_author_document'}
    progress = LessonProgress(user_id=test_user.id, lesson_id=lesson.id, status='completed', score=100)
    db.session.add(progress)
    db.session.commit()
    ids = topic.content['guided_exercise_ids'][:]
    first = db.session.get(GrammarExercise, ids[0])
    case = _approve(app, admin_user, test_user, first)
    prior_attempt_ids = [row.id for row in GrammarAttempt.query.filter_by(exercise_id=first.id).all()]
    version, prior_review = lesson.content_version, deepcopy(case.review)

    search = 'q=synthetic&kind=exercise&level=A1&page=2'
    redirect_to_editor = admin_client.get(f'/admin/grammar-lab/topics/{topic.id}/edit',
                                          query_string={'materials_query': search})
    assert redirect_to_editor.status_code == 303 and 'materials_query=' in redirect_to_editor.location
    path = f'{INDEX}/{topic.id}'
    page = _page(admin_client.get(redirect_to_editor.location))
    assert page.select_one('#guided-title')['value'] == doc['title']
    assert page.find('a', string='К результатам поиска')['href'] == '/admin/materials?' + search

    doc['title'] = 'Changed synthetic title'
    doc['goal'] = 'Changed synthetic goal'
    doc['steps'][0]['body'] = 'Changed theory in the exercise step. ' * 24
    doc['steps'][1]['body'] = 'Changed neighbouring theory.'
    invalid = _page(admin_client.post(path + '/preview', data=_fields(topic, doc, goal=' ')), 422)
    assert invalid.select_one('#guided-title')['value'] == doc['title']
    assert invalid.select_one('#guided-body-1').text == doc['steps'][0]['body']

    preview_url = page.select_one('.guided-main-form')['action']
    preview = _page(admin_client.post(preview_url, data=_fields(topic, doc)))
    superseded = _field(preview, 'preview_id')
    assert 'First synthetic rule.' in preview.text and doc['steps'][0]['body'] in preview.text
    assert 'Решения, которые перестанут применяться' not in preview.text
    assert topic.title_ru == 'Synthetic travel' and lesson.content_version == version
    resume = _page(admin_client.get(preview.find('a', string='Продолжить редактирование')['href']))
    assert resume.select_one('#guided-body-1').text == doc['steps'][0]['body']
    doc['steps'][0]['body'] += ' Final correction.'
    preview = _page(admin_client.post(resume.select_one('.guided-main-form')['action'],
                                      data=_fields(topic, doc, draft=_field(resume, 'draft'))))
    token = _field(preview, 'preview_id')
    assert admin_client.post(path + '/publish', data={'preview_id': superseded}).status_code == 409
    published = admin_client.post(preview.select_one('form')['action'], data={'preview_id': token})
    assert published.status_code == 303 and 'materials_query=' in published.location
    assert _page(admin_client.get(published.location)).find('a', string='К результатам поиска')['href'].endswith(search)
    assert admin_client.post(path + '/publish', data={'preview_id': token}).status_code == 409
    assert AdminAuditLog.query.filter_by(action='grammar_topic.publish_guided', target_id=str(topic.id)).count() == 1
    assert topic.content['guided_exercise_ids'] == ids
    assert topic.content['guided_author_document'] == doc
    assert lesson.content_version == version + 1 and lesson.grammar_topic_id == topic.id
    assert db.session.get(LessonProgress, progress.id).lesson_id == lesson.id
    assert final.title == 'Reference to guided topic'
    assert case.status == 'applied' and case.review == prior_review
    assert [row.id for row in GrammarAttempt.query.filter_by(exercise_id=first.id).all()] == prior_attempt_ids
    assert first.content['theory_help'][0]['body'] == doc['steps'][0]['body']

    student, headers = browser(app, test_user)
    detail = student.get(f'/grammar-lab/api/topic/{topic.id}')
    assert detail.status_code == 200
    assert detail.json['content']['learning_goal'] == doc['goal']
    assert detail.json['content']['learning_steps'][0]['theory'][0]['body'] == doc['steps'][0]['body']
    assert 'guided_author_document' not in detail.text and topic.content['guided_author_document'] == doc
    data = {'answer': APPROVED, 'exercise_revision': lab_revision(first), 'submission_id': str(uuid4())}
    endpoint = f'/grammar-lab/api/exercise/{first.id}/submit'
    grade = student.post(endpoint, headers=headers, json=data)
    repeated = student.post(endpoint, headers=headers, json=data)
    assert grade.status_code == 200 and grade.json['is_correct'] is True and repeated.json == grade.json
    assert GrammarAttempt.query.filter_by(exercise_id=first.id).count() == len(prior_attempt_ids) + 1
    assert not submit(student, headers, first, OLD)['is_correct']


def test_approval_makes_preview_stale_and_changed_question_warns_without_transferring_decision(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User, installed_topic: tuple,
) -> None:
    topic, lesson, _, doc = installed_topic
    path = f'{INDEX}/{topic.id}'
    first = db.session.get(GrammarExercise, topic.content['guided_exercise_ids'][0])
    doc['steps'][0]['body'] = 'New synthetic theory.'
    stale = _field(_page(admin_client.post(path + '/preview', data=_fields(topic, doc))), 'preview_id')
    case = _approve(app, admin_user, test_user, first)
    assert admin_client.post(path + '/publish', data={'preview_id': stale}).status_code == 409
    assert lesson.content['learning_steps'][0]['theory'][0]['body'] == 'First synthetic rule.'

    doc['steps'][0]['exercises'][0]['correct_answer'] = 'I travel by train.'
    preview = _page(admin_client.post(path + '/preview', data=_source(topic, doc)))
    assert f'Упражнение ID {first.id}' in preview.text and f'Споры № {case.id}' in preview.text
    token = _field(preview, 'preview_id')
    assert admin_client.post(path + '/publish', data={'preview_id': token}).status_code == 422
    assert admin_client.post(path + '/publish', data={'preview_id': token, 'acknowledge_decisions': 'yes'}).status_code == 303
    replacement = db.session.get(GrammarExercise, topic.content['guided_exercise_ids'][0])
    assert replacement.id != first.id and replacement.answer_review_override is None
    assert first.content['guided_retired'] and first.answer_review_override
    assert case.grammar_exercise_id == first.id and case.status == 'applied'
    assert GrammarAttempt.query.filter_by(exercise_id=first.id).count() == 1


def test_moderator_exact_source_recovery_and_generic_final_form_still_works(
    app: Flask, admin_client: FlaskClient, test_user: User, installed_topic: tuple,
) -> None:
    topic, lesson, final, doc = installed_topic
    path = f'{INDEX}/{topic.id}'
    doc['editor_note'] = 'Synthetic metadata lost if the source is discarded.'
    install_catalog(documents={topic.slug: doc}, apply=True)
    topic.content = {key: value for key, value in topic.content.items() if key != 'guided_author_document'}
    db.session.commit()
    student, _ = browser(app, test_user)
    assert student.get(path).status_code in (302, 403)
    test_user.is_moderator = True
    db.session.commit()
    editor, _ = browser(app, test_user)
    edit = _page(editor.get(path))
    assert not edit.select_one('#guided-title') and edit.select_one('#guided-document').text == ''
    assert not edit.select_one('#sidebar a[href="/admin/materials"]')
    wrong = deepcopy(doc)
    wrong['editor_note'] = 'Bundled sample is not the current document.'
    assert editor.post(path + '/preview', data=_source(topic, wrong, mode='recover')).status_code == 422
    recovered = _page(editor.post(path + '/preview', data=_source(topic, doc, mode='recover')))
    assert recovered.select_one('#guided-title')['value'] == doc['title']
    assert editor.get(f'/admin/grammar-lab/topics/{topic.id}/edit').status_code in (302, 403)
    doc['goal'] = 'Goal published by the active moderator.'
    preview = _page(editor.post(path + '/preview', data=_fields(topic, doc, recovery=_field(recovered, 'recovery'))))
    assert editor.post(path + '/publish', data={'preview_id': _field(preview, 'preview_id')}).status_code == 303
    assert topic.content['learning_goal'] == doc['goal']

    g.pop('_login_user', None)
    final_path = f'/curriculum/admin/lesson/{final.id}/edit'
    page = _page(admin_client.get(final_path))
    posted = admin_client.post(final_path, data={
        'content_revision': _field(page, 'content_revision'),
        'content': '{"description":"Final form remains independent"}',
    })
    assert posted.status_code == 302 and posted.location.endswith(f'/lesson/{final.id}/view')
    assert final.content['description'] == 'Final form remains independent' and final.grammar_topic_id == topic.id
    for target in [f'/curriculum/admin/lesson/{lesson.id}/edit',
                   f'/admin/grammar-lab/topics/{topic.id}/edit',
                   f'/admin/grammar-lab/exercises/{topic.content["guided_exercise_ids"][0]}/edit']:
        assert admin_client.get(target).location.endswith(path)
        assert admin_client.post(target, data={'content': '{}'}).location.endswith(path)
