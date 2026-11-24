"""An approved answer restores only the reporter's verified work."""
from typing import Any
from uuid import uuid4

import pytest

from app.curriculum.answer_review_editor import editor_decide, editor_preview, editor_version
from app.curriculum.answer_disputes import AnswerDispute, AnswerDisputeReport
from app.curriculum.dispute_credit import credit_approved_reports
from app.curriculum.models import LessonAttempt, LessonProgress
from app.grammar_lab.answer_review import lab_revision
from app.grammar_lab.models import GrammarAttempt, UserGrammarExercise
from app.notifications.models import Notification
from app.utils.db import db
from tests.answer_review_fixtures import telegram_admin
from tests.api.test_course_receipt_expiry import post, receipt
from tests.api.test_grammar_lab_disputes import dispute as dispute_lab, endpoint, exercise


def report_course(ctx: dict, *, token: str | None = None) -> AnswerDispute:
    response = ctx['client'].post(ctx['endpoint'] + '/dispute', headers=ctx['headers'], json={
        'session_token': token or ctx['doc']['session_token'], 'question_id': '1', 'answer': 'greetings',
    })
    assert response.status_code == 200, response.json
    return AnswerDispute.query.filter_by(lesson_id=ctx['lesson'].id).one()


def prepare(case: AnswerDispute) -> None:
    case.status = 'notified'
    case.review = {'label': 'valid_variant', 'shown_answer': 'greetings',
                   'patch': {'alternatives' if case.grammar_exercise_id else 'alternative_answers': ['greetings']}}
    db.session.commit()


def approve(case: AnswerDispute) -> None:
    prepare(case)
    with telegram_admin() as admin:
        version = editor_version(case)
        assert editor_preview(case, 'add', 'greetings')['accepts_report']
        assert editor_decide(case.id, admin.user_id, version, 'add', 'greetings') == 'Правка сохранена.'
        with pytest.raises(ValueError, match='Спор изменился'):
            editor_decide(case.id, admin.user_id, version, 'add', 'greetings')


def notifications(user_id: int) -> list[Notification]:
    return Notification.query.filter_by(user_id=user_id, type='answer_review').all()


