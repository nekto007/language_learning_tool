"""Exercise owner decisions with the independent Grammar Lab grader and its authored catalog."""
from collections.abc import Iterator
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from flask import Flask
import pytest
from werkzeug.test import TestResponse

from app.curriculum import answer_review as worker
from app.curriculum.answer_review_editor import editor_decide, editor_preview, editor_version
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute, record_lab_rejected_answer
from app.grammar_lab.answer_review import effective_content, lab_revision, proposed_lab_edit
from app.grammar_lab.content_catalog import compile_topic, load_catalog
from app.grammar_lab.dispute_receipts import normalized_lab_answer
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.telegram import bot
from app.telegram.models import TelegramUser
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
) -> Iterator[tuple[Flask, Mock, Mock, TelegramUser]]:
    for key, val in {'OPENAI_MODEL': 'test-model', 'OPENAI_API_KEY': 'test-key',
                     'TELEGRAM_BOT_TOKEN': 'test-bot'}.items():
        monkeypatch.setitem(native_app.config, key, val)
    classify = Mock(side_effect=lambda *a, **kw: {'label': 'valid_variant', 'reason': 'Смысл сохранён.'})
    send = Mock(return_value=True)
    monkeypatch.setattr(ai, 'classify', classify)
    monkeypatch.setattr(bot, 'send_message', send)
    with telegram_admin() as binding:
        yield native_app, classify, send, binding


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
    assert worker.process_one() and case.status == 'ready'
    assert worker.process_one() and case.status == 'notified'
    assert not worker.process_one()
    assert classify.call_args.args[0]['question']['instruction'] == raw['instruction']
    assert classify.call_args.args[0]['submitted_answer'] == 'two busess'
    send.assert_called_once()
    assert 'two busess' in send.call_args.args[1]
    assert 'Нужна форма buses.' in send.call_args.args[1]
    assert exercise.content == raw and exercise.answer_review_override is None


def test_true_false_dispute_card_keeps_the_actual_statement(services: tuple) -> None:
    _, classify, send, _ = services
    statement = '«Don’t have to» означает запрет.'
    exercise = exercise_for({'type': 'true_false', 'statement': statement, 'correct_answer': False})
    case = report(exercise, 'true')
    classify.side_effect = None
    classify.return_value = {'label': 'learner_error', 'reason': 'Это отсутствие обязанности.'}
    assert case.evidence['question']['prompt'] == statement
    assert worker.process_one() and worker.process_one()
    assert case.status == 'notified'
    assert send.call_args.args[1].count(statement) == 1


@pytest.mark.parametrize('old_state', ['notified', 'manual'])
def test_old_manual_reorder_button_requires_fresh_approval(services: tuple, old_state: str) -> None:
    _, classify, send, admin = services
    key = 'I found a small toy in the box'
    variant = 'I found a toy in the small box'
    exercise = exercise_for({'type': 'reorder', 'words': key.split(), 'correct_answer': key,
                             'instruction': 'Собери предложение.'})
    case = report(exercise, variant)
    case.review = {'label': 'valid_variant', 'reason': 'Оба порядка допустимы.', 'patch': None,
                   'shown_answer': variant, 'shown_key': key, 'notified_telegram_ids': [admin.telegram_id]}
    case.status = old_state
    db.session.commit()
    proposal = editor_preview(case, 'add', variant)
    assert proposal['accepts_report'] and exercise.answer_review_override is None
    card, _ = worker._telegram_card(case)
    assert f'/admin/grammar-lab/exercises/{exercise.id}/edit' in card
    assert 'Автор обращения не сохранён' in card
    original_version = editor_version(case)
    editor_decide(case.id, admin.user_id, original_version, 'add', variant)
    with pytest.raises(ValueError):
        editor_decide(case.id, admin.user_id, original_version, 'add', variant)
    classify.assert_not_called()
    send.assert_not_called()
    assert all(GrammarExerciseGrader().grade(exercise, answer)['is_correct'] for answer in (key, variant))
    assert GrammarAttempt.query.filter_by(exercise_id=exercise.id).count() == 0


