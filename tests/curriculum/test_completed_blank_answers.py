"""Written cloze responses across the common graders and their real endpoints."""
# ruff: noqa: RUF001 -- fixtures and assertions include Russian learner instructions.

from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask, g
from flask.testing import FlaskClient
from flask_login import login_user
from sqlalchemy.orm import scoped_session
import pytest

from app.curriculum.blank_answers import BLANK_TYPES, blank_instruction, legacy_blank_row
from app.curriculum.grading import process_grammar_submission, process_quiz_submission
from app.curriculum.models import CEFRLevel, LessonAttempt, Lessons, Module
from app.curriculum.routes.grammar_quiz_lessons import render_final_test_lesson
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic
from app.grammar_lab.content_install import install_catalog
from app.grammar_lab.services.grader import GrammarExerciseGrader
from tests.admin.test_guided_topic_editor import installed_topic as installed_topic
from tests.api.test_grammar_lab_disputes import browser
from tests.api.test_native_full_integration import learner

QUESTION = 'Is she ready? — Yes, she ___.'
INSTRUCTION = 'Дай краткий утвердительный ответ. Впиши только форму be.'
ROW = {'type': 'fill_blank', 'question': QUESTION, 'correct_answer': 'is', 'instruction': INSTRUCTION}
VALID = ['is', 'Yes, she is.', 'YES SHE IS']
INVALID = ["Yes, she’s.", 'Yes, he is', 'No, she is', 'Yes, she are', 'Yes, she is ready', 'Yes, she is is']
XHR = {'X-Requested-With': 'XMLHttpRequest'}


def _all_graders(row: dict, answer: str, expected: bool) -> None:
    for grade in (process_grammar_submission, process_quiz_submission):
        assert grade([row], {'0': answer})['correct_answers'] == int(expected)
    exercise = SimpleNamespace(id=1, exercise_type='fill_blank', content=row)
    assert GrammarExerciseGrader().grade(exercise, answer)['is_correct'] is expected


@pytest.mark.parametrize(('answer', 'expected'), [(a, True) for a in VALID] + [(a, False) for a in INVALID])
def test_short_affirmative_answer(answer: str, expected: bool) -> None:
    _all_graders(ROW, answer, expected)


@pytest.mark.parametrize(('prompt', 'key', 'answer'), [
    ('She ___ my sister.', 'is', "She's my sister."),
    ('No, he ___.', 'cannot', "No, he can't."),
    ('We are ___ ___ plant tomatoes on Saturday.', 'going to', "We're going to plant tomatoes on Saturday."),
    ('The warning light has flashed! It ___ ___ ___ stop.', 'is going to', 'It is going to stop.'),
    ('He whispered in order ___ ___ wake the baby.', 'not to', 'He whispered in order not to wake the baby.'),
    ('Nina is ___ ___ ___ Paul. (tall)', 'as tall as', 'Nina is as tall as Paul.'),
    ('one dish → two ___ (Добавь окончание: dish ___.)', 'dishes', 'two dishes'),
    ('Please hold ___ — the elevator is full.', 'on', 'Please hold on — the elevator is full.'),
    ("It's raining ___. The streets are flooded.", 'hard', "It's raining hard."),
    ('Wait for Dr. Jones at ___ p.m. today.', 'five', 'Wait for Dr. Jones at five p.m. today.'),
    ('My uncle lives in ___ France. (— если артикль не нужен)', '—', 'My uncle lives in France.'),
])
def test_exact_target_and_eligible_contractions(prompt: str, key: str, answer: str) -> None:
    row = {**ROW, 'question': prompt, 'correct_answer': key}
    _all_graders(row, answer, True)
    _all_graders(row, answer + ' extra', False)


def test_lab_keeps_original_context_and_requires_the_original_words() -> None:
    row = SimpleNamespace(id=1, exercise_type='fill_blank', content=ROW)
    grader = GrammarExerciseGrader()
    assert grader.grade(row, 'Is she ready? — Yes, she is.')['is_correct']
    assert not grader.grade(row, 'Is he ready? — Yes, she is.')['is_correct']
    assert not grader.grade(row, "Is she ready? — Yes, she's.")['is_correct']


