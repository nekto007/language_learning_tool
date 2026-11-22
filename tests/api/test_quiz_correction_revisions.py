"""Changed plain quizzes preserve old diagnostics without reusing their IDs."""
from copy import deepcopy

import pytest

from tests.api.test_quiz_corrections import (
    course as _course, document, native_app as _native_app, submit, progress_and_attempts,
)


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def course(native_app, monkeypatch):
    return _course.__wrapped__(native_app, monkeypatch)


def update_question(model):
    from app.utils.db import db
    content = deepcopy(model.content)
    content['exercises'][0].update(
        question='Correct: We is at school.', correct_answer='We are at school.', explanation='We + are.',
    )
    model.content = content
    db.session.commit()


@pytest.mark.parametrize('untagged_legacy_log', [False, True])
def test_changed_plain_revision_gets_new_error_without_resolving_old(course, untagged_legacy_log):
    from app.daily_plan.linear.errors import get_review_pool, count_unresolved
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db
    user, _, model, _, _ = course
    first = document(course)
    submit(course, first, {'0': 'She go to school', '1': '1'})
    previous = progress_and_attempts(course)[0].data['quiz_correction']
    old_error = QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id).one()
    old_id = old_error.id
    if untagged_legacy_log:
        old_error.question_payload = {key: value for key, value in old_error.question_payload.items()
                                      if key not in ('quiz_revision', 'quiz_attempt_id')}
        db.session.commit()
    update_question(model)
    restarted = document(course)
    assert restarted['quiz_phase'] == 'first'
    submitted = submit(course, restarted, {'0': 'We is at school', '1': '1'})
    assert submitted.status_code == 200, submitted.json
    state = progress_and_attempts(course)[0].data['quiz_correction']
    assert state['revision'] != previous['revision']
    assert state['attempt_id'] != previous['attempt_id']
    logs = QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id).order_by(QuizErrorLog.id).all()
    assert len(logs) == 2  # Same positional ID in different content must not deduplicate.
    old_error, current_error = logs
    assert old_error.id == old_id and old_error.resolved_at is None
    assert old_error.question_payload['quiz_superseded'] is True
    assert current_error.question_payload['quiz_revision'] == state['revision']
    assert current_error.question_payload['quiz_attempt_id'] == state['attempt_id']
    assert not current_error.question_payload.get('quiz_superseded')
    assert count_unresolved(user.id, db) == 1
    assert [row.id for row in get_review_pool(user.id, db)] == [current_error.id]
    # A network retry cannot archive the new revision or add another log.
    assert submit(course, restarted, {'0': 'We is at school', '1': '1'}).json == submitted.json
    assert QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id).count() == 2
    correction = document(course)
    response = submit(course, correction, {'0': 'We are at school'})
    assert response.status_code == 200 and response.json['completed'], response.json
    db.session.expire_all()
    assert db.session.get(QuizErrorLog, old_id).resolved_at is None
    assert db.session.get(QuizErrorLog, current_error.id).resolved_at is not None
    assert count_unresolved(user.id, db) == 0
    assert len(progress_and_attempts(course)[1]) == 2  # Only the independent rounds.


def test_updated_all_correct_round_archives_old_errors_without_fake_resolution(course):
    from app.daily_plan.linear.errors import count_unresolved
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db
    user, _, model, _, _ = course
    submit(course, document(course), {'0': 'She go to school', '1': '1'})
    old_error = QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id).one()
    old_id = old_error.id
    update_question(model)
    response = submit(course, document(course), {'0': 'We are at school', '1': '1'})
    assert response.status_code == 200 and response.json['completed'], response.json
    old_error = db.session.get(QuizErrorLog, old_id)
    assert old_error.resolved_at is None
    assert old_error.question_payload['quiz_superseded'] is True
    assert count_unresolved(user.id, db) == 0
    assert QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id).count() == 1
    assert progress_and_attempts(course)[0].status == 'completed'


@pytest.mark.parametrize('all_correct', [False, True])
def test_legacy_progress_enrollment_archives_untagged_live_error(course, all_correct):
    from app.daily_plan.linear.errors import count_unresolved
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db
    user, _, model, _, _ = course
    legacy = document(course, optin=False)
    submit(course, legacy, {'0': 'She go to school', '1': '0'})
    progress, _ = progress_and_attempts(course)
    assert progress.status == 'in_progress' and not progress.data.get('quiz_correction')
    old_error = QuizErrorLog(user_id=user.id, lesson_id=model.id,
                             question_payload={'question_index': 0, 'question_text': 'Legacy question'})
    db.session.add(old_error)
    db.session.commit()
    old_id = old_error.id
    answers = {'0': 'She goes to school' if all_correct else 'She go to school', '1': '1'}
    response = submit(course, document(course), answers)
    assert response.status_code == 200, response.json
    old_error = db.session.get(QuizErrorLog, old_id)
    assert old_error.resolved_at is None and old_error.question_payload['quiz_superseded'] is True
    assert count_unresolved(user.id, db) == (0 if all_correct else 1)
    current = [row for row in QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id).all()
               if not row.question_payload.get('quiz_superseded')]
    if all_correct:
        assert response.json['completed'] and not current
    else:
        assert response.json['correction_pending'] and len(current) == 1
        state = progress_and_attempts(course)[0].data['quiz_correction']
        assert current[0].question_payload['quiz_attempt_id'] == state['attempt_id']
        assert current[0].question_payload['quiz_revision'] == state['revision']
