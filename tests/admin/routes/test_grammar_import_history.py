"""Exercise the real one-transaction import routes with preserved learner history."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4
import io
import json

import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse

from app.admin.routes import grammar_lab_routes
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute, AnswerDisputeReport, record_lab_rejected_answer
from app.curriculum.answer_review_editor import editor_decide, editor_version
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.grammar_lab.exercise_visibility import active_exercise_clause
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.utils.db import db

JSON_ROUTE = '/admin/grammar-lab/import-exercises-json'
MODULE_ROUTE = '/admin/grammar-lab/import-from-modules'
ORIGINAL = 'I walk to work.'
ACCEPTED = 'I get to work on foot.'
NEW_KEY = 'I drive to work.'


def _topic(number: int, **kwargs: Any) -> GrammarTopic:
    topic = GrammarTopic(slug=f'a1-{number}', title=f'Import {number}', title_ru=f'Import {number}', level='A1', **kwargs)
    db.session.add(topic)
    db.session.flush()
    return topic


def _module(topic: GrammarTopic) -> Lessons:
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Beginner')
        db.session.add(level)
        db.session.flush()
    module = Module(level_id=level.id, number=int(topic.slug.split('-')[-1]), title=topic.title)
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(module_id=module.id, grammar_topic_id=topic.id, type='grammar',
                     title=topic.title, number=1, content={})
    db.session.add(lesson)
    db.session.flush()
    return lesson


def _row(prompt: str, key: str = ORIGINAL) -> dict:
    return {'question': prompt, 'correct_answer': key}


def _upload(number: int, *rows: tuple[dict, dict]) -> tuple[io.BytesIO, str]:
    content = {'module_id': number, 'level': 'A1', 'grammar_topic_slug': 'travel',
               'sessions': [{'exercises': [{'exercise_type': 'translation', 'content': row, **metadata}
                                          for row, metadata in rows]}]}
    return io.BytesIO(json.dumps(content).encode()), f'grammar_extra_a1_{number}.json'


def _file(number: int, row: dict, **metadata: Any) -> tuple[io.BytesIO, str]:
    return _upload(number, (row, metadata))


def _post_json(client: FlaskClient, *files: tuple[io.BytesIO, str]) -> TestResponse:
    return client.post(JSON_ROUTE, data={'json_files': list(files)}, content_type='multipart/form-data')


def _active(topic: GrammarTopic) -> dict[str, GrammarExercise]:
    rows = GrammarExercise.query.filter_by(topic_id=topic.id).filter(active_exercise_clause()).all()
    assert len(rows) == len({row.content['question'] for row in rows}), 'duplicate active prompt'
    return {row.content['question']: row for row in rows}


def _approve(exercise: GrammarExercise, learner: User, admin: User) -> tuple[int, int]:
    assert not GrammarExerciseGrader().grade(exercise, ACCEPTED)['is_correct']
    attempt = GrammarAttempt(user_id=learner.id, exercise_id=exercise.id, user_answer=ACCEPTED,
                             is_correct=False, source='topic_practice')
    db.session.add(attempt)
    db.session.flush()
    record_lab_rejected_answer(db.session, exercise, ACCEPTED, 'i get to work on foot',
                               user_id=learner.id, grammar_attempt_id=attempt.id)
    case = AnswerDispute.query.filter_by(grammar_exercise_id=exercise.id).one()
    editor_decide(case.id, admin.id, editor_version(case), 'add', ACCEPTED)
    return case.id, attempt.id


def _assert_history(exercise: GrammarExercise, case_id: int, attempt_id: int) -> None:
    assert db.session.get(AnswerDispute, case_id).status == 'applied'
    assert db.session.get(GrammarAttempt, attempt_id).exercise_id == exercise.id
    assert AnswerDisputeReport.query.filter_by(dispute_id=case_id, grammar_attempt_id=attempt_id).one()
    assert exercise.answer_review_override['patch']['alternatives'] == [ACCEPTED]


@pytest.mark.parametrize('source', ['json', 'module'])
def test_repeat_and_changed_key_keep_history_without_a_second_active_version(
    source: str, admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    topic = _topic(611)
    db_session.commit()
    lesson = _module(topic) if source == 'module' else None

    def post(*rows: dict) -> TestResponse:
        if lesson is None:
            # Exercise sequence and file split can be changed independently.
            return _post_json(admin_client, *(_file(611, row) for row in rows))
        lesson.content = {'exercises': [{'type': 'translation', **row} for row in rows]}
        db_session.commit()
        return admin_client.post(MODULE_ROUTE)

    first, second = _row('Main'), _row('Other', 'We are late.')
    assert post(first, second).location.endswith('/admin/grammar-lab')
    original = _active(topic)['Main']
    identities = {name: exercise.id for name, exercise in _active(topic).items()}
    case_id, attempt_id = _approve(original, test_user, admin_user)
    assert post(second, first).location.endswith('/admin/grammar-lab')
    assert {name: exercise.id for name, exercise in _active(topic).items()} == identities
    assert GrammarExerciseGrader().grade(original, ACCEPTED)['is_correct']
    _assert_history(original, case_id, attempt_id)

    assert post(_row('Main', NEW_KEY), second).location.endswith('/admin/grammar-lab')
    active = _active(topic)['Main']
    assert active.id != original.id and active.answer_review_override is None
    assert active.content['correct_answer'] == NEW_KEY
    assert not GrammarExerciseGrader().grade(active, ACCEPTED)['is_correct']
    assert original.content['guided_retired'] is True
    _assert_history(original, case_id, attempt_id)

    # A stale complete snapshot must neither revive A nor retire the active B.
    rejected = post(first, second)
    assert rejected.status_code == 302
    with admin_client.session_transaction() as session:
        assert any('ранее снятое упражнение' in message for _, message in session.get('_flashes', []))
    assert _active(topic)['Main'].id == active.id
    assert original.content['guided_retired'] is True


def test_json_permutation_and_metadata_update_keep_the_same_id_and_history(
    admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    topic = _topic(612)
    db_session.commit()
    a, b = _row('Main'), _row('Other', 'We are late.')
    assert _post_json(admin_client, _upload(612, (a, {'order': 1}), (b, {'order': 2}))).status_code == 302
    exercise = _active(topic)['Main']
    case_id, attempt_id = _approve(exercise, test_user, admin_user)
    response = _post_json(admin_client, _upload(612, (b, {'order': 2}), (a, {'order': 9, 'difficulty': 3})))
    assert response.location.endswith('/admin/grammar-lab')
    assert _active(topic)['Main'].id == exercise.id
    assert (exercise.order, exercise.difficulty) == (9, 3)
    assert GrammarExerciseGrader().grade(exercise, ACCEPTED)['is_correct']
    _assert_history(exercise, case_id, attempt_id)


def test_module_reuses_untagged_exact_exercise_without_taking_ownership(
    admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    topic = _topic(613)
    lesson = _module(topic)
    authored = {'type': 'translation', **_row('Main')}
    _, material = grammar_lab_routes._module_exercise_content(authored)
    legacy_content = {key: value for key, value in material.items() if key != 'source'}
    exercise = GrammarExercise(topic_id=topic.id, exercise_type='translation',
                               content=legacy_content, order=19, difficulty=2)
    archived_source = {'type': 'translation', **_row('Manual retired')}
    _, archived_material = grammar_lab_routes._module_exercise_content(archived_source)
    archived_content = {key: value for key, value in archived_material.items() if key != 'source'}
    manual_retired = GrammarExercise(topic_id=topic.id, exercise_type='translation',
                                     content={**archived_content, 'guided_retired': True})
    lesson.content = {'exercises': [authored]}
    db_session.add_all([exercise, manual_retired])
    db_session.commit()
    case_id, attempt_id = _approve(exercise, test_user, admin_user)
    for _ in range(2):
        assert admin_client.post(MODULE_ROUTE).status_code == 302
        assert [row.id for row in _active(topic).values()] == [exercise.id]
        assert exercise.content == legacy_content and (exercise.order, exercise.difficulty) == (19, 2)
        assert GrammarExerciseGrader().grade(exercise, ACCEPTED)['is_correct']
        assert manual_retired.content['guided_retired'] is True
        _assert_history(exercise, case_id, attempt_id)
    lesson.content = {'exercises': [archived_source]}
    db_session.commit()
    assert admin_client.post(MODULE_ROUTE).status_code == 302
    with admin_client.session_transaction() as session:
        assert any('ранее снятое упражнение' in message for _, message in session.get('_flashes', []))
    assert [row.id for row in _active(topic).values()] == [exercise.id]
    assert manual_retired.content == {**archived_content, 'guided_retired': True}


@pytest.mark.parametrize('invalid', ['syntax', 'exercise'])
def test_invalid_second_json_file_cancels_all_topics(
    invalid: str, admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    first = _topic(614)
    another = _topic(615)
    db_session.commit()
    assert _post_json(admin_client, _file(614, _row('Before'))).status_code == 302
    old = _active(first)['Before']
    error = ((io.BytesIO(b'{'), 'bad.json') if invalid == 'syntax'
             else _file(615, {'question': 'Missing key'}))
    response = _post_json(admin_client, _file(614, _row('New')), error)
    assert response.location.endswith(JSON_ROUTE)
    assert [row.id for row in _active(first).values()] == [old.id]
    assert not _active(another)
    assert GrammarExercise.query.filter_by(topic_id=first.id).count() == 1


def test_invalid_module_cancels_another_valid_module_and_guided_is_protected(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    first, second = _topic(616), _topic(617)
    guided = _topic(618, content={'guided_catalog_digest': 'authored'})
    lesson, bad_lesson, guided_lesson = _module(first), _module(second), _module(guided)
    guided_exercise = GrammarExercise(topic_id=guided.id, exercise_type='translation',
                                       content={**_row('Guided'), 'guided_key': 'keep'})
    lesson.content = {'exercises': [{'type': 'translation', **_row('Before')}]}
    guided_lesson.content = {'exercises': ['invalid if treated as legacy']}
    db_session.add(guided_exercise)
    db_session.commit()
    assert admin_client.post(MODULE_ROUTE).status_code == 302
    old = _active(first)['Before']
    lesson.content = {'exercises': [{'type': 'translation', **_row('After')}]}
    bad_lesson.content = {'exercises': [{'type': 'translation', 'question': 'Missing key'}]}
    db_session.commit()
    assert admin_client.post(MODULE_ROUTE).status_code == 302
    assert [row.id for row in _active(first).values()] == [old.id]
    assert guided.content == {'guided_catalog_digest': 'authored'}
    assert _active(guided)['Guided'].id == guided_exercise.id
    assert _post_json(admin_client, _file(618, _row('Extra'))).location.endswith(JSON_ROUTE)
    assert [row.id for row in _active(guided).values()] == [guided_exercise.id]


def test_concurrent_json_posts_do_not_duplicate_a_replacement(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Independent row locks require PostgreSQL')
    topic = _topic(619)
    suffix = uuid4().hex
    admin = User(username=f'grammar_import_{suffix}', email=f'{suffix}@example.invalid', active=True,
                 is_admin=True, onboarding_completed=True)
    admin.set_password('synthetic-import-test')
    db.session.add(admin)
    db.session.commit()
    topic_id, admin_id = topic.id, admin.id
    login_id = admin.get_id()
    barrier = Barrier(2)
    real = grammar_lab_routes.lock_topics

    def wait_for_other_request(topic_ids: Any) -> dict[int, GrammarTopic]:
        barrier.wait(timeout=8)
        return real(topic_ids)

    monkeypatch.setattr(grammar_lab_routes, 'lock_topics', wait_for_other_request)

    def import_once() -> str:
        with app.app_context():
            client = app.test_client()
            g.pop('_login_user', None)
            with client.session_transaction() as session:
                session['_user_id'] = login_id
                session['_fresh'] = True
            return _post_json(client, _file(619, _row('Concurrent'))).location

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(import_once) for _ in range(2)]
            locations = [future.result(timeout=15) for future in futures]
        assert all(location.endswith('/admin/grammar-lab') for location in locations), locations
        assert GrammarExercise.query.filter_by(topic_id=topic_id).count() == 1
    finally:
        db.session.rollback()
        db.session.delete(db.session.get(GrammarTopic, topic_id))
        db.session.delete(db.session.get(User, admin_id))
        db.session.commit()
