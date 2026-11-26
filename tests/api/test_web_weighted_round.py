"""Web round checks use real signed documents and stored first-pass evidence."""

from typing import Any

import pytest
from flask import g

from app.achievements.models import StreakEvent, UserStatistics
from app.api.native_lessons import _digest
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.dispute_credit import credit_approved_reports
from app.curriculum.models import LessonAttempt, LessonProgress
from app.curriculum.web_practice_round import WebPracticeRound, weighted_score
from app.daily_plan.items.curriculum import _lesson_meets_passing
from app.daily_plan.linear.models import QuizErrorLog
from app.utils.db import db
from tests.api.test_course_receipt_expiry import receipt, sign_in


@pytest.fixture
def web_round(receipt: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    lesson = receipt['lesson']
    lesson.content = {'questions': [
        {'type': 'multiple_choice', 'question': f'Choose the weather word {i}.', 'options': ['rain', 'tea'], 'correct': 0}
        for i in range(7)
    ]}
    db.session.commit()
    receipt['web'] = f'/curriculum/api/lesson/{lesson.id}/practice'
    return receipt


def document(r: dict[str, Any], suffix: str = '') -> dict:
    g.pop('_login_user', None)
    response = r['client'].get(r['web'] + '?mode=course&weighted=1' + suffix)
    assert response.status_code == 200, response.json
    return response.json['lesson']


def send(r: dict[str, Any], doc: dict, step: int, question_id: str, answer: str) -> Any:
    g.pop('_login_user', None)
    return r['client'].post(r['web'] + '/round-check', headers=r['headers'], json={
        'session_token': doc['session_token'], 'step': step, 'question_id': question_id, 'answer': answer,
    })


def test_weights_are_floored_after_exact_summation() -> None:
    assert weighted_score({str(i): 1 if i < 3 else 2 for i in range(7)}, 7) == 88
    for rank, score in [(1, 100), (2, 80), (3, 64), (8, 20)]:
        assert weighted_score({str(i): rank for i in range(7)}, 7) == score


def test_requeue_reload_receipt_and_weighted_progress(web_round: dict[str, Any]) -> None:
    r = web_round
    doc = document(r)
    assert doc['web_round']['phase'] == 'first'
    for step in range(7):
        outcome = send(r, doc, step, str(step), '0' if step < 3 else '1')
        assert outcome.status_code == 200, outcome.json
    assert outcome.json['round']['question_id'] == '3'
    assert outcome.json['round']['phase'] == 'correction'
    assert outcome.json['round']['result'] is None
    assert LessonAttempt.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id).count() == 0

    failure = send(r, doc, 7, '3', '1')
    retry = send(r, doc, 7, '3', '1')
    assert failure.json == retry.json
    assert failure.json['round']['question_id'] == '4'
    assert send(r, doc, 7, '3', '0').status_code == 409
    assert send(r, doc, 8, '3', '0').status_code == 409
    recovered = document(r)
    assert recovered['web_round'] == failure.json['round']
    for step, qid in enumerate(['4', '5', '6', '3'], start=8):
        outcome = send(r, recovered, step, qid, '0')
        assert outcome.status_code == 200, outcome.json
    result = outcome.json['round']['result']
    assert result['score'] == 86
    assert result['web_weighted']['first_score'] == 42.86
    assert result['web_weighted']['first_correct_count'] == 3
    assert result['feedback'][3]['web_resolution'] == {'rank': 3, 'answer': 'rain'}
    assert result['feedback'][4]['web_resolution'] == {'rank': 2, 'answer': 'rain'}
    assert result['completed'] is True
    assert send(r, recovered, 11, '3', '0').json == outcome.json
    progress = LessonProgress.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id).one()
    attempt = LessonAttempt.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id).one()
    assert (progress.last_score, progress.best_score, attempt.score, progress.status) == (86, 86, 86, 'completed')
    assert QuizErrorLog.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id, resolved_at=None).count() == 0
    assert UserStatistics.query.filter_by(user_id=r['user'].id).one().total_xp == 9
    assert document(r, '&round=' + recovered['web_round']['id'])['web_round']['result'] == result


@pytest.mark.parametrize(('failures', 'score'), [(0, 100), (1, 80), (2, 64), (4, 40)])
def test_completion_can_be_below_old_threshold(
    web_round: dict[str, Any], failures: int, score: int,
) -> None:
    r = web_round
    doc = document(r)
    for attempt in range(failures + 1):
        for qid in range(7):
            result = send(r, doc, attempt * 7 + qid, str(qid), '0' if attempt == failures else '1')
            assert result.status_code == 200, result.json
    assert result.json['round']['result']['score'] == score
    progress = LessonProgress.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id).one()
    assert progress.status == 'completed' and progress.last_score == score
    assert _lesson_meets_passing(r['lesson'], progress.last_score, progress.data)