@pytest.mark.parametrize(('prompt', 'key', 'contracted', 'wrong_tense'), [
    ('She ___ finished her report.', 'has', "She's finished her report.", 'She had finished her report.'),
    ('They ___ been outside all morning.', 'have', "They've been outside all morning.",
     'They had been outside all morning.'),
    ('I ___ prefer coffee.', 'would', "I'd prefer coffee.", 'I had prefer coffee.'),
])
def test_internal_contractions_do_not_accept_an_explicit_tense_shift(
    prompt: str, key: str, contracted: str, wrong_tense: str,
) -> None:
    row = {**ROW, 'question': prompt, 'correct_answer': key}
    _all_graders(row, contracted, True)
    _all_graders(row, wrong_tense, False)


@pytest.mark.parametrize(('prompt', 'key', 'alias', 'completed'), [
    ('I packed a green ___. (футболка)', 'T-shirt', 'tee', 'I packed a green tee.'),
    ('The guide ___ works on Mondays plays violin.', 'who', 'that', 'The guide that works on Mondays plays violin.'),
])
@pytest.mark.parametrize('field', ['alternatives', 'alternative_answers', 'acceptable_answers'])
def test_authored_short_and_full_aliases(prompt: str, key: str, alias: str, completed: str, field: str) -> None:
    authored = completed.replace(alias, key, 1)
    other_full = 'This is a separate accepted answer.'
    row = {**ROW, 'question': prompt, 'correct_answer': key, field: [alias, authored, other_full]}
    for answer in (alias, completed, authored, other_full):
        _all_graders(row, answer, True)
    head, tail = prompt.split('___')
    for full in (authored, other_full, other_full.rstrip('.')):
        _all_graders(row, head + full.rstrip('.') + tail.split(' (')[0], False)
    _all_graders(row, 'And ' + completed, False)


def test_ambiguous_and_choice_items_keep_discrete_rules() -> None:
    two = {**ROW, 'question': '___ she ready when he ___?'}
    _all_graders(two, 'Is she ready when he is?', False)
    conflict = {**ROW, 'prompt': 'He ___ my brother.'}
    _all_graders(conflict, 'Yes, she is.', False)
    choice = {**ROW, 'options': ['are', 'is']}
    _all_graders(choice, 'Yes, she is.', False)
    _all_graders(choice, 'is', True)


@pytest.mark.parametrize('instruction', [
    INSTRUCTION, 'Выбери форму have для Nina — одно слово.',
    'Поставь work в нужное время и впиши одно слово в пропуск.',
])
def test_instruction_keeps_the_authored_task(instruction: str) -> None:
    row = {**ROW, 'instruction': instruction}
    projected = blank_instruction(row)
    assert projected.startswith('Для краткого ответа: ' + instruction)
    assert projected.endswith('Можно также написать фразу с заполненным пропуском целиком.')
    assert row['instruction'] == instruction


@pytest.fixture
def endpoints(app: Flask, db_session: scoped_session) -> tuple:
    user, bearer = learner(app)
    user.is_admin = True
    user.onboarding_completed = True
    level = CEFRLevel.query.filter_by(code='A1').first()
    if not level:
        level = CEFRLevel(code='A1', name='A1')
        db_session.add(level)
        db_session.flush()
    module = Module(level_id=level.id, number=973, title='Written cloze test', input_mode='mixed')
    db_session.add(module)
    db_session.commit()
    web, csrf = browser(app, user)
    return user, module, web, csrf, app.test_client(), bearer


def _lesson(db_session: scoped_session, module: Module, kind: str, rows: list[dict]) -> Lessons:
    field = 'exercises' if kind == 'grammar' else 'questions'
    lesson = Lessons(module_id=module.id, number=1, order=1, title='Text gap test', type=kind,
                     content={field: rows, 'description': 'Exercise fixture.'})
    db_session.add(lesson)
    db_session.commit()
    return lesson


