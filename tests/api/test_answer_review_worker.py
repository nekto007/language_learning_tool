"""One learner dispute through the real grader, queue, owner decision and next check."""
from collections.abc import Iterator
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.curriculum import answer_review as worker
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute
from app.telegram import bot
from app.utils.db import db
from tests.api.test_quiz_corrections import course, native_app  # noqa: F401
from tests.api.test_web_answer_disputes import browser


@pytest.fixture
def flow(course: tuple, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:  # noqa: F811
    user, _, lesson, client, awards = course
    app = client.application
    for key, value in {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'configured-model',
                       'TELEGRAM_BOT_TOKEN': 'test-token', 'ANSWER_REVIEW_OWNER_TELEGRAM_ID': '123'}.items():
        monkeypatch.setitem(app.config, key, value)
    row = {'type': 'translation', 'question': 'Переведи свободно: Я хожу на работу пешком.',
           'correct_answer': 'I walk to work.', 'alternative_answers': ['I walk to my job.']}
    lesson.type = 'quiz'
    lesson.content = {'questions': [row]}
    db.session.commit()
    client, endpoint, headers, token = browser(app, user, lesson)
    body = {'session_token': token, 'question_id': '0', 'answer': 'I go to work on foot.'}
    classify = Mock(return_value={'label': 'valid_variant', 'reason': 'Смысл сохранён.', 'model': 'configured-model'})
    send = Mock(return_value=True)
    monkeypatch.setattr(ai, 'classify', classify)
    monkeypatch.setattr(bot, 'send_message', send)
    yield SimpleNamespace(client=client, endpoint=endpoint, headers=headers, body=body, lesson=lesson,
                          classify=classify, send=send, app=app, awards=awards)
    AnswerDispute.query.filter_by(lesson_id=lesson.id).delete()
    db.session.commit()


def open_case(f: SimpleNamespace) -> AnswerDispute:
    assert f.client.post(f.endpoint + '/dispute', json=f.body, headers=f.headers).json == {'success': True}
    return AnswerDispute.query.filter_by(lesson_id=f.lesson.id).one()


def test_variant_survives_telegram_failure_and_requires_owner_click(flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    f = flow
    case = open_case(f)
    open_case(f)
    f.send.side_effect = [False, True]
    assert worker.process_one() and case.status == 'ready'
    assert case.review['patch'] == {'alternative_answers': ['I walk to my job.', f.body['answer']]}
    assert worker.process_one() and case.status == 'ready' and case.next_attempt_at
    assert not worker.process_one()
    case.next_attempt_at = None
    db.session.commit()
    assert worker.process_one() and case.status == 'notified'
    assert f.classify.call_count == 1
    assert f.classify.call_args.kwargs == {'key': 'test-key', 'model': 'configured-model'}
    assert f.client.post(f.endpoint + '/check', json=f.body, headers=f.headers).json['feedback']['correct'] is False
    recipient, text = f.send.call_args.args
    assert recipient == 123 and f.body['answer'] in text and 'I walk to work.' in text
    data = f.send.call_args.kwargs['reply_markup']['inline_keyboard'][0][0]['callback_data']
    assert len(data.encode()) <= 64
    tag = worker.decision_tag(case)
    assert worker.decide(case.id, tag, 'approve', 456, 456) == 'Решение доступно владельцу'
    assert worker.decide(case.id, tag, 'approve', 123, -123) == 'Решение доступно владельцу'
    assert worker.decide(case.id, 'older', 'approve', 123, 123) == 'Карточка уже обработана или устарела'
    assert case.status == 'notified'
    ack = Mock()
    monkeypatch.setattr(bot, '_answer_callback', ack)
    event = {'callback_query': {'id': 'cb', 'data': data, 'from': {'id': 123}, 'message': {'chat': {'id': 123}}}}
    from sqlalchemy.exc import SQLAlchemyError
    with monkeypatch.context() as patch:
        patch.setattr(db.session, 'commit', Mock(side_effect=SQLAlchemyError('test failure')))
        bot.handle_update(event)
    assert case.status == 'notified' and f.body['answer'] not in f.lesson.content['questions'][0]['alternative_answers']
    ack.assert_called_once_with('cb', 'Не удалось сохранить решение. Нажмите ещё раз.')
    ack.reset_mock()
    bot.handle_update(event)
    assert case.status == 'applied' and case.review['decided_by'] == 123
    ack.assert_called_once_with('cb', 'Правка применена')
    bot.handle_update(event)
    assert 'уже обработана' in ack.call_args.args[1]
    token = f.client.get(f.endpoint).json['lesson']['session_token']
    for value in [f.body['answer'], 'I walk to work.', 'I walk to my job.']:
        assert f.client.post(f.endpoint + '/check', json=f.body | {'session_token': token, 'answer': value},
                             headers=f.headers).json['feedback']['correct']
    assert not worker.process_one() and f.awards == []


@pytest.mark.parametrize(('label', 'action', 'state'), [
    ('wrong_key', 'approve', 'applied'), ('valid_variant', 'reject', 'dismissed'),
    ('valid_variant', 'revise', 'revise'), ('grader_issue', 'approve', 'manual'),
])
def test_decisions(flow: SimpleNamespace, label: str, action: str, state: str) -> None:
    f = flow
    case = open_case(f)
    before = deepcopy(f.lesson.content)
    f.classify.return_value['label'] = label
    assert worker.process_one() and worker.process_one()
    worker.decide(case.id, worker.decision_tag(case), action, 123, 123)
    db.session.refresh(f.lesson)
    assert case.status == state
    if state == 'applied':
        assert f.lesson.content['questions'][0]['correct_answer'] == f.body['answer']
    else:
        assert f.lesson.content == before
    assert f.awards == []


@pytest.mark.parametrize(('field', 'original', 'options', 'replacement'), [
    ('correct_answer', 'magazine', ['magazine', 'shop', 'newspaper'], 'shop'),
    ('correct_index', 0, ['magazine', 'shop'], 1),
    ('correct', '0', ['magazine', 'shop'], '1'),
    ('correct_answer', '2018', ['2018', '2019'], '2019'),
])
def test_owner_can_replace_wrong_choice_key(flow: SimpleNamespace, field: str, original: str | int,
                                           options: list[str], replacement: str | int) -> None:
    f = flow
    f.lesson.content = {'questions': [{'type': 'multiple_choice', 'question': 'Выбери ответ.',
                                        'options': options, field: original}]}
    db.session.commit()
    f.body.update(answer='1', session_token=f.client.get(f.endpoint).json['lesson']['session_token'])
    case = open_case(f)
    f.classify.return_value['label'] = 'wrong_key'
    assert worker.process_one() and case.review['patch'] == {field: replacement}
    assert worker.process_one() and case.status == 'notified'
    assert worker.decide(case.id, worker.decision_tag(case), 'approve', 123, 123) == 'Правка применена'
    token = f.client.get(f.endpoint).json['lesson']['session_token']
    for i in range(len(options)):
        feedback = f.client.post(f.endpoint + '/check', headers=f.headers,
                                 json=f.body | {'answer': str(i), 'session_token': token}).json['feedback']
        assert feedback['correct'] == (i == 1)


def test_edited_question_invalidates_a_card(flow: SimpleNamespace) -> None:
    f = flow
    case = open_case(f)
    assert worker.process_one() and worker.process_one()
    f.lesson.content = {'questions': [f.lesson.content['questions'][0] | {'instruction': 'Use walk.'}]}
    db.session.commit()
    assert worker.decide(case.id, worker.decision_tag(case), 'approve', 123, 123) == 'Задание изменилось'
    assert case.status == 'stale' and f.body['answer'] not in f.lesson.content['questions'][0]['alternative_answers']


def test_service_failure_and_missing_config_preserve_dispute(flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    f = flow
    case = open_case(f)
    for name in ['OPENAI_MODEL', 'OPENAI_API_KEY']:
        with monkeypatch.context() as patch:
            patch.setitem(f.app.config, name, '')
            assert not worker.process_one()
    f.classify.assert_not_called()
    f.classify.side_effect = ai.ReviewServiceError('OpenAI HTTP 403')
    assert worker.process_one()
    assert case.status == 'pending' and case.next_attempt_at and not worker.process_one()
    f.send.assert_not_called()


def test_model_review_can_wait_for_telegram_configuration(flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    f = flow
    case = open_case(f)
    with monkeypatch.context() as patch:
        patch.setitem(f.app.config, 'ANSWER_REVIEW_OWNER_TELEGRAM_ID', '')
        assert worker.process_one() and case.status == 'ready'
        assert not worker.process_one()
    f.send.assert_not_called()
    monkeypatch.setitem(f.app.config, 'OPENAI_API_KEY', '')
    assert worker.process_one() and case.status == 'notified'
    f.classify.assert_called_once()
    f.send.assert_called_once()


@pytest.mark.parametrize('label', ['learner_error', 'insufficient_context'])
def test_reviewed_negative_is_reused(flow: SimpleNamespace, label: str) -> None:
    f = flow
    case = open_case(f)
    f.classify.return_value['label'] = label
    assert worker.process_one() and case.status == 'closed'
    assert open_case(f).id == case.id
    assert not worker.process_one()
    f.send.assert_not_called()
    f.classify.assert_called_once()


def test_contact_in_answer_stays_local(flow: SimpleNamespace) -> None:
    f = flow
    f.body['answer'] = 'user@example.com'
    case = open_case(f)
    assert worker.process_one() and case.status == 'manual'
    f.classify.assert_not_called()
    f.send.assert_not_called()


def test_responses_contract_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': '{"label":"grader_issue","reason":"Нужно проверить сравнение."}'},
    ]}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(ai.requests, 'post', post)
    result = ai.classify({'submitted_answer': 'example'}, key='test-key', model='configured-model')
    assert result['label'] == 'grader_issue' and result['model'] == 'configured-model'
    payload = post.call_args.kwargs['json']
    assert payload['model'] == 'configured-model' and payload['store'] is False
    assert payload['text']['format']['strict'] is True
    response.status_code = 404
    with pytest.raises(ai.ReviewServiceError, match='HTTP 404'):
        ai.classify({}, key='test-key', model='configured-model')
    response.status_code = 200
    response.json.return_value['output'][0]['content'][0] = {'type': 'refusal', 'refusal': 'Unavailable.'}
    with pytest.raises(ai.ReviewServiceError, match='no usable review'):
        ai.classify({}, key='test-key', model='configured-model')


def test_telegram_delivery_requires_bot_ack(flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(ok=True, status_code=200)
    post = Mock(return_value=response)
    monkeypatch.setattr(bot.requests, 'post', post)
    response.json.return_value = {'ok': False}
    assert not bot._send_message(123, 'example', parse_mode=None)
    assert 'parse_mode' not in post.call_args.kwargs['json']
    response.json.return_value = {'ok': True, 'result': {'message_id': 1234}}
    assert bot._send_message(123, 'example', parse_mode=None)
