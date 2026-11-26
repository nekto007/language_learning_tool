"""Automatic terminal marks preserve authored order and both answer encodings."""
import json
from typing import Any

import pytest
from bs4 import BeautifulSoup
from flask_jwt_extended import create_access_token

from app.api.native_lessons import _signer
from app.curriculum.order_punctuation import automatic_order_terminal
from app.utils.db import db
from tests.api.test_course_receipt_expiry import receipt


@pytest.mark.parametrize('mark', ['.', '!', '?'])
@pytest.mark.parametrize('transport', ['web', 'native'])
def test_order_check_and_submit_accept_new_and_preexisting_answer(
    receipt: dict[str, Any], mark: str, transport: str,  # noqa: F811 -- shared fixture.
) -> None:
    lesson = receipt['lesson']
    lesson.type = 'reading'
    lesson.content = {'text': 'They found a map.', 'exercises': [
        {'type': 'ordering', 'words': ['They', 'found', 'a', 'map', mark], 'correct': 'They found a map' + mark},
    ]}
    db.session.commit()
    client = receipt['client']
    user = receipt['user']
    if transport == 'web':
        prefix, headers = receipt['endpoint'], receipt['headers']
    else:
        prefix = f'/api/native/lessons/{lesson.id}'
        bearer = create_access_token(identity=str(user.id), additional_claims={'auth_version': user.auth_version()})
        headers = {'Authorization': 'Bearer ' + bearer}
    opened = client.get(prefix, headers=headers)
    assert opened.status_code == 200, opened.json
    doc = opened.json['lesson']
    q, = doc['questions']
    assert q['order_terminal'] == {'value': '4', 'label': mark}
    assert {o['value']: o['label'] for o in q['options']} == {'0': 'They', '1': 'found', '2': 'a', '3': 'map'}
    token = doc['session_token']
    assert _signer().loads(token)['projection_version'] == 2
    short = json.dumps(['0', '1', '2', '3'])
    old = json.dumps(['0', '1', '2', '3', '4'])
    wrong = json.dumps(['1', '0', '2', '3'])
    for answer, echo, truth in (
        (short, 'They found a map', True),
        (old, 'They found a map ' + mark, True),
        (wrong, 'found They a map', False),
    ):
        result = client.post(prefix + '/check', headers=headers, json={
            'session_token': token, 'question_id': '0', 'answer': answer,
        })
        assert result.status_code == 200, result.json
        f = result.json['feedback']
        assert f['correct'] is truth and f['answer'] == echo
        assert f['answer_display'] == echo.removesuffix(' ' + mark) + mark
        assert f['expected'] == 'They found a map' + mark
    incomplete = client.post(prefix + '/check', headers=headers, json={
        'session_token': token, 'question_id': '0', 'answer': '["0","1","4"]',
    })
    assert incomplete.status_code == 400
    body = {'session_token': token, 'answers': {'0': old if transport == 'native' else short}}
    first = client.post(prefix + '/submit', headers=headers, json=body)
    assert first.status_code == 200 and first.json['score'] == 100
    assert first.json['feedback'][0]['answer_display'] == 'They found a map' + mark
    assert client.post(prefix + '/submit', headers=headers, json=body).json == first.json


def test_ambiguous_and_explicit_punctuation_keeps_tiles() -> None:
    base = {'type': 'ordering', 'words': ['Read', 'it', '.'], 'correct': 'Read it.'}
    assert automatic_order_terminal(base) == (2, '.')
    assert automatic_order_terminal(base | {'correct': 'Read it'}) == (2, '.')
    assert automatic_order_terminal(base | {'words': ['Read', '.', 'it']}) == (1, '.')
    for fields in [
        {'correct': 'Read it!'}, {'correct': 'It fits.'}, {'words': ['Read', '.', 'it', '!']},
        {'words': ['Dr.', 'Fox', '.']}, {'instruction': 'Choose the punctuation.'},
        {'punctuation_required': True}, {'type': 'fill_blank'},
    ]:
        assert automatic_order_terminal(base | fields) is None


def test_decimal_and_abbreviations_keep_original_labels_and_wire_ids(
    receipt: dict[str, Any],  # noqa: F811 -- shared fixture.
) -> None:
    lesson = receipt['lesson']
    lesson.type = 'reading'
    lesson.content = {'text': 'Mr. Fox needs help.', 'exercises': [
        {'type': 'ordering', 'words': ['Dr.', 'Fox', '!', 'needs', '3.5', 'litres'],
         'correct': 'Dr. Fox needs 3.5 litres!'},
    ]}
    db.session.commit()
    web, headers, endpoint = receipt['client'], receipt['headers'], receipt['endpoint']
    doc = web.get(endpoint).json['lesson']
    question, = doc['questions']
    assert question['order_terminal'] == {'value': '2', 'label': '!'}
    assert {o['value']: o['label'] for o in question['options']} == {
        '0': 'Dr.', '1': 'Fox', '3': 'needs', '4': '3.5', '5': 'litres',
    }
    response = web.post(endpoint + '/check', headers=headers, json={
        'session_token': doc['session_token'], 'question_id': '0', 'answer': '["0","1","3","4","5"]',
    })
    assert response.status_code == 200 and response.json['feedback']['correct']
    assert response.json['feedback']['answer_display'] == 'Dr. Fox needs 3.5 litres!'
    assert automatic_order_terminal({
        'type': 'ordering', 'words': ['Mr.', 'Fox', '?'], 'correct': 'Mr. Fox?',
    }) == (2, '?')


def test_legacy_reading_renderer_hides_terminal_and_old_check_and_submit_work(
    receipt: dict[str, Any],  # noqa: F811 -- shared fixture.
) -> None:
    lesson = receipt['lesson']
    lesson.type = 'reading'
    lesson.content = {'text': 'They found a map.', 'exercises': [
        {'type': 'ordering', 'words': ['They', 'found', 'a', 'map', '.'], 'correct': 'They found a map.'},
    ]}
    db.session.commit()
    web, headers = receipt['client'], receipt['headers']
    page = web.get(f'/learn/{lesson.id}/?ui=legacy')
    assert page.status_code == 200
    doc = BeautifulSoup(page.text, 'html.parser')
    assert doc.select_one('.sentence-display[data-order-terminal="."]')
    assert {tile['data-word'] for tile in doc.select('.word-button[data-word]')} == {'They', 'found', 'a', 'map'}
    prefix = f'/curriculum/api/lesson/{lesson.id}'
    for answer, correct in [('They found a map.', True), ('They found a map .', True), ('found They a map', False)]:
        r = web.post(prefix + '/check-item', headers=headers, json={'index': 0, 'answer': answer})
        assert r.status_code == 200 and r.json['correct'] is correct
    response = web.post(prefix + '/submit', headers=headers, json={
        'answers': {'0': 'They found a map .'}, 'lesson_type': 'reading',
    })
    assert response.status_code == 200 and response.json['score'] == 100
