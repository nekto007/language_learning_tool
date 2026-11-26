"""One learner dispute through the real grader, queue, owner decision and next check."""
import json
from collections.abc import Iterator
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.auth.models import User
from app.curriculum import answer_review as worker
from app.curriculum import answer_review_ai as ai
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.answer_review_editor import editor_decide, editor_preview, editor_version
from app.telegram import bot
from app.telegram.models import TelegramUser
from app.utils.db import db
from tests.answer_review_fixtures import telegram_admin
from tests.api.test_quiz_corrections import course, native_app
from tests.api.test_web_answer_disputes import browser


@pytest.fixture
def flow(course: tuple, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:  # noqa: F811
    user, _, lesson, client, awards = course
    app = client.application
    for key, value in {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'configured-model',
                       'TELEGRAM_BOT_TOKEN': 'test-token'}.items():
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
    with telegram_admin() as binding:
        try:
            yield SimpleNamespace(client=client, endpoint=endpoint, headers=headers, body=body, lesson=lesson,
                                  classify=classify, send=send, app=app, awards=awards,
                                  telegram_id=binding.telegram_id, admin_user_id=binding.user_id)
        finally:
            db.session.rollback()
            AnswerDispute.query.filter_by(lesson_id=lesson.id).delete()
            db.session.commit()


def open_case(f: SimpleNamespace) -> AnswerDispute:
    assert f.client.post(f.endpoint + '/dispute', json=f.body, headers=f.headers).json == {'success': True}
    return AnswerDispute.query.filter_by(lesson_id=f.lesson.id).one()


def test_admin_card_shows_server_source_and_learner_only_to_admins(flow: SimpleNamespace) -> None:
    from app.auth.models import User
    from app.curriculum.answer_disputes import AnswerDisputeReport

    case = open_case(flow)
    report = AnswerDisputeReport.query.filter_by(dispute_id=case.id).one()
    user = db.session.get(User, report.user_id)
    assert worker.process_one() and worker.process_one()
    card = flow.send.call_args.args[1]
    assert f'Курс · Веб · {flow.lesson.module.level.code} · Модуль 1' in card  # noqa: RUF001 -- Russian card label.
    assert f'Урок {case.lesson_id} «{flow.lesson.title}», вопрос 1' in card
    assert f'/curriculum/admin/lesson/{case.lesson_id}/view' in card
    assert f'{user.username} (ID {user.id})' in card
    assert user.email not in card
    evidence = flow.classify.call_args.args[0]
    assert set(evidence) == {'row', 'question', 'expected', 'submitted_answer'}
    assert user.username not in json.dumps(evidence)
    user.username = user.email
    db.session.flush()
    redacted, _ = worker._telegram_card(case)
    assert f'От ученика: ID {user.id}' in redacted and user.email not in redacted


def test_variant_survives_telegram_failure_and_requires_admin_click(flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert recipient == f.telegram_id and f.body['answer'] in text and 'I walk to work.' in text
    assert f.send.call_args.kwargs['reply_markup']['inline_keyboard'][0][0]['url'].endswith(f'/admin/answer-disputes/{case.id}')
    data = f'dispute:{case.id}:old-tag:approve'
    version = editor_version(case)
    with pytest.raises(ValueError, match='Спор изменился'):
        editor_decide(case.id, f.admin_user_id, 'older', 'add', f.body['answer'])
    assert case.status == 'notified'
    ack = Mock()
    monkeypatch.setattr(bot, '_answer_callback', ack)
    event = {'callback_query': {'id': 'cb', 'data': data, 'from': {'id': f.telegram_id}, 'message': {'chat': {'id': f.telegram_id}}}}
    # Even an old Telegram message opens the editor instead of changing content.
    f.send.side_effect = None
    for sender, chat in [(f.telegram_id, -f.telegram_id), (456, 456)]:
        bot.handle_update({'callback_query': {**event['callback_query'], 'from': {'id': sender},
                                             'message': {'chat': {'id': chat}}}})
        ack.assert_called_with('cb', 'Решение доступно администратору')
        assert f.send.call_count == 2
    ack.reset_mock()
    bot.handle_update(event)
    ack.assert_called_once_with('cb', 'Отправлена ссылка на спор')
    assert case.status == 'notified'
    assert f.send.call_args.kwargs['reply_markup']['inline_keyboard'][0][0]['url'].endswith(f'/admin/answer-disputes/{case.id}')
    assert editor_preview(case, 'add', f.body['answer'])['accepts_report']
    editor_decide(case.id, f.admin_user_id, version, 'add', f.body['answer'])
    assert case.status == 'applied' and case.review['decided_by_user_id'] == f.admin_user_id
    token = f.client.get(f.endpoint).json['lesson']['session_token']
    for value in [f.body['answer'], 'I walk to work.', 'I walk to my job.']:
        assert f.client.post(f.endpoint + '/check', json=f.body | {'session_token': token, 'answer': value},
                             headers=f.headers).json['feedback']['correct']
    assert not worker.process_one() and f.awards == []


@pytest.mark.parametrize(('label', 'action', 'state'), [
    ('wrong_key', 'replace', 'applied'), ('valid_variant', 'reject', 'dismissed'),
    ('valid_variant', 'revise', 'revise'), ('grader_issue', 'revise', 'revise'),
])
def test_decisions(flow: SimpleNamespace, label: str, action: str, state: str) -> None:
    f = flow
    case = open_case(f)
    before = deepcopy(f.lesson.content)
    f.classify.return_value['label'] = label
    assert worker.process_one() and worker.process_one()
    preview = editor_preview(case, action, f.body['answer'])
    editor_decide(case.id, f.admin_user_id, editor_version(case), preview['action'], preview['answer'])
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
def test_admin_can_replace_wrong_choice_key(flow: SimpleNamespace, field: str, original: str | int,
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
    assert editor_preview(case, 'replace', options[1])['accepts_report']
    assert editor_decide(case.id, f.admin_user_id, editor_version(case), 'replace', options[1]) == 'Правка сохранена.'
    token = f.client.get(f.endpoint).json['lesson']['session_token']
    for i in range(len(options)):
        feedback = f.client.post(f.endpoint + '/check', headers=f.headers,
                                 json=f.body | {'answer': str(i), 'session_token': token}).json['feedback']
        assert feedback['correct'] == (i == 1)


def test_edited_question_invalidates_a_card(flow: SimpleNamespace) -> None:
    f = flow
    case = open_case(f)
    assert worker.process_one() and worker.process_one()
    assert editor_preview(case, 'add', f.body['answer'])['accepts_report']
    version = editor_version(case)
    f.lesson.content = {'questions': [f.lesson.content['questions'][0] | {'instruction': 'Use walk.'}]}
    db.session.commit()
    with pytest.raises(ValueError, match='Задание изменилось'):
        editor_decide(case.id, f.admin_user_id, version, 'add', f.body['answer'])
    assert case.status == 'notified' and f.body['answer'] not in f.lesson.content['questions'][0]['alternative_answers']


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


def test_ready_review_waits_until_an_admin_links_telegram(
    flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = flow
    TelegramUser.query.filter_by(user_id=f.admin_user_id).delete()
    db.session.commit()
    case = open_case(f)
    assert worker.process_one() and case.status == 'ready'
    assert not worker.process_one()
    f.send.assert_not_called()

    db.session.add(TelegramUser(user_id=f.admin_user_id, telegram_id=f.telegram_id, is_active=True))
    db.session.commit()
    monkeypatch.setitem(f.app.config, 'OPENAI_API_KEY', '')
    assert worker.process_one() and case.status == 'notified'
    f.classify.assert_called_once()
    f.send.assert_called_once()
    assert f.send.call_args.args[0] == f.telegram_id


def test_partial_telegram_delivery_retries_only_failed_admin(flow: SimpleNamespace) -> None:
    f = flow
    case = open_case(f)
    with telegram_admin() as other:
        failed_id = other.telegram_id
        failed_attempts = 0

        def deliver(recipient: int, *args: object, **kwargs: object) -> bool:
            nonlocal failed_attempts
            if recipient == failed_id:
                failed_attempts += 1
                return failed_attempts > 1
            return True

        f.send.side_effect = deliver
        assert worker.process_one() and case.status == 'ready'
        assert worker.process_one() and case.next_attempt_at
        assert sorted(call.args[0] for call in f.send.call_args_list) == sorted((f.telegram_id, failed_id))
        assert not worker.process_one()
        case.next_attempt_at = None
        db.session.commit()
        assert worker.process_one() and case.status == 'notified'
        assert f.send.call_count == 3 and f.send.call_args.args[0] == failed_id
        assert not worker.process_one()
        f.classify.assert_called_once()
        version = editor_version(case)
        assert editor_decide(case.id, f.admin_user_id, version, 'add', f.body['answer']) == 'Правка сохранена.'
        with pytest.raises(ValueError, match='Спор изменился'):
            editor_decide(case.id, other.user_id, version, 'reject', '')
        assert case.status == 'applied' and case.review['decided_by_user_id'] == f.admin_user_id


@pytest.mark.parametrize('revocation', ['role', 'unlink', 'account_inactive', 'telegram_inactive'])
def test_revocation_rechecks_telegram_link_and_web_role(
    flow: SimpleNamespace, revocation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flask import g
    f = flow
    case = open_case(f)
    before = deepcopy(f.lesson.content)
    assert worker.process_one() and worker.process_one()
    assert case.status == 'notified'
    user = db.session.get(User, f.admin_user_id)
    user.onboarding_completed = True
    link = TelegramUser.query.filter_by(user_id=f.admin_user_id).one()
    if revocation == 'role':
        user.is_admin = False
    elif revocation == 'unlink':
        db.session.delete(link)
    elif revocation == 'account_inactive':
        user.active = False
    else:
        link.is_active = False
    db.session.commit()
    ack = Mock()
    monkeypatch.setattr(bot, '_answer_callback', ack)
    f.send.reset_mock()
    bot.handle_update({'callback_query': {'id': 'cb', 'data': f'dispute:{case.id}:from-old-card:approve',
                                         'from': {'id': f.telegram_id}, 'message': {'chat': {'id': f.telegram_id}}}})
    ack.assert_called_once_with('cb', 'Решение доступно администратору')
    f.send.assert_not_called()
    assert case.status == 'notified' and f.lesson.content == before

    client = f.app.test_client()
    with client.session_transaction() as session:
        session['_user_id'], session['_fresh'] = user.get_id(), True
    g.pop('_login_user', None)
    page = client.get(f'/admin/answer-disputes/{case.id}')
    if revocation in ('role', 'account_inactive'):
        assert page.status_code in (302, 403) and f.body['answer'] not in page.text
        with pytest.raises(ValueError, match='Нет права'):
            editor_decide(case.id, user.id, editor_version(case), 'add', f.body['answer'])
        assert 'decided_by_user_id' not in case.review
    else:
        assert page.status_code == 200 and f.body['answer'] in page.text
        assert editor_decide(case.id, user.id, editor_version(case), 'add', f.body['answer']) == 'Правка сохранена.'



@pytest.mark.parametrize('label', ['learner_error', 'insufficient_context'])
def test_negative_review_is_sent_once_and_can_be_reopened_for_review(flow: SimpleNamespace, label: str) -> None:
    f = flow
    case = open_case(f)
    f.classify.return_value['label'] = label
    assert worker.process_one() and case.status == 'ready'
    assert worker.process_one() and case.status == 'notified'
    assert case.review['patch'] is None
    assert open_case(f).id == case.id
    assert not worker.process_one()
    f.send.assert_called_once()
    f.classify.assert_called_once()
    assert 'Разбор: ' + case.review['reason'] in f.send.call_args.args[1]
    assert 'Открыть спор в админке' in str(f.send.call_args.kwargs['reply_markup'])
    reply = editor_decide(case.id, f.admin_user_id, editor_version(case), 'revise', '')
    assert reply == 'Спор сохранён на доработку.'
    assert case.status == 'revise'
    assert not worker.process_one()


def test_turning_off_pilot_closes_negative_review_without_delivery(
    flow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(flow.app.config, 'ANSWER_REVIEW_NOTIFY_ALL', False)
    case = open_case(flow)
    flow.classify.return_value['label'] = 'learner_error'
    assert worker.process_one() and case.status == 'closed'
    monkeypatch.setitem(flow.app.config, 'ANSWER_REVIEW_NOTIFY_ALL', True)
    assert not worker.process_one()
    flow.send.assert_not_called()


def test_contact_in_answer_stays_local(flow: SimpleNamespace) -> None:
    f = flow
    f.body['answer'] = 'user@example.com'
    case = open_case(f)
    assert worker.process_one() and case.status == 'ready'
    status = f.app.test_cli_runner().invoke(args=['answer-review-status'])
    assert status.exit_code == 0
    assert case.id in json.loads(status.output)['manual_ids']
    assert worker.process_one() and case.status == 'manual'
    f.classify.assert_not_called()
    f.send.assert_called_once()
    text = f.send.call_args.args[1]
    assert f'Спор {case.id}' in text and f.body['answer'] not in text
    assert f.send.call_args.kwargs['reply_markup'] is None


def test_changed_source_sends_reference_without_grading_or_quietly_reopening_case(flow: SimpleNamespace) -> None:
    case = open_case(flow)
    flow.lesson.content = {'questions': [flow.lesson.content['questions'][0] | {'instruction': 'Use walk.'}]}
    db.session.commit()
    assert worker.process_one() and case.status == 'ready'
    assert worker.process_one() and case.status == 'stale'
    assert not worker.process_one()
    flow.classify.assert_not_called()
    flow.send.assert_called_once()
    text = flow.send.call_args.args[1]
    assert 'Версия задания изменилась' in text and flow.body['answer'] not in text
    assert flow.send.call_args.kwargs['reply_markup'] is None


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
