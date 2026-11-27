"""Idempotent browser submissions keep writing history and completion atomic."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from flask import g

from app.auth.models import User
from app.curriculum.models import LessonAttempt, UserWritingAttempt
from app.curriculum.routes import lessons as routes
from app.utils import languagetool, time_utils
from app.utils.db import db
from tests.api.test_course_receipt_expiry import effects, receipt, sign_in
from tests.curriculum.test_writing_context import A, ANSWER, B, cards, opened, stored, writing


@pytest.fixture
def form(writing: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    token = opened(writing['client'], writing['lesson'].id)
    writing['submit_url'] = f"/curriculum/api/lesson/{writing['lesson'].id}/submit"
    writing['body'] = {'writing_context': token, 'writing_submission_id': uuid4().hex,
                       'response_text': ANSWER, 'checked_items': A['checklist'], 'time_spent_seconds': 77}
    return writing


def submit(form: dict[str, Any], **updates: object) -> Any:
    g.pop('_login_user', None)
    return form['client'].post(form['submit_url'], headers=form['headers'], json=form['body'] | updates)


def test_exact_retry_after_new_prompt_uses_original_receipt(form: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    checks = []

    def check_text(text: str) -> dict:
        checks.append(text)
        return {'error_count': 1, 'matches': [{'offset': 0, 'length': 2, 'message': 'Check wording'}]}

    monkeypatch.setattr(languagetool, 'check_text', check_text)
    first = submit(form)
    assert first.status_code == 200 and first.json['completed']
    row, = stored(form)
    before = (row.id, row.created_at, row.response_text, row.prompt_snapshot)
    after_first = effects(form)
    assert after_first['xp'] == 50 and len(after_first['attempts']) == 1
    assert row.web_submission_receipt['result'] == first.json

    lesson = form['lesson']
    lesson.title, lesson.content, lesson.type = 'A family meal', B, 'quiz'
    db.session.commit()
    replay = submit(form, checked_items=list(reversed(A['checklist'])))
    assert replay.status_code == 200 and replay.json == first.json
    assert checks == [ANSWER]
    assert effects(form) == after_first
    row, = stored(form)
    assert (row.id, row.created_at, row.response_text, row.prompt_snapshot) == before
    assert cards(form['client'])[0].select_one('.writing-history__lesson-title').text == 'A train trip'

    assert submit(form, writing_submission_id=uuid4().hex).status_code == 409


def test_conflict_and_new_intent_independent_of_text(form: dict[str, Any]) -> None:
    assert submit(form).json['completed']
    after_first = effects(form)
    new_opening = opened(form['client'], form['lesson'].id)
    for changes in (
        {'response_text': 'We changed the answer.'},
        {'checked_items': A['checklist'][:1]},
        {'time_spent_seconds': 78},
        {'writing_context': new_opening},
    ):
        response = submit(form, **changes)
        assert response.status_code == 409 and response.json['error'] == 'writing_submission_conflict'
    assert effects(form) == after_first
    assert submit(form, writing_submission_id=uuid4().hex, writing_context=new_opening).json['completed']
    first, second = stored(form)
    assert first.response_text == second.response_text == ANSWER
    assert first.web_submission_id != second.web_submission_id
    assert len(cards(form['client'])) == 2
    assert effects(form)['xp'] == after_first['xp']


def test_author_context_csrf_and_old_form(form: dict[str, Any], test_user: User) -> None:
    client, app = form['client'], form['app']
    assert client.post(form['submit_url'], json=form['body']).status_code != 200
    outsider = app.test_client()
    headers = sign_in(outsider, app, test_user)
    assert outsider.post(form['submit_url'], headers=headers, json=form['body']).status_code == 403
    assert not cards(outsider)
    for changes in ({'writing_context': None}, {'writing_context': form['body']['writing_context'] + 'x'},
                    {'writing_submission_id': 'bad'}, {'checked_items': 'bad'}):
        assert submit(form, **changes).status_code == 400
    assert not stored(form)
    legacy = {key: value for key, value in form['body'].items() if not key.startswith('writing_')}
    for _ in range(2):
        assert client.post(form['submit_url'], headers=form['headers'], json=legacy).json['completed']
    assert len(stored(form)) == 2
    assert all(row.prompt_snapshot is None and row.web_submission_id is None and row.web_submission_receipt is None
               for row in stored(form))


def test_incomplete_and_rollback_do_not_claim_receipt(form: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    before = effects(form)
    assert not submit(form, checked_items=[]).json['completed']
    assert not stored(form)
    assert effects(form) == before

    def fail_analytics(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError('synthetic write failure')

    with monkeypatch.context() as failing:
        failing.setattr(routes, '_record_self_assessed_attempt', fail_analytics)
        assert submit(form).status_code == 500
        assert not stored(form)
        assert effects(form) == before

    assert submit(form).json['completed']
    assert len(stored(form)) == 1
    assert LessonAttempt.query.filter_by(lesson_id=form['lesson'].id).count() == 1


def test_retry_bypasses_quota_without_new_rows_or_time_credit(form: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def challenge(**kw: Any) -> dict:
        seen.append(kw['time_spent_seconds'])
        return {'bonus_xp': 0}

    user, lesson = form['user'], form['lesson']
    user.timezone = 'Asia/Tokyo'
    db.session.commit()
    g.pop('_request_cache', None)
    before_boundary = datetime.now(UTC).replace(hour=16, minute=59, second=0, microsecond=0)
    actual_now = datetime.now(UTC)
    if before_boundary > actual_now:
        before_boundary -= timedelta(days=1)
    after_boundary = before_boundary + timedelta(minutes=2)
    initial_bounds = time_utils.day_to_naive_utc(user.id, db, now_utc=before_boundary)
    next_bounds = time_utils.day_to_naive_utc(user.id, db, now_utc=after_boundary)
    assert next_bounds - initial_bounds == timedelta(days=1)
    monkeypatch.setattr('app.daily_plan.challenge.maybe_auto_complete_challenge', challenge)
    now = before_boundary
    day_bound = time_utils.day_to_naive_utc

    def frozen_day(user_id: int, db_session: Any = None, days_ahead: int = 0) -> datetime:
        return day_bound(user_id, db_session, days_ahead, now_utc=now)

    monkeypatch.setattr(time_utils, 'day_to_naive_utc', frozen_day)
    db.session.add_all([
        UserWritingAttempt(user_id=user.id, lesson_id=lesson.id, response_text='Earlier synthetic attempt.',
                           word_count=3, checklist_completed=True, created_at=initial_bounds + timedelta(minutes=2))
        for _ in range(routes.WRITING_DAILY_LIMIT - 1)
    ])
    db.session.commit()
    accepted = submit(form)
    assert accepted.status_code == 200 and accepted.json['completed']
    bound = UserWritingAttempt.query.filter_by(web_submission_id=form['body']['writing_submission_id']).one()
    bound.created_at = before_boundary.replace(tzinfo=None)
    db.session.commit()
    assert routes._count_writing_attempts_today(user.id) == 70
    assert submit(form).json == accepted.json
    assert submit(form, writing_submission_id=uuid4().hex).status_code == 429
    assert seen == [77]

    now = after_boundary
    assert routes._count_writing_attempts_today(user.id) == 0
    assert submit(form).json == accepted.json
    assert seen == [77]
    assert submit(form, writing_submission_id=uuid4().hex).json['completed']
    assert seen == [77, 77]
