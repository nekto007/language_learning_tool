"""Final-test grammar warmups use their exact plan item and linked topic."""

from typing import Any
from uuid import uuid4

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.daily_plan.plan_builder import _grammar_prep_item_dict
from app.daily_plan.snapshot import _is_item_completed
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic
from app.study.models import NativeLearningRun
from app.utils.db import db


@pytest.fixture
def warmup(
    app: Flask, client: FlaskClient, db_session: Any, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    key = uuid4().hex[:12]
    user = User(username='warmup_' + key, email=key + '@example.invalid', active=True)
    user.set_password(uuid4().hex)
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Synthetic A1', order=1)
        db_session.add(level)
    distractor = GrammarTopic(
        slug='distractor-' + key, title='Unrelated topic', title_ru='Другая тема', level='A1',
        content={'introduction': 'An unrelated rule.'},
    )
    target = GrammarTopic(
        slug='demonstratives-' + key, title='Synthetic demonstratives',
        title_ru='Синтетические указательные местоимения', level='A1',
        content={'introduction': 'This: one near object. That: one distant object.'},
    )
    db_session.add_all([user, distractor, target])
    db_session.flush()
    module = Module(level_id=level.id, number=3, title='Synthetic clothes')
    db_session.add(module)
    db_session.flush()
    grammar = Lessons(
        module_id=module.id, number=4, type='grammar', title='Completed synthetic rule',
        grammar_topic_id=target.id,
        content={'description': 'This is a shirt. That is a coat.', 'exercises': []},
    )
    other_grammar = Lessons(
        module_id=module.id, number=9, type='grammar', title='Other rule',
        grammar_topic_id=distractor.id, content={'description': 'Another rule.'},
    )
    final = Lessons(
        module_id=module.id, number=18, type='final_test', title='Synthetic final',
        content={'questions': [
            {'type': 'fill_blank', 'question': 'One shirt near me: ___.', 'correct_answer': 'this'},
        ]},
    )
    selected = GrammarExercise(
        topic_id=target.id, exercise_type='fill_blank',
        content={'question': '___ is one shirt near me.', 'correct_answer': 'This'},
    )
    unrelated = GrammarExercise(
        topic_id=distractor.id, exercise_type='fill_blank',
        content={'question': 'I ___ here.', 'correct_answer': 'am'},
    )
    db_session.add_all([grammar, other_grammar, final, selected, unrelated])
    db_session.flush()
    db_session.add(LessonProgress(
        user_id=user.id, lesson_id=grammar.id, status='completed', score=100,
    ))
    db_session.commit()
    item = _grammar_prep_item_dict(db, final)
    assert item['id'] == f'grammar_review:module:{module.id}:topic:{target.id}:pre_ft'
    assert item['data']['topic_id'] == target.id and item['lesson_type'] is None
    plan = {
        'mode': 'unified',
        'required': [
            {'id': 'srs:global', 'kind': 'srs', 'completed': True},
            {**item, 'completed': False},
            {'id': f'curriculum:{final.id}', 'kind': 'curriculum', 'completed': False,
             'data': {'lesson_id': final.id}},
        ],
        'optional': [], 'setup': [],
    }
    monkeypatch.setattr('app.daily_plan.service.get_daily_plan_unified', lambda *args, **kwargs: plan)
    token = create_access_token(
        identity=str(user.id), additional_claims={'auth_version': user.auth_version()},
    )
    return {
        'client': client, 'headers': {'Authorization': 'Bearer ' + token}, 'plan': plan,
        'item': item, 'user': user, 'target': target, 'distractor': distractor,
        'selected': selected, 'unrelated': unrelated, 'grammar': grammar, 'final': final,
    }


def start(warmup: dict[str, Any], body: dict[str, str]) -> Any:
    return warmup['client'].post(
        '/api/native/activities/grammar_review/start', headers=warmup['headers'], json=body,
    )


def assert_final_unfinished(warmup: dict[str, Any]) -> None:
    assert LessonAttempt.query.filter_by(
        user_id=warmup['user'].id, lesson_id=warmup['final'].id,
    ).count() == 0
    progress = LessonProgress.query.filter_by(
        user_id=warmup['user'].id, lesson_id=warmup['final'].id,
    ).first()
    assert progress is None or progress.status != 'completed'
    assert not warmup['plan']['required'][-1]['completed']


def test_pre_final_grammar_start_check_submit_and_receipt_retry(warmup: dict[str, Any]) -> None:
    body = {'item_id': warmup['item']['id'], 'request_id': str(uuid4())}
    response = start(warmup, body)
    assert response.status_code == 200, response.json
    lesson = response.json['lesson']
    assert lesson['type'] == 'grammar' and lesson['title'] == warmup['target'].title_ru
    assert len(lesson['questions']) == 1
    assert lesson['questions'][0]['prompt'] == warmup['selected'].content['question']
    assert lesson['questions'][0]['input'] == 'text'
    run = NativeLearningRun.query.filter_by(
        user_id=warmup['user'].id, request_id=body['request_id'],
    ).one()
    assert run.payload['source']['topic_id'] == warmup['target'].id
    assert run.payload['source']['exercise_ids'] == [warmup['selected'].id]
    retry = start(warmup, body)
    assert retry.status_code == 200 and retry.json['lesson']['id'] == lesson['id']
    assert NativeLearningRun.query.filter_by(user_id=warmup['user'].id).count() == 1
    assert GrammarAttempt.query.filter_by(user_id=warmup['user'].id).count() == 0
    checked = warmup['client'].post(
        '/api/native/activities/grammar_review/check', headers=warmup['headers'],
        json={'session_token': lesson['session_token'], 'question_id': '0', 'answer': 'This'},
    )
    assert checked.status_code == 200 and checked.json['feedback']['correct']
    assert GrammarAttempt.query.filter_by(user_id=warmup['user'].id).count() == 0
    assert not _is_item_completed(warmup['user'].id, warmup['item'], db)
    assert_final_unfinished(warmup)
    submitted = {'session_token': lesson['session_token'], 'answers': {'0': 'This'}}
    result = warmup['client'].post(
        '/api/native/activities/grammar_review/submit', headers=warmup['headers'], json=submitted,
    )
    assert result.status_code == 200 and result.json['completed'] and result.json['score'] == 100
    assert GrammarAttempt.query.filter_by(
        user_id=warmup['user'].id, exercise_id=warmup['selected'].id,
    ).count() == 1
    assert GrammarAttempt.query.filter_by(
        user_id=warmup['user'].id, exercise_id=warmup['unrelated'].id,
    ).count() == 0
    # Once the plan moves to the final, a lost submission confirmation remains readable.
    prep = warmup['plan']['required'][1]
    prep['completed'] = _is_item_completed(warmup['user'].id, prep, db)
    assert prep['completed']
    repeated = warmup['client'].post(
        '/api/native/activities/grammar_review/submit', headers=warmup['headers'], json=submitted,
    )
    assert repeated.status_code == 200 and repeated.json == result.json
    assert GrammarAttempt.query.filter_by(user_id=warmup['user'].id).count() == 1
    assert_final_unfinished(warmup)
    assert LessonProgress.query.filter_by(
        user_id=warmup['user'].id, lesson_id=warmup['grammar'].id,
    ).one().status == 'completed'


def test_pre_final_grammar_cannot_bypass_previous_step(warmup: dict[str, Any]) -> None:
    warmup['plan']['required'][0]['completed'] = False
    response = start(warmup, {'item_id': warmup['item']['id'], 'request_id': str(uuid4())})
    assert response.status_code == 403 and response.json['error'] == 'lesson_locked'
    assert NativeLearningRun.query.filter_by(user_id=warmup['user'].id).count() == 0
    assert_final_unfinished(warmup)


def test_pre_final_grammar_cannot_substitute_another_topic(warmup: dict[str, Any]) -> None:
    forged = warmup['item']['id'].replace(
        f":topic:{warmup['target'].id}:", f":topic:{warmup['distractor'].id}:",
    )
    response = start(warmup, {'item_id': forged, 'request_id': str(uuid4())})
    assert response.status_code == 403 and response.json['error'] == 'lesson_locked'
    assert NativeLearningRun.query.filter_by(user_id=warmup['user'].id).count() == 0
    assert_final_unfinished(warmup)