@pytest.mark.parametrize(('transport', 'kind'), [
    ('web', 'grammar'), ('web', 'final_test'), ('native', 'quiz'), ('native', 'final_test'),
])
def test_versioned_course_endpoints(db_session: scoped_session, endpoints: tuple, transport: str, kind: str) -> None:
    user, module, web, csrf, native, bearer = endpoints
    rows = [{**ROW, 'question': QUESTION}, {**ROW, 'question': 'She ___ my sister.'}]
    lesson = _lesson(db_session, module, kind, rows)
    if transport == 'web':
        client, headers = web, csrf
        base = f'/curriculum/api/lesson/{lesson.id}/practice'
    else:
        client, headers = native, bearer
        base = f'/api/native/lessons/{lesson.id}'
    document = client.get(base, headers=headers)
    assert document.status_code == 200, document.text
    content = document.json['lesson']
    assert INSTRUCTION in content['questions'][0]['instruction']
    assert 'completed_blanks' not in document.text and 'correct_answer' not in document.text
    token = content['session_token']
    if kind != 'final_test':
        for answer in [*VALID, *INVALID]:
            response = client.post(base + '/check', headers=headers,
                                   json={'session_token': token, 'question_id': '0', 'answer': answer})
            assert response.status_code == 200, response.text
            assert response.json['feedback']['correct'] is (answer in VALID)
        assert LessonAttempt.query.filter_by(lesson_id=lesson.id, user_id=user.id).count() == 0
    else:
        response = client.post(base + '/check', headers=headers,
                               json={'session_token': token, 'question_id': '0', 'answer': VALID[0]})
        assert response.status_code == 404
    body = {'session_token': token, 'answers': {'0': 'Yes, she is.', '1': "She's my sister."}}
    response = client.post(base + '/submit', headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json['score'] == 100
    assert client.post(base + '/submit', headers=headers, json=body).json == response.json


@pytest.mark.parametrize('kind', ['quiz', 'final_test'])
def test_legacy_web_all_four_types_and_option_keys(
    app: Flask, db_session: scoped_session, endpoints: tuple, kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, module, client, headers, _, _ = endpoints
    rows = []
    answers = {}
    client_results = []
    for alias in sorted(BLANK_TYPES):
        for fields, submitted, label in (
            ({}, 'Yes, she is.', None),
            ({'options': ['1', 'is'], 'correct_answer': '1'}, '1', '1'),
            ({'options': ['is', 'are'], 'correct_index': 0}, '0', None),
        ):
            idx = len(rows)
            row = {**ROW, 'type': alias, **fields}
            if 'correct_index' in fields:
                del row['correct_answer']
            rows.append(row)
            answers[f'answer_{idx}'] = submitted
            if label is not None:
                client_results.append({'question_index': idx, 'answer': label})
                if kind == 'final_test':
                    answers[f'option_text_{idx}'] = label
    monkeypatch.setattr('app.curriculum.routes.grammar_quiz_lessons.random.shuffle', lambda values: values.reverse())
    lesson = _lesson(db_session, module, kind, rows)
    route = f'/curriculum/lesson/{lesson.id}/{kind}?ui=legacy'
    response = client.get(route)
    if kind == 'final_test':
        assert response.status_code == 302
        active = client.get(response.location)
        assert active.status_code == 200 and 'completed_blanks' not in active.text
        # The old renderer can grade archived forms, but production never
        # serves its embedded keys on a final-test GET.
        with app.test_request_context(route):
            login_user(user)
            source = render_final_test_lesson(lesson)
    else:
        assert response.status_code == 200, response.text
        source = response.text
    assert source.count('"type": "fill_blank"') >= len(rows)
    assert source.count('"completed_blanks": ["yes she is"]') == len(BLANK_TYPES)
    assert 'curriculum-completed-blank.js' in source
    if kind == 'quiz':
        answers['client_results'] = json.dumps(client_results)
    response = client.post(route, data=answers, headers={**headers, **XHR})
    assert response.status_code == 200, response.text
    assert response.json['score'] == 100
    db_session.refresh(lesson)
    assert lesson.content['questions'] == rows
    assert legacy_blank_row(rows[0])['type'] == 'fill_blank'


def test_lab_web_and_native_attempts(db_session: scoped_session, endpoints: tuple) -> None:
    user, _, web, csrf, native, bearer = endpoints
    topic = GrammarTopic(slug='cloze-test', title='Cloze', title_ru='Cloze', level='A1', content={})
    db_session.add(topic)
    db_session.flush()
    exercise = GrammarExercise(topic_id=topic.id, exercise_type='fill_blank', content=deepcopy(ROW))
    db_session.add(exercise)
    db_session.commit()
    projected = exercise.to_dict(hide_answer=True)
    assert INSTRUCTION in projected['instruction'] and 'correct_answer' not in projected
    original = deepcopy(exercise.content)
    response = web.post(f'/grammar-lab/api/exercise/{exercise.id}/submit', headers=csrf, json={'answer': 'Yes, she is.'})
    assert response.status_code == 200, response.text
    assert response.json['is_correct'] is True
    g.pop('_login_user', None)
    base = '/api/native/activities/grammar_topic'
    response = native.post(base + '/start', headers=bearer,
                           json={'item_id': f'grammar_topic:{topic.id}', 'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    document = response.json['lesson']
    token = document['session_token']
    assert INSTRUCTION in document['questions'][0]['instruction']
    for answer in ["Yes, she's.", 'Yes, she is.']:
        response = native.post(base + '/check', headers=bearer,
                               json={'session_token': token, 'question_id': '0', 'answer': answer})
        assert response.status_code == 200, response.text
        assert response.json['feedback']['correct'] is ("'" not in answer)
    assert GrammarAttempt.query.filter_by(user_id=user.id, exercise_id=exercise.id).count() == 1
    response = native.post(base + '/submit', headers=bearer, json={
        'session_token': token, 'answers': {'0': 'Yes, she is.'},
    })
    assert response.status_code == 200, response.text
    assert response.json['correct_count'] == 1
    assert GrammarAttempt.query.filter_by(user_id=user.id, exercise_id=exercise.id).count() == 2
    assert exercise.content == original


def test_native_quiz_all_four_types_keep_option_identity(db_session: scoped_session, endpoints: tuple) -> None:
    _, module, _, _, client, headers = endpoints
    rows = [{**ROW, 'type': kind, 'correct_answer': '1', 'options': ['1', 'are']}
            for kind in sorted(BLANK_TYPES)]
    lesson = _lesson(db_session, module, 'quiz', rows)
    base = f'/api/native/lessons/{lesson.id}'
    document = client.get(base, headers=headers).json['lesson']
    token = document['session_token']
    answers = {}
    for q in document['questions']:
        answers[q['id']] = next(option['value'] for option in q['options'] if option['label'] == '1')
        response = client.post(base + '/check', headers=headers, json={
            'session_token': token, 'question_id': q['id'], 'answer': answers[q['id']],
        })
        assert response.status_code == 200 and response.json['feedback']['correct'] is True
    response = client.post(base + '/submit', headers=headers, json={'session_token': token, 'answers': answers})
    assert response.status_code == 200 and response.json['score'] == 100


def test_guided_admin_previews_learner_copy_without_changing_author_document(
    admin_client: FlaskClient, installed_topic: tuple,
) -> None:
    topic, _, _, document = installed_topic
    document['steps'][0]['exercises'][0].update(ROW)
    install_catalog(documents={topic.slug: document}, apply=True)
    response = admin_client.get(f'/admin/grammar-lab/guided/{topic.id}')
    assert response.status_code == 200
    assert 'Для краткого ответа: ' + INSTRUCTION in response.text
    assert 'Можно также написать фразу с заполненным пропуском целиком.' in response.text
    assert topic.content['guided_author_document'] == document