@pytest.mark.parametrize('other_is_correct', [True, False])
def test_approval_restores_score_and_only_resolves_matching_correction(receipt: Any, other_is_correct: bool) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    body = {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0' if other_is_correct else '1', '1': 'greetings'}}
    original = post(ctx, body).json
    assert original['correction_pending']
    progress = LessonProgress.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one()
    attempt = LessonAttempt.query.filter_by(lesson_progress_id=progress.id).one()
    activity = progress.last_activity
    approve(case)
    credit_approved_reports(case)
    db.session.commit()
    assert progress.last_activity == activity
    assert attempt.score == (100 if other_is_correct else 50) == progress.last_score == progress.best_score
    assert attempt.correct_answers == 1 + other_is_correct and attempt.passed
    assert LessonAttempt.query.filter_by(lesson_progress_id=progress.id).count() == 1
    replay = post(ctx, body).json
    assert replay['score'] == attempt.score and replay['feedback'][1]['correct']
    assert replay['completed'] is other_is_correct
    if other_is_correct:
        assert progress.status == 'completed' and progress.completed_at == attempt.completed_at
    else:
        assert progress.status == 'in_progress'
        corrected = ctx['client'].get(ctx['endpoint']).json['lesson']
        assert corrected['quiz_phase'] == 'correction' and [q['id'] for q in corrected['questions']] == ['0']
        assert post(ctx, {'session_token': corrected['session_token'], 'answers': {'0': '0'}}).json['completed']
        assert progress.score == 50
    notice, = notifications(ctx['user'].id)
    assert 'Ответ зачтён' in notice.message and notice.link == f'/learn/{case.lesson_id}/'
    assert AnswerDisputeReport.query.filter_by(dispute_id=case.id).one().credited_at is not None


def test_course_approval_before_submission_scopes_revision_change_to_reporter_session(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    token = ctx['doc']['session_token']
    other_token = ctx['client'].get(ctx['endpoint']).json['lesson']['session_token']
    case = report_course(ctx)
    approve(case)
    assert not LessonAttempt.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).count()
    assert len(notifications(ctx['user'].id)) == 1
    answers = {'0': '0', '1': 'greetings'}
    assert post(ctx, {'session_token': other_token, 'answers': answers}).status_code == 409
    check = ctx['client'].post(ctx['endpoint'] + '/check', headers=ctx['headers'], json={
        'session_token': token, 'question_id': '1', 'answer': 'greetings',
    })
    assert check.json['feedback']['correct']
    assert post(ctx, {'session_token': token, 'answers': answers}).json['score'] == 100
    assert len(notifications(ctx['user'].id)) == 1


def test_changed_submitted_answer_does_not_receive_credit(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    post(ctx, {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'hello'}})
    approve(case)
    assert LessonAttempt.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one().score == 50
    assert AnswerDisputeReport.query.filter_by(dispute_id=case.id).one().credited_at is None
    assert 'зачтён' not in notifications(ctx['user'].id)[0].message


def test_assisted_report_completes_last_correction_and_preserves_independent_score(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    post(ctx, {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'oops'}})
    doc = ctx['client'].get(ctx['endpoint']).json['lesson']
    case = report_course(ctx, token=doc['session_token'])
    approve(case)
    progress = LessonProgress.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one()
    assert progress.status == 'completed' and progress.last_score == 50
    assert progress.data['quiz_correction']['pending_ids'] == []
    assert LessonAttempt.query.filter_by(lesson_progress_id=progress.id).one().score == 50
    assert 'Исправление зачтено' in notifications(ctx['user'].id)[0].message


def test_lab_approval_notifies_once_and_keeps_original_receipt_and_srs_schedule(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    item = exercise('fill_blank', {'question': 'Enter a greeting', 'correct_answer': 'hello'})
    payload = {'submission_id': str(uuid4()), 'exercise_revision': lab_revision(item), 'answer': 'greetings'}
    def submit() -> dict:
        response = ctx['client'].post(endpoint(item) + '/submit', headers=ctx['headers'], json=payload)
        assert response.status_code == 200, response.json
        return response.json

    result = submit()
    assert result['is_correct'] is False
    assert dispute_lab(ctx['client'], ctx['headers'], item, result['dispute_token'], payload['answer']).status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    card = UserGrammarExercise.query.filter_by(user_id=ctx['user'].id, exercise_id=item.id).one()
    before = (card.state, card.interval, card.session_attempts, card.next_review, card.lapses)
    approve(case)
    credit_approved_reports(case)
    db.session.commit()
    assert (card.correct_count, card.incorrect_count) == (1, 0)
    assert (card.state, card.interval, card.session_attempts, card.next_review, card.lapses) == before
    assert GrammarAttempt.query.filter_by(user_id=ctx['user'].id, exercise_id=item.id).one().is_correct
    assert submit()['is_correct'] is False and 'dispute_token' not in submit()
    assert 'упражнении зачтён' in notifications(ctx['user'].id)[0].message
    assert len(notifications(ctx['user'].id)) == 1


def test_notification_failure_rolls_back_grade_and_content(receipt: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    post(ctx, {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'greetings'}})
    prepare(case)
    invalidated: list[int] = []
    monkeypatch.setattr('app.curriculum.services.progress_service._invalidate_user_progress_cache', invalidated.append)
    with telegram_admin() as admin:
        version = editor_version(case)
        assert editor_preview(case, 'add', 'greetings')['accepts_report']
        def fail(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError('Simulated notification persistence failure')
        with monkeypatch.context() as patch:
            patch.setattr('app.curriculum.dispute_credit.create_notification', fail)
            with pytest.raises(RuntimeError):
                editor_decide(case.id, admin.user_id, version, 'add', 'greetings')
            db.session.rollback()
        assert case.status == 'notified'
        assert 'alternative_answers' not in ctx['lesson'].content['questions'][1]
        attempt = LessonAttempt.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one()
        assert attempt.score == 50 and not notifications(ctx['user'].id)
        assert invalidated == []
        assert editor_decide(case.id, admin.user_id, version, 'add', 'greetings') == 'Правка сохранена.'
        assert attempt.score == 100 and len(notifications(ctx['user'].id)) == 1
        assert invalidated == [ctx['user'].id]


def test_historical_approval_preserves_later_attempt_and_current_receipt(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    first = {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'greetings'}}
    assert post(ctx, first).json['score'] == 50
    correction = ctx['client'].get(ctx['endpoint']).json['lesson']
    assert post(ctx, {'session_token': correction['session_token'], 'answers': {'1': 'welcome'}}).json['completed']
    retry = ctx['client'].get(ctx['endpoint']).json['lesson']
    body = {'session_token': retry['session_token'], 'answers': {'0': '1', '1': 'welcome'}}
    latest = post(ctx, body).json
    assert latest['score'] == 50
    approve(case)
    progress = LessonProgress.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one()
    assert progress.last_score == 50 and progress.best_score == 100 and progress.status == 'completed'
    attempts = LessonAttempt.query.filter_by(lesson_progress_id=progress.id).order_by(LessonAttempt.id).all()
    assert [a.score for a in attempts] == [100, 50]
    assert post(ctx, body).json == latest


def test_incomplete_legacy_progress_does_not_prevent_content_fix(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    post(ctx, {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'greetings'}})
    progress = LessonProgress.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one()
    progress.data = ['unsupported historical value']
    db.session.commit()
    approve(case)
    assert progress.data == ['unsupported historical value']
    assert progress.status == 'in_progress'
    assert LessonAttempt.query.filter_by(lesson_progress_id=progress.id).one().score == 100


def test_malformed_historical_mistakes_leave_unverified_score_alone(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    post(ctx, {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'greetings'}})
    attempt = LessonAttempt.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one()
    attempt.mistakes = True
    db.session.commit()
    approve(case)
    assert attempt.score == 50 and case.status == 'applied'
    assert AnswerDisputeReport.query.filter_by(dispute_id=case.id).one().credited_at is None
    assert len(notifications(ctx['user'].id)) == 1


def test_later_verified_lab_attempt_preserves_single_thanks(receipt: Any) -> None:  # noqa: F811
    from app.grammar_lab.dispute_receipts import issue_rejection_receipt

    ctx = receipt
    item = exercise('fill_blank', {'question': 'Enter a greeting', 'correct_answer': 'hello'})
    sent = ctx['client'].post(endpoint(item) + '/submit', headers=ctx['headers'], json={'answer': 'greetings'}).json
    legacy = issue_rejection_receipt(ctx['user'].id, item.id, lab_revision(item), 'greetings')
    assert dispute_lab(ctx['client'], ctx['headers'], item, legacy, 'greetings').status_code == 200
    case = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    approve(case)
    attempt = GrammarAttempt.query.filter_by(user_id=ctx['user'].id, exercise_id=item.id).one()
    assert not attempt.is_correct and len(notifications(ctx['user'].id)) == 1
    assert dispute_lab(ctx['client'], ctx['headers'], item, sent['dispute_token'], 'greetings').status_code == 200
    assert attempt.is_correct and len(notifications(ctx['user'].id)) == 1


def test_different_editorial_correction_thanks_without_granting_credit(receipt: Any) -> None:  # noqa: F811
    ctx = receipt
    case = report_course(ctx)
    post(ctx, {'session_token': ctx['doc']['session_token'], 'answers': {'0': '0', '1': 'greetings'}})
    case.status = 'applied'
    case.review = {'accepts_report': False}
    assert credit_approved_reports(case) == set()
    db.session.commit()
    assert credit_approved_reports(case) == set()
    db.session.commit()
    notice, = notifications(ctx['user'].id)
    assert 'Мы исправили задание' in notice.message and 'остаётся прежней' in notice.message
    report = AnswerDisputeReport.query.filter_by(dispute_id=case.id).one()
    assert report.thanked_at is not None and report.credited_at is None
    assert LessonAttempt.query.filter_by(user_id=ctx['user'].id, lesson_id=case.lesson_id).one().score == 50