def test_dispute_promotes_exact_question_without_losing_other_weights(web_round: dict[str, Any]) -> None:
    r = web_round
    doc = document(r)
    for step in range(7):
        assert send(r, doc, step, str(step), '1' if step in (1, 2) else '0').status_code == 200
    report = r['client'].post(r['web'] + '/dispute?weighted=1', headers=r['headers'], json={
        'session_token': doc['session_token'], 'question_id': '1', 'answer': '1',
    })
    assert report.status_code == 200, report.json
    assert send(r, doc, 7, '1', '0').status_code == 200
    assert send(r, doc, 8, '2', '0').json['round']['result']['score'] == 94
    previous = _digest(r['lesson'].content)
    content = dict(r['lesson'].content)
    content['questions'] = [dict(q) for q in content['questions']]
    content['questions'][1]['correct'] = 1
    r['lesson'].content = content
    case = AnswerDispute.query.filter_by(lesson_id=r['lesson'].id).one()
    case.status = 'applied'
    case.review = {'previous_revision': previous, 'updated_revision': _digest(content), 'shown_answer': 'tea'}
    db.session.flush()
    assert credit_approved_reports(case) == {r['user'].id}
    db.session.commit()
    row = WebPracticeRound.query.filter_by(lesson_id=r['lesson'].id).one()
    assert row.state['solved']['1'] == 1 and row.state['solved']['2'] == 2
    assert row.state['result']['score'] == 97
    assert row.state['result']['web_weighted']['first_correct_count'] == 6
    assert LessonAttempt.query.filter_by(lesson_id=r['lesson'].id).one().score == 97
    progress = LessonProgress.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id).one()
    assert progress.last_score == 97


def test_old_session_and_exam_keep_old_transport(web_round: dict[str, Any], test_user: Any) -> None:
    r = web_round
    original = r['client'].get(r['web'] + '?mode=course').json['lesson']
    assert 'web_round' not in original
    new = document(r)
    payload = {'session_token': new['session_token'], 'question_id': '0', 'answer': '0'}
    assert r['client'].post(r['web'] + '/check', json=payload, headers=r['headers']).status_code == 409
    assert r['client'].post(r['web'] + '/check', json=payload | {'session_token': original['session_token']},
                            headers=r['headers']).status_code == 200
    assert r['client'].post(r['web'] + '/round-check', json=payload | {'step': 0}).status_code == 400
    outsider = r['app'].test_client()
    headers = sign_in(outsider, r['app'], test_user)
    assert outsider.post(r['web'] + '/round-check', json=payload | {'step': 0}, headers=headers).status_code == 403
    g.pop('_login_user', None)
    r['lesson'].type = 'final_test'
    db.session.commit()
    exam = document(r)
    assert not exam['immediate_feedback'] and 'web_round' not in exam
    assert all('expected' not in q and 'correct_answer' not in q for q in exam['questions'])


def test_last_pending_dispute_frees_finish_and_writes_one_attempt(web_round: dict[str, Any]) -> None:
    r = web_round
    doc = document(r)
    for step in range(7):
        assert send(r, doc, step, str(step), '1' if step == 6 else '0').status_code == 200
    report = r['client'].post(r['web'] + '/dispute?weighted=1', headers=r['headers'], json={
        'session_token': doc['session_token'], 'question_id': '6', 'answer': '1',
    })
    assert report.status_code == 200
    previous = _digest(r['lesson'].content)
    content = dict(r['lesson'].content)
    content['questions'] = [dict(q) for q in content['questions']]
    content['questions'][6]['correct'] = 1
    r['lesson'].content = content
    case = AnswerDispute.query.filter_by(lesson_id=r['lesson'].id).one()
    case.status = 'applied'
    case.review = {'previous_revision': previous, 'updated_revision': _digest(content), 'shown_answer': 'tea'}
    db.session.flush()
    assert credit_approved_reports(case) == {r['user'].id}
    db.session.commit()
    assert LessonAttempt.query.filter_by(lesson_id=r['lesson'].id).count() == 0
    assert send(r, doc, 7, '6', '0').status_code == 409
    fresh = document(r)
    assert (fresh['web_round']['phase'], fresh['web_round']['question_id']) == ('ready', None)
    saved = send(r, fresh, 7, '', '')
    assert saved.status_code == 200 and saved.json['round']['result']['score'] == 100
    assert send(r, fresh, 7, '', '').json == saved.json
    assert LessonAttempt.query.filter_by(lesson_id=r['lesson'].id).count() == 1
    assert StreakEvent.query.filter_by(user_id=r['user'].id, event_type='xp_linear').count() == 1


def test_a_later_web_round_updates_last_and_keeps_best_and_first_score(web_round: dict[str, Any]) -> None:
    r = web_round
    first = document(r)
    for index in range(7):
        assert send(r, first, index, str(index), '0').status_code == 200
    second = document(r)
    assert second['web_round']['id'] != first['web_round']['id']
    for index in range(14):
        outcome = send(r, second, index, str(index % 7), '1' if index < 7 else '0')
        assert outcome.status_code == 200
    assert outcome.json['round']['result']['score'] == 80
    assert outcome.json['round']['result']['web_weighted']['first_score'] == 0
    progress = LessonProgress.query.filter_by(user_id=r['user'].id, lesson_id=r['lesson'].id).one()
    assert (progress.last_score, progress.best_score, progress.score) == (80, 100, 100)
    assert [a.score for a in LessonAttempt.query.filter_by(lesson_id=r['lesson'].id).order_by(LessonAttempt.id)] == [100, 80]