def test_owner_approval_survives_identical_reimport_and_stales_old_native_attempt(services: tuple) -> None:
    app, classify, send, admin = services
    raw = {'type': 'translation', 'question': 'Я хожу на работу пешком.', 'instruction': 'Переведи свободно.',
           'correct_answer': 'I walk to work.', 'answer': 'I walk to work.', 'guided_key': 'walk-to-work',
           'guided_revision': 'catalog-v1'}
    exercise = exercise_for(raw)
    new_answer = 'I go to work on foot.'
    initial = lab_revision(exercise)
    student, headers = learner(app)
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
    version = editor_version(case)
    assert editor_preview(case, 'add', new_answer)['accepts_report']
    with pytest.raises(ValueError, match='Нет права'):
        editor_decide(case.id, student.id, version, 'add', new_answer)
    assert case.status == 'notified'
    assert not GrammarExerciseGrader().grade(exercise, new_answer)['is_correct']
    assert editor_decide(case.id, admin.user_id, version, 'add', new_answer) == 'Правка сохранена.'
    with pytest.raises(ValueError, match='Спор изменился'):
        editor_decide(case.id, admin.user_id, version, 'add', new_answer)
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
    _, classify, _, admin = services
    raw = {'type': 'multiple_choice', 'question': 'Выбери перевод слова «магазин».',
           'options': ['magazine', 'shop', 'newspaper'], 'correct_answer': 'magazine', 'answer': 'magazine',
           'explanation': 'An explanation for the original key.'}
    exercise = exercise_for(raw)
    case = report(exercise, 1)
    classify.side_effect = None
    classify.return_value = {'label': 'wrong_key', 'reason': 'Shop — магазин.'}
    assert worker.process_one() and worker.process_one()
    assert case.review['patch'] == {'correct_answer': 'shop'}
    version = editor_version(case)
    assert editor_preview(case, 'replace', 'shop')['accepts_report']
    if change_before_approval:
        exercise.content = {**raw, 'question': 'Выбери перевод слова «журнал».'}
        db.session.commit()
        with pytest.raises(ValueError, match='Задание изменилось'):
            editor_decide(case.id, admin.user_id, version, 'replace', 'shop')
        assert case.status == 'notified' and exercise.answer_review_override is None
        assert GrammarExerciseGrader().grade(exercise, 1)['explanation'] == raw['explanation']
    else:
        assert editor_decide(case.id, admin.user_id, version, 'replace', 'shop') == 'Правка сохранена.'
        assert case.status == 'applied' and exercise.content == raw
        assert effective_content(exercise)['answer'] == 'shop'
        assert exercise.to_dict()['correct_answer'] == 'shop'
        assert [GrammarExerciseGrader().grade(exercise, i)['is_correct'] for i in range(3)] == [False, True, False]
        assert GrammarExerciseGrader().grade(exercise, 0)['explanation'] == ''


def test_web_receipt_to_approved_answer_on_next_web_submission(services: tuple) -> None:
    app, _, _, admin = services
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
    assert editor_decide(case.id, admin.user_id, editor_version(case), 'add', alternate) == 'Правка сохранена.'
    assert GrammarAttempt.query.filter_by(exercise_id=exercise.id).count() == 1
    result = submit(client, headers, exercise, alternate)
    assert result['is_correct'] and 'dispute_token' not in result
    assert submit(client, headers, exercise, 'It is cold now.')['is_correct']


def test_matching_displays_selected_pairs_and_grader_issue_uses_manual_review(services: tuple) -> None:
    _, classify, send, admin = services
    exercise = exercise_for({'type': 'matching', 'instruction': 'Соедини пары.',
                             'pairs': [{'english': 'one', 'russian': 'один'}, {'english': 'two', 'russian': 'два'}]})
    case = report(exercise, {'0': '1', '1': '0'})
    classify.side_effect = None
    classify.return_value = {'label': 'grader_issue', 'reason': 'Разобрать сравнение.'}
    assert worker.process_one() and worker.process_one()
    assert 'one → два' in send.call_args.args[1] and 'two → два' in send.call_args.args[1]
    with pytest.raises(ValueError, match='проверка задания применить не может'):
        editor_preview(case, 'add', 'one → два')
    assert editor_decide(case.id, admin.user_id, editor_version(case), 'revise', '') == 'Спор сохранён на доработку.'
    assert case.status == 'revise'
    assert exercise.answer_review_override is None


