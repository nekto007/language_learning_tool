"""Required filler must remain reachable and participate in day closure."""

from datetime import timedelta

from app.daily_plan.plan import get_daily_plan
from app.daily_plan.plan_builder import _ensure_minimum_items
from app.daily_plan.service import compute_day_secured_from_activity
from app.daily_plan.snapshot import overlay_completion
from app.study.models import WordSetQuizResult
from app.utils.db import db
from tests.daily_plan.test_behind_signal_and_minimum import _user, _lessons, _published_set, _now, _complete


def test_unpublished_filler_is_removed_from_frozen_required(app, db_session):
    user = _user(db_session)
    word_set = _published_set(db_session)
    with app.test_request_context():
        items = _ensure_minimum_items(user.id, db, [{'id': 'course', 'kind': 'curriculum'}])
    filler = items[1]
    word_set.is_published = False
    db_session.commit()
    with app.test_request_context():
        remaining = overlay_completion(user.id, {'items': [filler]}, db)
    assert remaining == [], 'Unpublished required quiz must not leave an unfinishable day'


def test_filler_blocks_day_until_quiz_is_completed(app, db_session):
    user = _user(db_session)
    word_set = _published_set(db_session)
    with app.test_request_context():
        filler = _ensure_minimum_items(user.id, db, [{'id': 'course', 'kind': 'curriculum'}])[1]
        items = overlay_completion(user.id, {'items': [filler]}, db)
    course = {'id': 'course', 'kind': 'curriculum', 'completed': True}
    plan = {'_plan_meta': {'effective_mode': 'unified'}, 'required': [course, *items]}
    assert not compute_day_secured_from_activity(plan, {})
    db_session.add(WordSetQuizResult(user_id=user.id, set_id=word_set.id,
                                    total_questions=3, correct_answers=2,
                                    score_percentage=66.7, time_taken=30, completed_at=_now()))
    db_session.commit()
    with app.test_request_context():
        plan['required'] = [course, *overlay_completion(user.id, {'items': [filler]}, db)]
    assert compute_day_secured_from_activity(plan, {})


def test_optional_does_not_duplicate_required_quiz(app, db_session):
    user = _user(db_session)
    _lessons(db_session, 3)
    _published_set(db_session)
    with app.test_request_context():
        plan = get_daily_plan(user.id, db)
    required_ids = {item['id'] for item in plan['required']}
    assert any(item['kind'] == 'word_set_quiz' for item in plan['required'])
    assert not required_ids.intersection(item['id'] for item in plan['optional'])


def test_history_eight_days_ago_counts_as_before_window(app, db_session):
    from app.daily_plan.tier import pace_status

    user = _user(db_session)
    lesson = _lessons(db_session, 1)[0]
    _complete(db_session, user, lesson, _now() - timedelta(days=8))
    status = pace_status(user.id, db)
    assert status['days_hit'] == 0
    assert status['behind'] is True
