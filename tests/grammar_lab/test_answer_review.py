"""Exercise owner decisions with the independent Grammar Lab grader and its authored catalog."""
from collections.abc import Iterator
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

from flask import Flask
import pytest
from werkzeug.test import TestResponse

from app.curriculum import answer_review as worker
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute, record_lab_rejected_answer
from app.grammar_lab.answer_review import effective_content, lab_revision
from app.grammar_lab.content_catalog import compile_topic, load_catalog
from app.grammar_lab.dispute_receipts import normalized_lab_answer
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.telegram import bot
from app.utils.db import db
from tests.answer_review_fixtures import telegram_admin
from tests.api.test_grammar_lab_disputes import browser, dispute, submit
from tests.api.test_native_full_integration import learner
from tests.api.test_quiz_corrections import native_app


def exercise_for(row: dict) -> GrammarExercise:
    topic = GrammarTopic(slug='review-' + uuid4().hex[:12], title='Lab', title_ru='Тема', level='A1', content={})
    db.session.add(topic)
    db.session.flush()
    exercise = GrammarExercise(topic_id=topic.id, exercise_type=row['type'], content=deepcopy(row))
    db.session.add(exercise)
    db.session.commit()
    return exercise


def report(exercise: GrammarExercise, answer: object) -> AnswerDispute:
    record_lab_rejected_answer(db.session, exercise, answer, normalized_lab_answer(exercise, answer))
    db.session.commit()
    return AnswerDispute.query.filter_by(grammar_exercise_id=exercise.id, status='pending').one()