@pytest.mark.parametrize('use_indices', [False, True])
def test_reorder_variant_requires_explicit_approval_and_keeps_earlier_answers(services: tuple, use_indices: bool) -> None:
    app, _, send, admin = services
    canonical = 'They saw the little bird near the lake'
    alternative = 'They saw the bird near the little lake'
    old_alternative = 'Near the lake they saw the little bird'
    words = canonical.split()
    indices = [0, 1, 2, 4, 5, 6, 3, 7]
    exercise = exercise_for({'type': 'reorder', 'words': words, 'correct_answer': canonical,
                             'alternatives': [old_alternative]})
    user, bearer = learner(app)
    client, headers = browser(app, user)
    answer = indices if use_indices else alternative
    rejection = submit(client, headers, exercise, answer)
    assert not rejection['is_correct']
    assert dispute(client, headers, exercise, rejection['dispute_token'], answer).json == {'success': True}
    case = AnswerDispute.query.filter_by(grammar_exercise_id=exercise.id).one()
    assert worker.process_one() and worker.process_one()
    assert case.review['patch'] == {'alternatives': [old_alternative, alternative]}
    assert send.call_args.kwargs['reply_markup']['inline_keyboard'][0][0]['url'].endswith(f'/admin/answer-disputes/{case.id}')
    assert not GrammarExerciseGrader().grade(exercise, answer)['is_correct']
    assert editor_preview(case, 'add', alternative)['accepts_report']
    assert editor_decide(case.id, admin.user_id, editor_version(case), 'add', alternative) == 'Правка сохранена.'
    for value in (canonical, old_alternative, alternative, indices):
        assert submit(client, headers, exercise, value)['is_correct']
    assert not submit(client, headers, exercise, 'They saw near the little bird the lake')['is_correct']
    repeated_tile = [0, 1, 2, 4, 5, 2, 3, 7]  # Same string, but the second 'the' tile was omitted.
    assert not GrammarExerciseGrader().grade(exercise, repeated_tile)['is_correct']
    native = app.test_client()
    activity = '/api/native/activities/grammar_topic'
    opened = native.post(activity + '/start', headers=bearer, json={
        'item_id': f'grammar_topic:{exercise.topic_id}', 'request_id': str(uuid4())})
    assert opened.status_code == 200, opened.json
    lesson = opened.json['lesson']
    assert lesson['questions'][0]['input'] == 'order'
    checked = native.post(activity + '/check', headers=bearer, json={
        'session_token': lesson['session_token'], 'question_id': '0', 'answer': json.dumps(list(map(str, indices)))})
    assert checked.json['feedback']['correct']


@pytest.mark.parametrize('answer', [
    'We found the note in my bag', 'We found a a note in my bag', 'We found a note my in bag',
    [0, 1, 2, 3, 3, 5], [False, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, -1], None, {},
])
def test_reorder_patch_requires_each_word_and_intact_phrase_tiles(answer: object) -> None:
    row = {'words': ['We', 'found', 'a', 'note', 'in my', 'bag'], 'correct_answer': 'We found a note in my bag'}
    exercise = SimpleNamespace(id=1, topic_id=1, exercise_type='reorder', content=row)
    assert proposed_lab_edit(exercise, row, answer, 'valid_variant') is None
    assert proposed_lab_edit(exercise, row, 'In my bag we found a note', 'valid_variant') == {
        'alternatives': ['In my bag we found a note']}


def test_reorder_replacement_accepts_new_key_and_rejects_original(services: tuple) -> None:
    _, _, _, admin = services
    original = 'She a letter found in the strange box'
    new_key = 'She found a letter in the strange box'
    exercise = exercise_for({'type': 'reorder', 'words': original.split(), 'correct_answer': original})
    case = report(exercise, new_key)
    preview = editor_preview(case, 'replace', new_key)
    assert preview['before'] == original and preview['after'] == new_key and preview['accepts_report']
    editor_decide(case.id, admin.user_id, editor_version(case), 'replace', new_key)
    grade = GrammarExerciseGrader().grade
    assert grade(exercise, new_key)['is_correct']
    assert not grade(exercise, original)['is_correct']