@pytest.fixture
def services(
    native_app: Flask, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> Iterator[tuple[Flask, Mock, Mock, int]]:
    for key, val in {'OPENAI_MODEL': 'test-model', 'OPENAI_API_KEY': 'test-key',
                     'TELEGRAM_BOT_TOKEN': 'test-bot'}.items():
        monkeypatch.setitem(native_app.config, key, val)
    classify = Mock(side_effect=lambda *a, **kw: {'label': 'valid_variant', 'reason': 'Смысл сохранён.'})
    send = Mock(return_value=True)
    monkeypatch.setattr(ai, 'classify', classify)
    monkeypatch.setattr(bot, 'send_message', send)
    with telegram_admin() as binding:
        yield native_app, classify, send, binding.telegram_id


def test_topic_four_bus_and_duplicate_lab_report(services: tuple) -> None:
    _, classify, send, _ = services
    rows = compile_topic(load_catalog(['a1-4'])['a1-4'])['exercises']
    raw = next(row for row in rows if row['question'] == 'one bus → two ___')
    exercise = exercise_for(raw)
    grade = GrammarExerciseGrader().grade
    assert not grade(exercise, 'two busess')['is_correct'] and grade(exercise, 'buses')['is_correct']
    case = report(exercise, 'two busess')
    assert report(exercise, 'TWO BUSess.').id == case.id
    classify.side_effect = None
    classify.return_value = {'label': 'learner_error', 'reason': 'Нужна форма buses.'}
    assert worker.process_one() and case.status == 'closed'
    assert not worker.process_one()
    assert classify.call_args.args[0]['question']['instruction'] == raw['instruction']
    assert classify.call_args.args[0]['submitted_answer'] == 'two busess'
    send.assert_not_called()
    assert exercise.content == raw and exercise.answer_review_override is None


def test_owner_approval_survives_identical_reimport_and_stales_old_native_attempt(services: tuple) -> None:
    app, classify, send, telegram_id = services
    raw = {'type': 'translation', 'question': 'Я хожу на работу пешком.', 'instruction': 'Переведи свободно.',
           'correct_answer': 'I walk to work.', 'answer': 'I walk to work.', 'guided_key': 'walk-to-work',
           'guided_revision': 'catalog-v1'}
    exercise = exercise_for(raw)
    new_answer = 'I go to work on foot.'
    initial = lab_revision(exercise)
    _, headers = learner(app)
    client = app.test_client()

    def start() -> dict:
        response = client.post('/api/native/activities/grammar_topic/start', headers=headers,
                               json={'item_id': f'grammar_topic:{exercise.topic_id}', 'request_id': str(uuid4())})
        assert response.status_code == 200, response.json
        return response.json['lesson']

    initial_run = start()
    case = report(exercise, new_answer)
    assert worker.process_one() and worker.process_one()
    assert case.review['patch'] == {'alternatives': [new_answer]}
    assert 'Grammar Lab' in send.call_args.args[1] and 'Добавить допустимый ответ' in send.call_args.args[1]
    assert classify.call_args.args[0]['expected'] == raw['correct_answer']
    tag = worker.decision_tag(case)
    assert worker.decide(case.id, tag, 'approve', 99, 99) == 'Решение доступно администратору'
    assert case.status == 'notified'
    assert not GrammarExerciseGrader().grade(exercise, new_answer)['is_correct']
    assert worker.decide(case.id, tag, 'approve', telegram_id, telegram_id) == 'Правка применена'
    assert 'уже обработана' in worker.decide(case.id, tag, 'approve', telegram_id, telegram_id)
    db.session.refresh(exercise)
    assert exercise.content == raw and lab_revision(exercise) != initial
    assert all(GrammarExerciseGrader().grade(exercise, value)['is_correct'] for value in (new_answer, raw['correct_answer']))
    assert not GrammarAttempt.query.filter_by(exercise_id=exercise.id).count()

    def check(token: str) -> TestResponse:
        return client.post('/api/native/activities/grammar_topic/check', headers=headers,
                           json={'session_token': token, 'question_id': '0', 'answer': new_answer})
    assert check(initial_run['session_token']).status_code == 409
    assert check(start()['session_token']).json['feedback']['correct']
    exercise.content = {**raw, 'guided_revision': 'catalog-v2'}
    db.session.commit()
    assert GrammarExerciseGrader().grade(exercise, new_answer)['is_correct']
    exercise.content = {**raw, 'instruction': 'Используй глагол walk.'}
    db.session.commit()
    assert not GrammarExerciseGrader().grade(exercise, new_answer)['is_correct']


@pytest.mark.parametrize('change_before_approval', [True, False])
def test_wrong_choice_key_and_concurrent_editorial_change(services: tuple, change_before_approval: bool) -> None:
    _, classify, _, telegram_id = services
    raw = {'type': 'multiple_choice', 'question': 'Выбери перевод слова «магазин».',
           'options': ['magazine', 'shop', 'newspaper'], 'correct_answer': 'magazine', 'answer': 'magazine'}
    exercise = exercise_for(raw)
    case = report(exercise, 1)
    classify.side_effect = None
    classify.return_value = {'label': 'wrong_key', 'reason': 'Shop — магазин.'}
    assert worker.process_one() and worker.process_one()
    assert case.review['patch'] == {'correct_answer': 'shop'}
    if change_before_approval:
        exercise.content = {**raw, 'question': 'Выбери перевод слова «журнал».'}
        db.session.commit()
    worker.decide(case.id, worker.decision_tag(case), 'approve', telegram_id, telegram_id)
    if change_before_approval:
        assert case.status == 'stale' and exercise.answer_review_override is None
    else:
        assert case.status == 'applied' and exercise.content == raw
        assert effective_content(exercise)['answer'] == 'shop'
        assert exercise.to_dict()['correct_answer'] == 'shop'
        assert [GrammarExerciseGrader().grade(exercise, i)['is_correct'] for i in range(3)] == [False, True, False]


def test_web_receipt_to_approved_answer_on_next_web_submission(services: tuple) -> None:
    app, _, _, telegram_id = services
    user, _ = learner(app)
    client, headers = browser(app, user)
    exercise = exercise_for({'type': 'translation', 'question': 'Сейчас холодно.', 'instruction': 'Переведи свободно.',
                             'correct_answer': 'It is cold now.'})
    alternate = "It's chilly now."
    receipt = submit(client, headers, exercise, alternate)
    assert receipt['is_correct'] is False
    for _ in range(2):
        assert dispute(client, headers, exercise, receipt['dispute_token'], alternate).json == {'success': True}
    case = AnswerDispute.query.filter_by(grammar_exercise_id=exercise.id).one()
    assert worker.process_one() and worker.process_one()
    assert worker.decide(case.id, worker.decision_tag(case), 'approve', telegram_id, telegram_id) == 'Правка применена'
    assert GrammarAttempt.query.filter_by(exercise_id=exercise.id).count() == 1
    result = submit(client, headers, exercise, alternate)
    assert result['is_correct'] and 'dispute_token' not in result
    assert submit(client, headers, exercise, 'It is cold now.')['is_correct']


def test_matching_displays_selected_pairs_and_grader_issue_uses_manual_review(services: tuple) -> None:
    _, classify, send, telegram_id = services
    exercise = exercise_for({'type': 'matching', 'instruction': 'Соедини пары.',
                             'pairs': [{'english': 'one', 'russian': 'один'}, {'english': 'two', 'russian': 'два'}]})
    case = report(exercise, {'0': '1', '1': '0'})
    classify.side_effect = None
    classify.return_value = {'label': 'grader_issue', 'reason': 'Разобрать сравнение.'}
    assert worker.process_one() and worker.process_one()
    assert 'one → два' in send.call_args.args[1] and 'two → два' in send.call_args.args[1]
    assert worker.decide(case.id, worker.decision_tag(case), 'approve', telegram_id, telegram_id) == 'Передано на ручной разбор'
    assert exercise.answer_review_override is None
